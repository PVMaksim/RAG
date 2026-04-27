"""
config.py — централизованная конфигурация RAG Dev Assistant.
Все значения загружаются из переменных окружения / .env файла.
Никаких захардкоженных путей.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Anthropic ──────────────────────────────────────────────────────────
    ai_api_key: str = Field(..., env="AI_API_KEY")
    claude_model: str = Field("claude-sonnet-4-20250514", env="CLAUDE_MODEL")

    # ── Пути к хранилищам ─────────────────────────────────────────────────
    # Локально: ./data/chroma_db  |  Docker: /app/data/chroma_db
    chroma_db_path: Path = Field(
        default=Path("./data/chroma_db"), env="CHROMA_DB_PATH"
    )
    graph_db_path: Path = Field(
        default=Path("./data/graph.db"), env="GRAPH_DB_PATH"
    )
    # Папка, где лежат проекты для сканирования
    # Локально монтируется как volume в docker-compose.dev.yml
    projects_base_path: Path = Field(
        default=Path("./projects"), env="PROJECTS_BASE_PATH"
    )

    # ── Правила сканирования ──────────────────────────────────────────────
    rag_rules_path: Path = Field(
        default=Path(__file__).parent.parent / "rag-rules.yaml",
        env="RAG_RULES_PATH",
    )

    # ── Модели эмбеддингов ────────────────────────────────────────────────
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL"
    )
    default_top_k: int = Field(5, env="DEFAULT_TOP_K")

    # ── MCP сервер ────────────────────────────────────────────────────────
    mcp_server_port: int = Field(27183, env="MCP_SERVER_PORT")
    # ── Webhook ──────────────────────────────────────────────────────────────────
    # HMAC-SHA256 секрет для верификации GitHub Webhook запросов
    # Генерируй: openssl rand -hex 32
    # Задай тот же секрет в GitHub → Settings → Webhooks → Secret
    webhook_secret: str | None = Field(None, env="WEBHOOK_SECRET")

    # ── MCP API ключ — если задан, MCP сервер требует его в заголовке
    # Authorization: Bearer <mcp_api_key>
    # Пустой = аутентификация отключена (только для локального режима)
    mcp_api_key: str | None = Field(None, env="MCP_API_KEY")

    # ── Telegram уведомления (стандарт PVMaksim) ──────────────────────────
    telegram_bot_token: str | None = Field(None, env="TELEGRAM_BOT_TOKEN")
    admin_telegram_id: int | None = Field(None, env="ADMIN_TELEGRAM_ID")

    # ── Сервер ────────────────────────────────────────────────────────────
    backend_port: int = Field(8000, env="BACKEND_PORT")
    debug: bool = Field(False, env="DEBUG")

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Список допустимых origins через запятую
    # Dev: "http://localhost:3000,http://localhost:8080"
    # Prod: "https://rag.yourdomain.com"
    cors_origins: str = Field(
        "http://localhost:3000,http://localhost:8080,http://frontend:3000",
        env="CORS_ORIGINS",
    )

    # ── Phase 2: Auth (пока отключена) ───────────────────────────────────
    auth_enabled: bool = Field(False, env="AUTH_ENABLED")
    # app_secret_key: str | None = None

    # ── Валидаторы ────────────────────────────────────────────────────────────

    @field_validator("ai_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """API ключ должен начинаться с sk-ant- (формат Anthropic)."""
        if not v:
            raise ValueError("AI_API_KEY не задан")
        if not v.startswith(("sk-ant-", "sk-")):
            raise ValueError(
                "ANTHROPIC_API_KEY имеет неверный формат. "
                "Ожидается ключ начинающийся с 'sk-ant-'. "
                "Получи ключ на console.anthropic.com"
            )
        return v

    @field_validator("default_top_k")
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("DEFAULT_TOP_K должен быть от 1 до 20")
        return v

    @model_validator(mode="after")
    def validate_paths_exist(self) -> "Settings":
        """Предупреждаем если rag-rules.yaml не найден — не падаем."""
        import logging
        if not self.rag_rules_path.exists():
            logging.getLogger(__name__).warning(
                f"rag-rules.yaml не найден: {self.rag_rules_path}. "
                "Сканирование будет недоступно."
            )
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    def ensure_paths(self) -> None:
        """Создать все необходимые директории при старте."""
        self.chroma_db_path.mkdir(parents=True, exist_ok=True)
        self.graph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.projects_base_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Синглтон настроек — загружается один раз при старте приложения."""
    settings = Settings()
    settings.ensure_paths()
    return settings
