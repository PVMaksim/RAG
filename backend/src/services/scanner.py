"""
scanner.py — сервис индексирования проектов.
Рефакторинг scan.py: класс ProjectScanner с dependency injection.
"""
import asyncio
import hashlib
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from sentence_transformers import SentenceTransformer

from logging_config import timed
from storage.chroma_store import ChromaStore

log = logging.getLogger(__name__)

ContentMode = Literal["full", "signatures", "metadata_only"]

# ─── Модели данных ─────────────────────────────────────────────────────────────

@dataclass
class FileNode:
    project_name: str
    rel_path: str
    abs_path: str
    graph_role: str
    content_mode: ContentMode
    priority: str
    content: str
    file_hash: str
    size_bytes: int

@dataclass
class ScanProgress:
    """Событие прогресса для SSE стриминга."""
    type: str           # start | progress | done | error
    files_scanned: int = 0
    files_indexed: int = 0
    files_total: int = 0
    current_file: str = ""
    project: str = ""
    duration_sec: float = 0.0
    error: str = ""

@dataclass
class ScanResult:
    project_name: str
    project_type: str
    files_scanned: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    nodes: list[FileNode] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ─── Загрузка правил ──────────────────────────────────────────────────────────

class RulesLoader:
    def __init__(self, rules_path: Path) -> None:
        with open(rules_path, encoding="utf-8") as f:
            self.rules: dict = yaml.safe_load(f)

    def merge_project_overrides(self, project_path: Path) -> None:
        override_file = self.rules.get("per_project_override_file", ".rag-project.yaml")
        override_path = project_path / override_file
        if not override_path.exists():
            return
        with open(override_path, encoding="utf-8") as f:
            overrides: dict = yaml.safe_load(f) or {}
        ov = overrides.get("overrides", {})
        if "extra_exclude" in ov:
            self.rules["global"]["always_exclude"].extend(ov["extra_exclude"])
        log.info(f"Применены переопределения из {override_file}")

    @property
    def global_rules(self) -> dict: return self.rules.get("global", {})
    @property
    def file_type_rules(self) -> list[dict]: return self.rules.get("file_types", [])
    @property
    def path_rules(self) -> list[dict]: return self.rules.get("path_rules", [])
    @property
    def project_type_detection(self) -> list[dict]: return self.rules.get("project_type_detection", [])


# ─── Фильтрация файлов ────────────────────────────────────────────────────────

class FileFilter:
    def __init__(self, rules: RulesLoader, project_path: Path) -> None:
        self.rules = rules
        self.project_path = project_path
        self._gitignore = self._load_gitignore(project_path)
        self._always_exclude = self.rules.global_rules.get("always_exclude", [])
        self._max_size = self.rules.global_rules.get("max_file_size_bytes", 102400)

    def _load_gitignore(self, path: Path):
        try:
            from gitignore_parser import parse_gitignore
            gi = path / ".gitignore"
            return parse_gitignore(gi) if gi.exists() else lambda _: False
        except ImportError:
            return lambda _: False

    def should_include(self, abs_path: Path) -> tuple[bool, ContentMode, str, str]:
        rel = str(abs_path.relative_to(self.project_path))
        if self.rules.global_rules.get("respect_gitignore") and self._gitignore(str(abs_path)):
            return False, "metadata_only", "unknown", "skip"
        if self._matches_any_glob(rel, self._always_exclude):
            return False, "metadata_only", "unknown", "skip"
        too_large = abs_path.stat().st_size > self._max_size
        ai_files = self.rules.global_rules.get("ai_context_files", [])
        if abs_path.name in ai_files or rel in ai_files:
            mode: ContentMode = "metadata_only" if too_large else "full"
            return True, mode, "documentation", "critical"
        for prule in self.rules.path_rules:
            if self._matches_glob(rel, prule["pattern"]):
                if prule["action"] == "exclude":
                    return False, "metadata_only", "unknown", "skip"
                if prule["action"] == "include":
                    mode = prule.get("content_mode", "signatures")
                    if too_large: mode = "metadata_only"
                    return True, mode, "file", prule.get("priority", "medium")
        result = self._check_file_type(abs_path, rel, too_large)
        if result is not None:
            return result
        return False, "metadata_only", "unknown", "skip"

    def _check_file_type(self, abs_path: Path, rel_str: str, too_large: bool):
        from fnmatch import fnmatch
        name, ext = abs_path.name, abs_path.suffix.lower()
        for rule in self.rules.file_type_rules:
            matched = (ext in rule.get("extensions", [])) or any(
                fnmatch(name, p) for p in rule.get("filenames", [])
            )
            if not matched: continue
            if not rule.get("include", True):
                return False, "metadata_only", "unknown", "skip"
            if self._matches_any_glob(rel_str, rule.get("exclude_patterns", [])):
                return False, "metadata_only", "unknown", "skip"
            if "include_only_filenames" in rule and name not in rule["include_only_filenames"]:
                return False, "metadata_only", "unknown", "skip"
            mode: ContentMode = rule.get("content_mode", "signatures")
            max_sz = rule.get("max_size_override_bytes", self._max_size)
            if abs_path.stat().st_size > max_sz or too_large:
                mode = "metadata_only"
            return True, mode, rule.get("graph_role", "file"), rule.get("priority", "medium")
        return None

    @staticmethod
    def _matches_glob(path_str: str, pattern: str) -> bool:
        from fnmatch import fnmatch
        return fnmatch(path_str, pattern) or fnmatch(Path(path_str).name, pattern)

    @staticmethod
    def _matches_any_glob(path_str: str, patterns: list[str]) -> bool:
        from fnmatch import fnmatch
        return any(
            fnmatch(path_str, p) or fnmatch(Path(path_str).name, p)
            for p in patterns
        )


