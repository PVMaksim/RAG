"""
webhook.py — GitHub Webhook для автоматического обновления проектов.

При каждом push в репозиторий GitHub отправляет POST запрос на этот эндпоинт.
Мы делаем git pull и переиндексируем проект.

Настройка в GitHub:
  Settings → Webhooks → Add webhook
  Payload URL: https://rag.yourdomain.com/api/webhook/github
  Content type: application/json
  Secret: значение WEBHOOK_SECRET из .env
  Events: Just the push event

Безопасность:
  HMAC-SHA256 верификация подписи X-Hub-Signature-256 от GitHub.
  Запросы без верной подписи отклоняются с 403.
"""
import hashlib
import hmac
import logging
import os

# HTTPException используется намеренно: 401/403/400 здесь — протокольные ответы,
# а не бизнес-ошибки. GitHub ожидает именно эти HTTP статусы.
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from config import get_settings
from dependencies import get_scanner
from services.git_service import GitService
from services.scanner import ProjectScanner

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_github_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """
    Верифицирует HMAC-SHA256 подпись от GitHub.
    GitHub отправляет: X-Hub-Signature-256: sha256=<hex>
    """
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    # Используем hmac.compare_digest для защиты от timing attacks
    return hmac.compare_digest(expected, signature_header)


async def _pull_and_rescan(
    project_name: str,
    projects_base_path,
    scanner: ProjectScanner,
    clone_url: str = "",
) -> None:
    """
    Фоновая задача: git pull + переиндексирование.
    Запускается через BackgroundTasks — не блокирует webhook ответ.
    """
    from pathlib import Path
    project_path = Path(projects_base_path) / project_name

    git_svc = GitService(Path(projects_base_path))

    # Если проекта нет локально — клонируем автоматически
    if not project_path.exists():
        if not clone_url:
            log.warning(
                "Webhook: проект не найден и clone_url не задан",
                extra={"project": project_name},
            )
            return
        log.info(
            "Webhook: проект не найден, клонирую",
            extra={"project": project_name, "url": clone_url},
        )
        try:
            project_path = await git_svc.clone_or_pull(clone_url, project_name)
        except Exception as e:
            log.error(
                "Webhook: клонирование упало",
                extra={"project": project_name, "url": clone_url},
                exc_info=True,
            )
            return
    elif not (project_path / ".git").exists():
        log.warning(
            "Webhook: папка не является git репозиторием",
            extra={"project": project_name},
        )
        return
    else:
        log.info("Webhook: запускаю git pull", extra={"project": project_name})
        try:
            await git_svc.clone_or_pull(
                GitService._get_remote_url(project_path) or "",
                project_name,
            )
            log.info("Webhook: git pull успешен", extra={"project": project_name})
        except Exception as e:
            log.error("Webhook: git pull упал", extra={"project": project_name, "error": str(e)})
            return

    # Переиндексируем
    log.info("Webhook: начинаю переиндексирование", extra={"project": project_name})
    try:
        async for progress in scanner.scan(project_path):
            if progress.type == "done":
                log.info(
                    "Webhook: переиндексирование завершено",
                    extra={
                        "project": project_name,
                        "indexed": progress.files_indexed,
                        "duration": progress.duration_sec,
                    },
                )
    except Exception as e:
        log.error(
            "Webhook: переиндексирование упало",
            extra={"project": project_name},
            exc_info=True,
        )


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
    scanner: ProjectScanner = Depends(get_scanner),
    settings=Depends(get_settings),
) -> dict:
    """
    Обрабатывает GitHub Webhook (push event).

    При получении push:
    1. Верифицирует HMAC подпись
    2. Определяет имя проекта из URL репозитория
    3. Запускает git pull + rescan в фоне
    4. Немедленно возвращает 200 (GitHub ждёт быстрый ответ)
    """
    # Проверяем что WEBHOOK_SECRET задан
    webhook_secret = getattr(settings, "webhook_secret", None) or os.getenv("WEBHOOK_SECRET", "")

    if not webhook_secret:
        log.warning("WEBHOOK_SECRET не задан — webhook небезопасен")
        raise HTTPException(
            status_code=503,
            detail="Webhook не настроен. Задай WEBHOOK_SECRET в .env",
        )

    # Читаем тело запроса для верификации
    payload = await request.body()

    # Верификация подписи
    if not _verify_github_signature(payload, x_hub_signature_256, webhook_secret):
        log.warning(
            "Webhook: неверная подпись",
            extra={"event": x_github_event, "ip": request.client.host if request.client else "?"},
        )
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Только push events
    if x_github_event == "ping":
        return {"status": "pong", "message": "Webhook настроен корректно"}

    if x_github_event != "push":
        return {"status": "ignored", "event": x_github_event}

    # Парсим payload
    import json
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Определяем имя репозитория → имя проекта
    repo = data.get("repository", {})
    repo_name = repo.get("name", "")
    repo_full = repo.get("full_name", "")

    if not repo_name:
        return {"status": "ignored", "reason": "no repository name in payload"}

    branch = data.get("ref", "").removeprefix("refs/heads/")

    log.info(
        "Webhook: получен push",
        extra={
            "repo":    repo_full,
            "branch":  branch,
            "commits": len(data.get("commits", [])),
        },
    )

    # Запускаем pull+rescan в фоне чтобы быстро ответить GitHub
    # Передаём URL репозитория для автоклонирования если проект не найден
    clone_url = repo.get("clone_url", "") or repo.get("ssh_url", "")

    background_tasks.add_task(
        _pull_and_rescan,
        project_name=repo_name,
        projects_base_path=settings.projects_base_path,
        scanner=scanner,
        clone_url=clone_url,
    )

    return {
        "status":  "accepted",
        "project": repo_name,
        "branch":  branch,
        "message": f"git pull + rescan запущен в фоне для '{repo_name}'",
    }
