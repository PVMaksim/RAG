"""
test_scanner.py — юнит-тесты для сервиса сканирования.

Проверяем:
- Фильтрацию файлов (FileFilter)
- Извлечение сигнатур (ContentExtractor)
- Определение типа проекта (ProjectTypeDetector)
- Генерацию прогресс-событий (ProjectScanner.scan)
"""
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ── Фикстура: файловая система тестового проекта ──────────────────────────────

@pytest.fixture
def python_project(tmp_path: Path) -> Path:
    """Создаёт минимальный Python/Telegram бот проект."""
    (tmp_path / "requirements.txt").write_text("aiogram>=3.0\nPyYAML>=6.0")
    (tmp_path / "README.md").write_text("# My Bot\nТелеграм бот")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "import asyncio\n\nasync def main():\n    pass\n\nif __name__ == '__main__':\n    asyncio.run(main())"
    )
    (tmp_path / "src" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n\nclass Config(BaseSettings):\n    BOT_TOKEN: str"
    )
    (tmp_path / "src" / "handlers").mkdir()
    (tmp_path / "src" / "handlers" / "start.py").write_text(
        "from aiogram import Router\n\nrouter = Router()\n\n@router.message()\nasync def handle_start(message):\n    await message.answer('Привет!')"
    )
    # Файлы которые должны быть исключены
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib").mkdir()
    (tmp_path / ".venv" / "lib" / "some_package.py").write_text("# library code")
    (tmp_path / "src" / "__pycache__").mkdir()
    (tmp_path / "src" / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\x00\x01\x02")
    return tmp_path


@pytest.fixture
def rules_path() -> Path:
    """Путь к реальному rag-rules.yaml."""
    path = Path(__file__).parent.parent / "rag-rules.yaml"
    if not path.exists():
        pytest.skip("rag-rules.yaml не найден")
    return path


# ── FileFilter тесты ──────────────────────────────────────────────────────────

class TestFileFilter:

    def _make_filter(self, rules_path: Path, project_path: Path):
        from services.scanner import FileFilter, RulesLoader
        rules = RulesLoader(rules_path)
        return FileFilter(rules, project_path)

    def test_python_file_included(self, rules_path, python_project):
        ff = self._make_filter(rules_path, python_project)
        main_py = python_project / "src" / "main.py"
        include, mode, role, priority = ff.should_include(main_py)
        assert include is True
        assert role == "code"

    def test_venv_excluded(self, rules_path, python_project):
        ff = self._make_filter(rules_path, python_project)
        lib_file = python_project / ".venv" / "lib" / "some_package.py"
        include, *_ = ff.should_include(lib_file)
        assert include is False

    def test_pycache_excluded(self, rules_path, python_project):
        ff = self._make_filter(rules_path, python_project)
        pyc = python_project / "src" / "__pycache__" / "main.cpython-312.pyc"
        include, *_ = ff.should_include(pyc)
        assert include is False

    def test_readme_included_as_documentation(self, rules_path, python_project):
        ff = self._make_filter(rules_path, python_project)
        readme = python_project / "README.md"
        include, mode, role, priority = ff.should_include(readme)
        assert include is True
        assert role == "documentation"
        assert mode == "full"

    def test_requirements_txt_included(self, rules_path, python_project):
        ff = self._make_filter(rules_path, python_project)
        req = python_project / "requirements.txt"
        include, *_ = ff.should_include(req)
        assert include is True

    def test_large_file_becomes_metadata_only(self, rules_path, tmp_path):
        """Файл > 100KB → metadata_only режим."""
        from services.scanner import FileFilter, RulesLoader
        rules = RulesLoader(rules_path)
        # Правило max_file_size_bytes по умолчанию 102400
        big_file = tmp_path / "huge.py"
        big_file.write_bytes(b"x" * 200_000)
        ff = FileFilter(rules, tmp_path)
        include, mode, role, priority = ff.should_include(big_file)
        assert include is True
        assert mode == "metadata_only"


# ── ContentExtractor тесты ────────────────────────────────────────────────────

class TestContentExtractor:

    def _extractor(self):
        from services.scanner import ContentExtractor
        return ContentExtractor()

    def test_full_mode_returns_all_content(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Hello\nWorld")
        result = self._extractor().extract(f, "full")
        assert "# Hello" in result
        assert "World" in result

    def test_metadata_only_returns_size(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x" * 100)
        result = self._extractor().extract(f, "metadata_only")
        assert "test.py" in result
        assert "100b" in result

    def test_signatures_python_extracts_defs(self, tmp_path):
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello {name}"

class MyClass:
    """My class."""
    def method(self):
        pass
'''
        f = tmp_path / "test.py"
        f.write_text(code)
        result = self._extractor().extract(f, "signatures")
        assert "def hello(" in result
        assert "class MyClass(" in result
        # Тела функций не должны попасть
        assert "return f" not in result

    def test_signatures_python_handles_syntax_error(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def broken(: pass")
        # Не должен падать, должен вернуть хоть что-то
        result = self._extractor().extract(f, "signatures")
        assert isinstance(result, str)

    def test_signatures_typescript_extracts_exports(self, tmp_path):
        code = '''
export async function fetchData(url: string): Promise<Response> {
    return fetch(url)
}

export const BASE_URL = "http://api.example.com"

interface User {
    id: number
    name: string
}
'''
        f = tmp_path / "test.ts"
        f.write_text(code)
        result = self._extractor().extract(f, "signatures")
        assert "export async function" in result
        assert "export const BASE_URL" in result


# ── ProjectTypeDetector тесты ─────────────────────────────────────────────────

class TestProjectTypeDetector:

    def _detector(self, rules_path: Path):
        from services.scanner import ProjectTypeDetector, RulesLoader
        return ProjectTypeDetector(RulesLoader(rules_path))

    def test_detects_telegram_bot(self, rules_path, python_project):
        # python_project имеет aiogram в requirements.txt и src/handlers/
        detector = self._detector(rules_path)
        result = detector.detect(python_project)
        assert result == "telegram_bot"

    def test_detects_python_script(self, rules_path, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests>=2.0")
        (tmp_path / "main.py").write_text("print('hello')")
        detector = self._detector(rules_path)
        result = detector.detect(tmp_path)
        assert result == "python_script"

    def test_unknown_project(self, rules_path, tmp_path):
        (tmp_path / "something.go").write_text("package main")
        detector = self._detector(rules_path)
        result = detector.detect(tmp_path)
        assert result == "unknown"


# ── ProjectScanner интеграционные тесты ───────────────────────────────────────

class TestProjectScanner:
    """Тестирует полный pipeline сканирования с замоканным ChromaDB."""

    def _make_scanner(self, rules_path: Path, mock_chroma):
        from services.scanner import ProjectScanner
        return ProjectScanner(
            rules_path=rules_path,
            chroma_store=mock_chroma,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        )

    @pytest.mark.asyncio
    async def test_scan_yields_start_and_done(self, rules_path, python_project, mock_chroma):
        """Сканирование всегда начинается с start и заканчивается done."""
        with patch("services.scanner.ProjectScanner._index_to_chroma", new_callable=AsyncMock):
            scanner = self._make_scanner(rules_path, mock_chroma)
            events = []
            async for progress in scanner.scan(python_project):
                events.append(progress)

        types = [e.type for e in events]
        assert types[0] == "start"
        assert types[-1] == "done"

    @pytest.mark.asyncio
    async def test_scan_indexes_python_files(self, rules_path, python_project, mock_chroma):
        """Python файлы из src/ попадают в индекс."""
        with patch("services.scanner.ProjectScanner._index_to_chroma", new_callable=AsyncMock) as mock_idx:
            scanner = self._make_scanner(rules_path, mock_chroma)
            events = []
            async for progress in scanner.scan(python_project):
                events.append(progress)

        done_event = next(e for e in events if e.type == "done")
        assert done_event.files_indexed > 0

    @pytest.mark.asyncio
    async def test_scan_excludes_venv(self, rules_path, python_project, mock_chroma):
        """Файлы в .venv не индексируются."""
        indexed_paths = []

        async def capture_index(project_name, project_type, nodes):
            indexed_paths.extend(node.rel_path for node in nodes)

        with patch.object(
            __import__('services.scanner', fromlist=['ProjectScanner']).ProjectScanner,
            '_index_to_chroma',
            side_effect=capture_index
        ):
            scanner = self._make_scanner(rules_path, mock_chroma)
            async for _ in scanner.scan(python_project):
                pass

        # Ни один путь не должен содержать .venv
        venv_paths = [p for p in indexed_paths if ".venv" in p]
        assert len(venv_paths) == 0

    @pytest.mark.asyncio
    async def test_scan_nonexistent_path_yields_error(self, rules_path, mock_chroma):
        """Несуществующий путь → событие error."""
        scanner = self._make_scanner(rules_path, mock_chroma)
        events = []
        async for progress in scanner.scan(Path("/nonexistent/path/project")):
            events.append(progress)

        assert any(e.type == "error" for e in events)

    @pytest.mark.asyncio
    async def test_scan_dry_run_does_not_index(self, rules_path, python_project, mock_chroma):
        """dry_run=True не вызывает _index_to_chroma."""
        with patch("services.scanner.ProjectScanner._index_to_chroma", new_callable=AsyncMock) as mock_idx:
            scanner = self._make_scanner(rules_path, mock_chroma)
            async for _ in scanner.scan(python_project, dry_run=True):
                pass

        mock_idx.assert_not_called()
