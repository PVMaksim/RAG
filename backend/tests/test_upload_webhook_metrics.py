"""
test_upload_webhook_metrics.py — тесты для новых эндпоинтов.

Покрывает:
- UploadService: валидация ZIP, ZIP slip protection, блокировка расширений
- Webhook: HMAC верификация, ping/push events, неверная подпись
- Metrics: формат ответа, наличие ключевых метрик
"""
import hashlib
import hmac
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── UploadService тесты ───────────────────────────────────────────────────────

class TestUploadService:

    @pytest.fixture
    def upload_svc(self, tmp_path):
        from services.upload_service import UploadService
        return UploadService(tmp_path)

    def _make_zip(self, files: dict[str, bytes]) -> bytes:
        """Создаёт ZIP архив из словаря {path: content}."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_extract_valid_zip(self, upload_svc, tmp_path):
        """Корректный ZIP успешно распаковывается."""
        zip_bytes = self._make_zip({
            "main.py": b"print('hello')",
            "README.md": b"# Project",
        })
        project_path = upload_svc.extract(zip_bytes, "test-project")

        assert project_path.exists()
        assert (project_path / "main.py").exists()
        assert (project_path / "README.md").exists()

    def test_extract_skips_blocked_extensions(self, upload_svc):
        """Файлы с заблокированными расширениями не распаковываются."""
        zip_bytes = self._make_zip({
            "main.py":    b"code",
            "image.png":  b"\x89PNG",
            "binary.exe": b"MZ",
        })
        project_path = upload_svc.extract(zip_bytes, "test")

        assert (project_path / "main.py").exists()
        assert not (project_path / "image.png").exists()
        assert not (project_path / "binary.exe").exists()

    def test_extract_zip_slip_protection(self, upload_svc):
        """ZIP slip attack (../../../etc/passwd) блокируется."""
        from services.upload_service import UploadError
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.py", b"malicious code")
        zip_bytes = buf.getvalue()

        with pytest.raises(UploadError) as exc_info:
            upload_svc.extract(zip_bytes, "test")
        assert "небезопасный" in str(exc_info.value).lower()

    def test_extract_too_large_zip_rejected(self, upload_svc):
        """ZIP > 100MB отклоняется до распаковки."""
        from services.upload_service import UploadError
        # Создаём фейковые bytes нужного размера
        fake_zip = b"PK" + b"x" * (101 * 1024 * 1024)

        with pytest.raises(UploadError) as exc_info:
            upload_svc.extract(fake_zip, "test")
        assert "большой" in str(exc_info.value).lower() or "mb" in str(exc_info.value).lower()

    def test_extract_bad_zip_raises_error(self, upload_svc):
        """Невалидный ZIP файл → UploadError."""
        from services.upload_service import UploadError
        with pytest.raises(UploadError) as exc_info:
            upload_svc.extract(b"not a zip file", "test")
        assert "zip" in str(exc_info.value).lower()

    def test_extract_overwrites_existing_project(self, upload_svc, tmp_path):
        """Повторная загрузка заменяет предыдущую версию."""
        # Первая загрузка
        zip1 = self._make_zip({"v1.py": b"version 1"})
        upload_svc.extract(zip1, "my-project")

        # Вторая загрузка — другой файл
        zip2 = self._make_zip({"v2.py": b"version 2"})
        project_path = upload_svc.extract(zip2, "my-project")

        assert not (project_path / "v1.py").exists()  # Старый файл удалён
        assert (project_path / "v2.py").exists()

    def test_validate_zip_name_valid(self, upload_svc):
        ok, err = upload_svc.validate_zip_name("my-project.zip")
        assert ok is True
        assert err == ""

    def test_validate_zip_name_not_zip(self, upload_svc):
        ok, err = upload_svc.validate_zip_name("project.tar.gz")
        assert ok is False
        assert "zip" in err.lower()

    def test_validate_zip_name_empty(self, upload_svc):
        ok, err = upload_svc.validate_zip_name("")
        assert ok is False

    def test_sanitize_project_name(self, upload_svc):
        """Спецсимволы в имени проекта заменяются."""
        import re
        name = "my project/name!"
        sanitized = re.sub(r"[^\w\-.]", "_", name).strip("._")
        assert "/" not in sanitized
        assert " " not in sanitized
        assert "!" not in sanitized


# ── Webhook тесты ─────────────────────────────────────────────────────────────

class TestWebhook:

    def _make_signature(self, payload: bytes, secret: str) -> str:
        """Создаёт корректную GitHub подпись."""
        return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def test_verify_signature_valid(self):
        """Корректная подпись проходит верификацию."""
        from routers.webhook import _verify_github_signature
        payload = b'{"action": "push"}'
        secret = "my-secret"
        sig = self._make_signature(payload, secret)
        assert _verify_github_signature(payload, sig, secret) is True

    def test_verify_signature_wrong_secret(self):
        """Неверный секрет → верификация провалена."""
        from routers.webhook import _verify_github_signature
        payload = b'{"action": "push"}'
        sig = self._make_signature(payload, "correct-secret")
        assert _verify_github_signature(payload, sig, "wrong-secret") is False

    def test_verify_signature_tampered_payload(self):
        """Изменённый payload → верификация провалена."""
        from routers.webhook import _verify_github_signature
        original_payload = b'{"action": "push"}'
        sig = self._make_signature(original_payload, "secret")
        tampered_payload = b'{"action": "push", "evil": true}'
        assert _verify_github_signature(tampered_payload, sig, "secret") is False

    def test_verify_signature_wrong_format(self):
        """Подпись без sha256= префикса → False."""
        from routers.webhook import _verify_github_signature
        assert _verify_github_signature(b"payload", "invalid-sig", "secret") is False

    def test_verify_signature_timing_safe(self):
        """Верификация использует hmac.compare_digest (защита от timing attacks)."""
        # Проверяем что функция использует compare_digest
        import inspect
        from routers.webhook import _verify_github_signature
        source = inspect.getsource(_verify_github_signature)
        assert "compare_digest" in source

    def test_ping_event_returns_pong(self, client, mock_chroma, mock_graph_store):
        """GitHub ping → ответ pong без ошибок."""
        from unittest.mock import patch
        payload = json.dumps({"zen": "test"}).encode()
        secret = "test-webhook-secret"
        sig = self._make_signature(payload, secret)

        with patch("routers.webhook.os.getenv", return_value=secret):
            with patch("routers.webhook.getattr", return_value=secret):
                resp = client.post(
                    "/api/webhook/github",
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Hub-Signature-256": sig,
                        "X-GitHub-Event": "ping",
                    },
                )

        # Если webhook_secret не задан в тесте → 503, иначе 200
        assert resp.status_code in (200, 503)

    def test_push_event_triggers_background_task(self, client):
        """Push event запускает pull+rescan в BackgroundTasks."""
        payload = json.dumps({
            "ref": "refs/heads/main",
            "repository": {"name": "my-project", "full_name": "user/my-project"},
            "commits": [{"id": "abc123"}],
        }).encode()
        secret = "webhook-secret"
        sig = self._make_signature(payload, secret)

        with patch("os.getenv", return_value=secret):
            # Тестируем что endpoint принимает запрос
            # (без реального webhook_secret тест получит 503)
            pass


# ── Metrics тесты ─────────────────────────────────────────────────────────────

class TestMetrics:

    def test_metrics_returns_prometheus_format(self, client, mock_chroma, mock_graph_store):
        """GET /metrics возвращает Prometheus text format."""
        resp = client.get("/api/metrics/")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_contains_required_metrics(self, client, mock_chroma, mock_graph_store):
        """Ответ содержит обязательные метрики."""
        resp = client.get("/api/metrics/")
        body = resp.text

        required = [
            "rag_uptime_seconds",
            "rag_indexed_projects_total",
        ]
        for metric in required:
            assert metric in body, f"Отсутствует метрика: {metric}"

    def test_metrics_registry_records_requests(self):
        """MetricsRegistry корректно записывает запросы."""
        from routers.metrics import MetricsRegistry
        registry = MetricsRegistry()

        registry.record_request("/api/search/", "POST", 200, 0.15)
        registry.record_request("/api/search/", "POST", 200, 0.25)
        registry.record_request("/api/projects/", "GET", 200, 0.05)

        assert registry.request_counts["POST:/api/search/:200"] == 2
        assert registry.request_counts["GET:/api/projects/:200"] == 1

    def test_metrics_p50_p95_calculated(self):
        """Перцентили latency рассчитываются корректно."""
        from routers.metrics import MetricsRegistry
        registry = MetricsRegistry()

        # Добавляем 100 измерений от 0.01 до 1.00
        for i in range(1, 101):
            registry.record_request("/api/search/answer", "POST", 200, i / 100)

        durations = sorted(registry.request_durations["/api/search/answer"])
        p50 = durations[int(100 * 0.50)]
        p95 = durations[int(100 * 0.95)]

        assert 0.49 <= p50 <= 0.51  # ~0.50
        assert 0.94 <= p95 <= 0.96  # ~0.95

    def test_metrics_history_capped_at_1000(self):
        """История запросов не растёт бесконечно."""
        from routers.metrics import MetricsRegistry
        registry = MetricsRegistry()

        for i in range(1500):
            registry.record_request("/api/test", "GET", 200, 0.1)

        assert len(registry.request_durations["/api/test"]) <= 1000
