"""
test_git_service.py — тесты для GitService.

Проверяем:
- Валидацию URL (https, ssh, пустые, невалидные)
- Извлечение имени проекта из URL
- Обработку ошибок git (timeout, non-zero exit)
- Маскировку токенов в логах
- list_local()
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


@pytest.fixture
def git_svc(tmp_path):
    from services.git_service import GitService
    return GitService(tmp_path)


class TestValidateGitUrl:

    def test_valid_https(self, git_svc):
        ok, err = git_svc.validate_git_url("https://github.com/user/repo.git")
        assert ok is True
        assert err == ""

    def test_valid_https_no_git_suffix(self, git_svc):
        ok, err = git_svc.validate_git_url("https://github.com/user/my-project")
        assert ok is True

    def test_valid_ssh(self, git_svc):
        ok, err = git_svc.validate_git_url("git@github.com:user/repo.git")
        assert ok is True

    def test_invalid_empty(self, git_svc):
        ok, err = git_svc.validate_git_url("")
        assert ok is False
        assert "пустым" in err

    def test_invalid_no_scheme(self, git_svc):
        ok, err = git_svc.validate_git_url("github.com/user/repo")
        assert ok is False

    def test_invalid_ftp(self, git_svc):
        ok, err = git_svc.validate_git_url("ftp://github.com/repo")
        assert ok is False

    def test_url_with_spaces(self, git_svc):
        ok, err = git_svc.validate_git_url("  https://github.com/user/repo  ")
        # Пробелы должны триммироваться
        assert ok is True


class TestNameFromUrl:

    def _name(self, url):
        from services.git_service import GitService
        return GitService._name_from_url(url)

    def test_https_with_git_suffix(self):
        assert self._name("https://github.com/user/my-project.git") == "my-project"

    def test_https_without_git_suffix(self):
        assert self._name("https://github.com/user/my-project") == "my-project"

    def test_ssh_url(self):
        assert self._name("git@github.com:user/my-project.git") == "my-project"

    def test_trailing_slash(self):
        assert self._name("https://github.com/user/repo/") == "repo"

    def test_nested_path(self):
        result = self._name("https://gitlab.com/group/subgroup/project.git")
        assert result == "project"


class TestCloneOrPull:

    @pytest.mark.asyncio
    async def test_clone_new_project(self, git_svc, tmp_path):
        """Клонирует новый проект если папки нет."""
        with patch.object(git_svc, '_check_git_available', new_callable=AsyncMock):
            with patch.object(git_svc, '_git_clone', new_callable=AsyncMock) as mock_clone:
                result = await git_svc.clone_or_pull(
                    "https://github.com/user/my-project.git"
                )

        mock_clone.assert_called_once()
        assert result.name == "my-project"

    @pytest.mark.asyncio
    async def test_pull_existing_project(self, git_svc, tmp_path):
        """Делает pull если папка уже существует."""
        project_dir = git_svc._base / "my-project"
        project_dir.mkdir()

        with patch.object(git_svc, '_check_git_available', new_callable=AsyncMock):
            with patch.object(git_svc, '_git_pull', new_callable=AsyncMock) as mock_pull:
                result = await git_svc.clone_or_pull(
                    "https://github.com/user/my-project.git"
                )

        mock_pull.assert_called_once()
        assert result == project_dir

    @pytest.mark.asyncio
    async def test_custom_project_name(self, git_svc):
        """Уважает явно указанное имя проекта."""
        with patch.object(git_svc, '_check_git_available', new_callable=AsyncMock):
            with patch.object(git_svc, '_git_clone', new_callable=AsyncMock):
                result = await git_svc.clone_or_pull(
                    "https://github.com/user/repo.git",
                    project_name="my_custom_name"
                )

        assert result.name == "my_custom_name"

    @pytest.mark.asyncio
    async def test_invalid_chars_in_name_sanitized(self, git_svc):
        """Спецсимволы в имени проекта заменяются на _."""
        with patch.object(git_svc, '_check_git_available', new_callable=AsyncMock):
            with patch.object(git_svc, '_git_clone', new_callable=AsyncMock):
                result = await git_svc.clone_or_pull(
                    "https://github.com/user/repo.git",
                    project_name="my project/name!"
                )

        # Спецсимволы заменены
        assert "/" not in result.name
        assert "!" not in result.name


class TestGitErrors:

    @pytest.mark.asyncio
    async def test_timeout_raises_git_service_error(self, git_svc):
        """Таймаут git clone → GitServiceError."""
        from services.git_service import GitServiceError

        async def slow_process(*args, **kwargs):
            mock = AsyncMock()
            mock.communicate.side_effect = asyncio.TimeoutError()
            return mock

        with patch.object(git_svc, '_check_git_available', new_callable=AsyncMock):
            with patch('asyncio.create_subprocess_exec', side_effect=slow_process):
                with pytest.raises(GitServiceError) as exc_info:
                    await git_svc.clone_or_pull("https://github.com/user/repo.git")

        assert "5 минут" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_git_error_masks_token_in_url(self, git_svc):
        """Токен в HTTPS URL не должен попасть в сообщение об ошибке."""
        from services.git_service import GitServiceError

        async def failing_proc(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 128
            proc.communicate.return_value = (
                b"",
                b"fatal: Authentication failed for 'https://user:secret_token@github.com/user/private.git/'"
            )
            return proc

        with patch.object(git_svc, '_check_git_available', new_callable=AsyncMock):
            with patch('asyncio.create_subprocess_exec', side_effect=failing_proc):
                with pytest.raises(GitServiceError) as exc_info:
                    await git_svc._git_clone(
                        "https://user:secret_token@github.com/user/private.git",
                        git_svc._base / "private"
                    )

        error_msg = str(exc_info.value)
        assert "secret_token" not in error_msg
        assert "***" in error_msg

    @pytest.mark.asyncio
    async def test_git_not_installed(self, git_svc):
        """Если git не установлен → понятная ошибка."""
        from services.git_service import GitServiceError

        with patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError):
            with pytest.raises(GitServiceError) as exc_info:
                await git_svc._check_git_available()

        assert "git не найден" in str(exc_info.value)


class TestListLocal:

    def test_lists_directories(self, git_svc):
        """list_local() возвращает папки в base_path."""
        (git_svc._base / "project_a").mkdir()
        (git_svc._base / "project_b").mkdir()
        (git_svc._base / ".hidden").mkdir()  # скрытые не показываем

        result = git_svc.list_local()
        names = [p["name"] for p in result]

        assert "project_a" in names
        assert "project_b" in names
        assert ".hidden" not in names

    def test_detects_git_repos(self, git_svc):
        """Git репозиторий детектируется по наличию .git папки."""
        project = git_svc._base / "my_repo"
        project.mkdir()
        (project / ".git").mkdir()

        result = git_svc.list_local()
        repo = next(p for p in result if p["name"] == "my_repo")
        assert repo["is_git"] is True

    def test_non_git_folder(self, git_svc):
        """Обычная папка — is_git=False."""
        (git_svc._base / "plain_folder").mkdir()

        result = git_svc.list_local()
        folder = next(p for p in result if p["name"] == "plain_folder")
        assert folder["is_git"] is False