# ─── Извлечение содержимого ───────────────────────────────────────────────────

class ContentExtractor:
    def extract(self, path: Path, mode: ContentMode) -> str:
        if mode == "metadata_only":
            return f"[FILE] {path.name} | size={path.stat().st_size}b"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[READ ERROR] {e}"
        if mode == "full":
            return text
        ext = path.suffix.lower()
        if ext == ".py":
            return self._python_signatures(text)
        if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
            return self._js_signatures(text)
        return text

    def _python_signatures(self, source: str) -> str:
        import ast, re as _re
        lines = []
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                    args = ", ".join(a.arg for a in node.args.args)
                    lines.append(f"{prefix}def {node.name}({args}):")
                    doc = ast.get_docstring(node)
                    if doc: lines.append(f'    """{doc[:200]}"""')
                elif isinstance(node, ast.ClassDef):
                    bases = [getattr(b, "id", "?") for b in node.bases]
                    lines.append(f"class {node.name}({', '.join(bases)}):")
                    doc = ast.get_docstring(node)
                    if doc: lines.append(f'    """{doc[:200]}"""')
        except SyntaxError:
            for line in source.splitlines():
                if line.strip().startswith(("def ", "async def ", "class ")):
                    lines.append(line)
        return "\n".join(lines)

    def _js_signatures(self, source: str) -> str:
        import re
        patterns = [
            r"^export\s+(default\s+)?(async\s+)?function\s+\w+[^{]*",
            r"^export\s+(const|let|var)\s+\w+\s*[=:]",
            r"^(const|let|var)\s+\w+\s*=\s*(async\s+)?\(.*\)\s*=>",
            r"^\s*(public|private|protected|static)?\s*(async\s+)?\w+\s*\(.*\)\s*[:{]",
            r"^interface\s+\w+",
            r"^type\s+\w+\s*=",
            r"^class\s+\w+",
        ]
        lines = []
        for line in source.splitlines():
            for p in patterns:
                if re.match(p, line.strip()):
                    lines.append(line.rstrip())
                    break
        return "\n".join(lines)


# ─── Определение типа проекта ─────────────────────────────────────────────────

class ProjectTypeDetector:
    def __init__(self, rules: RulesLoader) -> None:
        self.rules = rules

    def detect(self, project_path: Path) -> str:
        req_text = self._read_deps(project_path)
        for rule in self.rules.project_type_detection:
            if self._check(project_path, rule.get("markers", {}), req_text):
                return rule.get("type", "unknown")
        return "unknown"

    def _check(self, path: Path, markers: dict, req_text: str) -> bool:
        if "files_exist" in markers:
            if not all((path / f).exists() for f in markers["files_exist"]): return False
        if "files_exist_any" in markers:
            if not any((path / f).exists() for f in markers["files_exist_any"]): return False
        if "files_not_exist" in markers:
            if any((path / f).exists() for f in markers["files_not_exist"]): return False
        if "requirements_contain_any" in markers:
            if not any(lib in req_text for lib in markers["requirements_contain_any"]): return False
        return True

    def _read_deps(self, path: Path) -> str:
        texts = []
        for fname in ("requirements.txt", "pyproject.toml", "package.json"):
            p = path / fname
            if p.exists():
                try: texts.append(p.read_text(encoding="utf-8", errors="replace").lower())
                except Exception: pass
        return " ".join(texts)


# ─── Основной сканер ──────────────────────────────────────────────────────────

