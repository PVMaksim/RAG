"""
exceptions.py — иерархия исключений RAG Dev Assistant.

Все бизнес-ошибки — конкретные типы, а не голый Exception.
Это позволяет:
  - Различать ожидаемые ошибки (проект не найден) от неожиданных (упал ChromaDB)
  - Маппить исключения на HTTP статусы в одном месте
  - Логировать с правильным уровнем (warning vs error vs critical)
"""


# ── Базовый класс ─────────────────────────────────────────────────────────────

class RAGError(Exception):
    """Базовый класс всех бизнес-ошибок приложения."""
    http_status: int = 500
    log_level: str = "error"   # debug | info | warning | error | critical

    def __init__(self, message: str, **context):
        super().__init__(message)
        self.message = message
        self.context = context  # Дополнительные поля для структурированных логов

    def __str__(self) -> str:
        if self.context:
            ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} ({ctx})"
        return self.message


# ── Проекты ───────────────────────────────────────────────────────────────────

class ProjectNotFoundError(RAGError):
    """Проект не найден в ChromaDB индексе."""
    http_status = 404
    log_level = "warning"

    def __init__(self, project_name: str):
        super().__init__(f"Проект не найден: {project_name}", project=project_name)


class ProjectPathNotFoundError(RAGError):
    """Путь к проекту не существует на диске."""
    http_status = 404
    log_level = "warning"

    def __init__(self, path: str):
        super().__init__(f"Путь не найден: {path}", path=path)


class ProjectAlreadyScanningError(RAGError):
    """Проект уже сканируется в данный момент."""
    http_status = 409
    log_level = "warning"

    def __init__(self, project_name: str):
        super().__init__(f"Проект уже сканируется: {project_name}", project=project_name)


# ── Поиск ─────────────────────────────────────────────────────────────────────

class EmptyIndexError(RAGError):
    """Индекс пустой — нет проиндексированных проектов."""
    http_status = 404
    log_level = "warning"

    def __init__(self, project: str | None = None):
        ctx = f" в проекте '{project}'" if project else ""
        super().__init__(f"Ничего не найдено{ctx}. Проверь что проект проиндексирован.", project=project)


class GraphNotBuiltError(RAGError):
    """Knowledge Graph не построен для данного проекта."""
    http_status = 404
    log_level = "warning"

    def __init__(self, project: str | None = None):
        ctx = f" для '{project}'" if project else ""
        super().__init__(
            f"Knowledge Graph не построен{ctx}. "
            "Перейди в Проекты → Построить граф знаний.",
            project=project,
        )


# ── LLM / Anthropic ───────────────────────────────────────────────────────────

class LLMError(RAGError):
    """Ошибка при обращении к LLM API."""
    http_status = 502
    log_level = "error"


class LLMRateLimitError(LLMError):
    """Rate limit от Anthropic API."""
    http_status = 429
    log_level = "warning"

    def __init__(self, retry_after: int | None = None):
        super().__init__(
            "Превышен лимит запросов к Anthropic API. Попробуй позже.",
            retry_after=retry_after,
        )
        self.retry_after = retry_after


class LLMResponseParseError(LLMError):
    """Не удалось распарсить ответ LLM (ожидался JSON)."""
    log_level = "warning"

    def __init__(self, raw_response: str, parse_error: str):
        super().__init__(
            f"LLM вернул невалидный JSON: {parse_error}",
            raw_preview=raw_response[:200],
        )
        self.raw_response = raw_response


# ── ChromaDB / Storage ────────────────────────────────────────────────────────

class StorageError(RAGError):
    """Ошибка хранилища (ChromaDB или SQLite)."""
    http_status = 503
    log_level = "critical"


class ChromaUnavailableError(StorageError):
    """ChromaDB недоступна."""
    def __init__(self, detail: str = ""):
        super().__init__(f"ChromaDB недоступна: {detail}")


# ── Сканирование ──────────────────────────────────────────────────────────────

class ScanError(RAGError):
    """Ошибка при сканировании файла."""
    log_level = "warning"

    def __init__(self, file_path: str, reason: str):
        super().__init__(f"Ошибка сканирования {file_path}: {reason}", file=file_path)


class RulesFileError(RAGError):
    """Ошибка загрузки rag-rules.yaml."""
    http_status = 500
    log_level = "critical"

    def __init__(self, path: str, reason: str):
        super().__init__(f"Не удалось загрузить правила {path}: {reason}", path=path)
