"""
git_service.py — сервис клонирования проектов из Git репозиториев.

Позволяет добавлять проекты на VPS по URL вместо ручного копирования файлов.
Поддерживает: GitHub, GitLab, Bitbucket, любой публичный git репозиторий.
Приватные репозитории — через SSH ключ или токен в URL.

Pipeline:
  git_url → clone/pull → projects_base_path/{project_name} → scan
"""
import asyncio
import logging
import re
import shutil
from pathlib import Path

from exceptions import ProjectPathNotFoundError, RAGError
from logging_config import timed

log = logging.getLogger(__name__)

# Максимальный размер репозитория (защита от гигантских репо)
MAX_REPO_SIZE_MB = 500


class GitServiceError(RAGError):
    """Ошибка при работе с Git репозиторием."""
    http_status = 400
    log_level = "warning"


class GitService:
    """
    Клонирует и обновляет Git репозитории в projects_base_path.
    Использует системный git через asyncio subprocess.
    """

    def __init__(self, projects_base_path: Path) -> None:
        self._base = projects_base_path
        self._base.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────

    @timed("git_clone")
    async def clone_or_pull(self, git_url: str, project_name: str | None = None) -> Path:
        """
        Клонирует репозиторий или делает pull если уже существует.
        Возвращает путь к папке проекта.

        Args:
            git_url:      URL репозитория (https:// или git@)
            project_name: Имя папки (по умолчанию — из URL)

        Returns:
            Path к директории проекта
        """
        await self._check_git_available()

        name = project_name or self._name_from_url(git_url)
        if not name:
            raise GitServiceError(f"Не удалось определить имя проекта из URL: {git_url}")

        # Санитизация имени папки
        name = re.sub(r"[^\w\-.]", "_", name).strip("._")
        if not name:
            raise GitServiceError(f"Неверное имя проекта: {project_name}")

        project_path = self._base / name

        if project_path.exists():
            log.info("Репозиторий существует, делаю pull", extra={"project": name})
            await self._git_pull(project_path)
        else:
            log.info("Клонирую репозиторий", extra={"url": git_url, "project": name})
            await self._git_clone(git_url, project_path)

        return project_path

    async def delete(self, project_name: str) -> None:
        """Удалить папку проекта с диска."""
        project_path = self._base / project_name
        if project_path.exists():
            shutil.rmtree(project_path)
            log.info("Папка проекта удалена", extra={"project": project_name})

    def list_local(self) -> list[dict]:
        """Список папок в projects_base_path (не обязательно Git репо)."""
        result = []
        for p in sorted(self._base.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                is_git = (p / ".git").exists()
                result.append({
                    "name":   p.name,
                    "path":   str(p),
                    "is_git": is_git,
                    "remote": self._get_remote_url(p) if is_git else None,
                })
        return result

    # ── Git operations ────────────────────────────────────────────────────

    async def _git_clone(self, url: str, path: Path) -> None:
        """Клонирует репозиторий с shallow clone (только последний коммит)."""
        cmd = [
            "git", "clone",
            "--depth", "1",          # shallow: только HEAD → быстро
            "--single-branch",        # только основная ветка
            "--filter=blob:none",     # не скачивать содержимое файлов сразу (partial clone)
            url,
            str(path),
        ]
        await self._run_git(cmd, cwd=self._base)
        log.info("Клонирование завершено", extra={"path": str(path)})

    async def _git_pull(self, path: Path) -> None:
        """Обновляет существующий репозиторий."""
        cmd = ["git", "pull", "--ff-only", "--depth", "1"]
        await self._run_git(cmd, cwd=path)
        log.info("Pull завершён", extra={"path": str(path)})

    async def _run_git(self, cmd: list[str], cwd: Path) -> str:
        """Запускает git команду в subprocess. Кидает GitServiceError при ошибке."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Ограничиваем время: 5 минут на clone/pull
                env={
                    **__import__("os").environ,
                    "GIT_TERMINAL_PROMPT": "0",   # не запрашивать пароль
                },
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=300
                )
            except asyncio.TimeoutError:
                proc.kill()
                raise GitServiceError(
                    f"Git операция превысила 5 минут: {' '.join(cmd[:3])}",
                    url=str(cwd),
                )

            if proc.returncode != 0:
                err_text = stderr.decode(errors="replace").strip()
                # Маскируем токены из URL в логах
                safe_cmd = " ".join(
                    re.sub(r"https?://[^@]+@", "https://***@", part)
                    for part in cmd
                )
                log.error(
                    "Git ошибка",
                    extra={"cmd": safe_cmd, "stderr": err_text[:500]},
                )
                # Убираем токены из сообщения пользователю
                safe_err = re.sub(r"https?://[^@]+@", "https://***@", err_text)
                raise GitServiceError(
                    f"Git ошибка: {safe_err[:300]}",
                    exit_code=proc.returncode,
                )

            return stdout.decode(errors="replace")

        except GitServiceError:
            raise
        except Exception as exc:
            raise GitServiceError(f"Не удалось запустить git: {exc}") from exc

    # ── Утилиты ───────────────────────────────────────────────────────────

    async def _check_git_available(self) -> None:
        """Проверяет что git установлен в системе."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise GitServiceError(
                    "git не установлен или недоступен. "
                    "Установи: apt install git"
                )
        except FileNotFoundError:
            raise GitServiceError(
                "git не найден в PATH. "
                "В Docker образе бэкенда нужно добавить: RUN apt-get install -y git"
            )

    @staticmethod
    def _name_from_url(url: str) -> str:
        """
        Извлекает имя проекта из Git URL.
        https://github.com/user/my-project.git → my-project
        git@github.com:user/my-project.git    → my-project
        """
        # Убираем .git суффикс
        url = url.rstrip("/").removesuffix(".git")
        # Берём последний сегмент пути
        return url.split("/")[-1].split(":")[-1] or ""

    @staticmethod
    def _get_remote_url(path: Path) -> str | None:
        """Получает URL remote origin."""
        try:
            config = (path / ".git" / "config").read_text(errors="replace")
            for line in config.splitlines():
                if "url = " in line:
                    url = line.split("url = ", 1)[1].strip()
                    # Маскируем токены
                    return re.sub(r"https?://[^@]+@", "https://***@", url)
        except Exception:
            pass
        return None

    @staticmethod
    def validate_git_url(url: str) -> tuple[bool, str]:
        """
        Базовая валидация Git URL.
        Возвращает (valid, error_message).
        """
        url = url.strip()
        if not url:
            return False, "URL не может быть пустым"

        # HTTPS URL
        if url.startswith(("https://", "http://")):
            if not re.match(r"https?://[^\s/$.?#].[^\s]*", url):
                return False, "Неверный HTTPS URL"
            return True, ""

        # SSH URL (git@github.com:user/repo.git)
        if url.startswith("git@"):
            if not re.match(r"git@[\w.]+:[\w./\-]+", url):
                return False, "Неверный SSH URL (ожидается: git@host:user/repo)"
            return True, ""

        return False, "URL должен начинаться с https:// или git@"