class ProjectScanner:
    """
    Сканирует проект, извлекает содержимое файлов,
    создаёт эмбеддинги и индексирует в ChromaDB.
    Генерирует ScanProgress события для SSE стриминга.
    """

    def __init__(
        self,
        rules_path: Path,
        chroma_store: ChromaStore,
        embedding_model: str,
    ) -> None:
        self._rules_path = rules_path
        self._chroma = chroma_store
        self._extractor = ContentExtractor()
        self._embedding_model_name = embedding_model
        self._model: SentenceTransformer | None = None
        # Отслеживаем активные сканирования: project_name → asyncio.Lock
        # Предотвращает параллельное сканирование одного проекта
        self._active_scans: dict[str, asyncio.Lock] = {}

    def _get_model(self) -> SentenceTransformer:
        """Ленивая загрузка модели эмбеддингов."""
        if self._model is None:
            log.info(f"Загружаю модель: {self._embedding_model_name}")
            self._model = SentenceTransformer(self._embedding_model_name)
        return self._model

    async def scan(
        self, project_path: Path, dry_run: bool = False
    ) -> AsyncGenerator[ScanProgress, None]:
        """
        Асинхронный генератор: выдаёт ScanProgress события.
        Используется для SSE стриминга прогресса в FastAPI.
        """
        import time
        start = time.time()

        project_path = project_path.resolve()
        if not project_path.exists():
            yield ScanProgress(type="error", error=f"Путь не найден: {project_path}")
            return

        project_name = project_path.name

        # Защита от параллельного сканирования одного проекта
        if project_name not in self._active_scans:
            self._active_scans[project_name] = asyncio.Lock()

        if self._active_scans[project_name].locked():
            yield ScanProgress(
                type="error",
                project=project_name,
                error=f"Проект '{project_name}' уже сканируется. Дождись завершения.",
            )
            return

        async with self._active_scans[project_name]:
        rules = RulesLoader(self._rules_path)
        rules.merge_project_overrides(project_path)

        file_filter = FileFilter(rules, project_path)
        type_detector = ProjectTypeDetector(rules)
        project_type = type_detector.detect(project_path)

        # Подсчёт общего числа файлов для прогресс-бара
        all_files = [f for f in project_path.rglob("*") if f.is_file()]
        total = len(all_files)

        log.info(
            "Сканирование начато",
            extra={"project": project_name, "total_files": total, "type": project_type},
        )
        yield ScanProgress(
            type="start",
            project=project_name,
            files_total=total,
        )

        nodes: list[FileNode] = []
        scanned = indexed = skipped = 0

        for abs_path in sorted(all_files):
            scanned += 1
            try:
                include, mode, role, priority = file_filter.should_include(abs_path)
            except Exception as e:
                skipped += 1
                log.warning(
                    "Ошибка фильтрации файла",
                    extra={"file": str(abs_path)},
                    exc_info=True,
                )
                continue

            if not include:
                skipped += 1
                continue

            try:
                content = self._extractor.extract(abs_path, mode)
                file_hash = hashlib.md5(abs_path.read_bytes()).hexdigest()
                nodes.append(FileNode(
                    project_name=project_name,
                    rel_path=str(abs_path.relative_to(project_path)),
                    abs_path=str(abs_path),
                    graph_role=role,
                    content_mode=mode,
                    priority=priority,
                    content=content or "[EMPTY]",
                    file_hash=file_hash,
                    size_bytes=abs_path.stat().st_size,
                ))
                indexed += 1

                # Отдаём прогресс каждые 10 файлов (не спамим SSE)
                if scanned % 10 == 0 or scanned == total:
                    yield ScanProgress(
                        type="progress",
                        project=project_name,
                        files_scanned=scanned,
                        files_indexed=indexed,
                        files_total=total,
                        current_file=str(abs_path.relative_to(project_path)),
                    )
                    await asyncio.sleep(0)  # уступаем event loop

            except Exception as e:
                skipped += 1
                log.warning(
                    "Ошибка обработки файла",
                    extra={"file": str(abs_path), "error": str(e)},
                    exc_info=True,
                )

        # Индексация в ChromaDB
        if not dry_run and nodes:
            await self._index_to_chroma(project_name, project_type, nodes)

        duration = round(time.time() - start, 2)
        yield ScanProgress(
            type="done",
            project=project_name,
            files_scanned=scanned,
            files_indexed=indexed,
            files_total=total,
            duration_sec=duration,
        )
        log.info(
            f"Сканирование {project_name}: "
            f"{scanned} просканировано, {indexed} проиндексировано, "
            f"{skipped} пропущено за {duration}с"
        )

    @timed("chroma_indexing")
    async def _index_to_chroma(
        self,
        project_name: str,
        project_type: str,
        nodes: list[FileNode],
    ) -> None:
        """Загружает узлы в ChromaDB с инкрементальным обновлением."""
        collection = self._chroma.get_or_create_project(project_name, project_type)
        existing_hashes = self._chroma.get_existing_hashes(collection)
        model = self._get_model()

        ids, docs, embeds, metas = [], [], [], []
        updated = skipped = 0

        for node in nodes:
            if existing_hashes.get(node.rel_path) == node.file_hash:
                skipped += 1
                continue

            doc_id = self._chroma.make_doc_id(project_name, node.rel_path)
            # Эмбеддинг в thread pool чтобы не блокировать event loop
            embedding = await asyncio.get_event_loop().run_in_executor(
                None, lambda c=node.content: model.encode(c).tolist()
            )

            ids.append(doc_id)
            docs.append(node.content)
            embeds.append(embedding)
            metas.append({
                "project": project_name,
                "project_type": project_type,
                "rel_path": node.rel_path,
                "graph_role": node.graph_role,
                "priority": node.priority,
                "content_mode": node.content_mode,
                "file_hash": node.file_hash,
                "size_bytes": node.size_bytes,
            })
            updated += 1

        if ids:
            collection.upsert(ids=ids, documents=docs, embeddings=embeds, metadatas=metas)

        log.info(f"Chroma [{project_name}]: +{updated} обновлено, {skipped} без изменений")
