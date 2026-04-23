# CLAUDE.md — RAG Dev Assistant

## Стек

| Слой | Технология | Версия |
|------|-----------|--------|
| Backend | Python + FastAPI + uvicorn | 3.12 / 0.115+ |
| Frontend | TypeScript + Next.js App Router | 5 / 14.2.5 |
| macOS клиент | Swift + SwiftUI + WKWebView | 5.9 / macOS 13+ |
| MCP сервер | Python + MCP SDK + Starlette | 1.0+ |
| Vector DB | ChromaDB (локальная, без сервера) | 0.5+ |
| Graph DB | SQLite (WAL mode) | встроен |
| Эмбеддинги | sentence-transformers/all-MiniLM-L6-v2 | 3.0+ (офлайн) |
| LLM | Anthropic Claude | claude-sonnet-4-20250514 |
| Инфраструктура | Docker Compose + nginx + GitHub Actions | — |

## Архитектура — три слоя

```
macOS App (SwiftUI + WKWebView)
    ↓ открывает
Docker Compose [localhost:8080 / https://rag.domain.com]
    ├── nginx          — reverse proxy, SSL termination
    ├── frontend       — Next.js, порт 3000
    ├── backend        — FastAPI, порт 8000
    └── mcp-server     — MCP HTTP transport, порт 27183
         ↕
    ChromaDB (volume)  — эмбеддинги и чанки
    SQLite (volume)    — Knowledge Graph (nodes/edges/communities)
```

## Структура backend/src/

```
config.py            — Pydantic Settings, все из .env, валидация API ключа
main.py              — FastAPI app, middleware, exception handlers
exceptions.py        — иерархия RAGError (ProjectNotFoundError, LLMError, etc.)
logging_config.py    — JSONFormatter (prod) + цветной (dev), @timed декоратор
retry.py             — @with_anthropic_retry() — exponential backoff для Claude API
embedding_cache.py   — LRU кэш эмбеддингов (maxsize=512), cache_stats()
dependencies.py      — FastAPI Depends синглтоны (lru_cache)
schemas.py           — Pydantic модели запросов/ответов

middleware/
  error_handler.py   — RequestContextMiddleware (request_id), safe_sse_stream()

routers/
  search.py          — POST /search, /answer, /patch, /global (SSE)
  projects.py        — CRUD проектов + /scan, /graph/build (SSE)
  graph.py           — GET /graph/{project}, /summaries

services/
  scanner.py         — ProjectScanner: scan() → AsyncGenerator[ScanProgress]
                       asyncio.Lock на проект (защита от параллельных сканирований)
  query_engine.py    — QueryEngine: answer_stream(), patch_stream(), global_answer_stream()
  graphrag.py        — GraphRAGEngine: build_graph() с Semaphore(3) + батчинг по 5 файлов
  notifier.py        — Telegram алерты об ошибках (стандарт PVMaksim)

storage/
  chroma_store.py    — ChromaDB обёртка: search(), list_projects(), search_summaries()
  graph_store.py     — SQLite WAL: nodes, edges, communities (busy_timeout=30s)
```

## Структура frontend/src/

```
app/
  search/page.tsx    — поиск + SSE стриминг через useSSE хук
  projects/page.tsx  — управление проектами + прогресс сканирования
  graph/page.tsx     — react-force-graph-2d визуализация Knowledge Graph
  settings/page.tsx  — URL бэкенда, MCP инструкции
  layout.tsx         — Sidebar + ErrorBoundary

components/
  Sidebar/           — навигация + статус бэкенда
  ErrorBoundary.tsx  — React error boundary на уровне страниц

hooks/
  useSSE.ts          — SSE стриминг с AbortController, cleanup, error handling
  useProjects.ts     — проекты: загрузка, удаление (оптимистично), estimates

lib/
  api.ts             — HTTP клиент ко всем FastAPI эндпоинтам
```

## MCP Server (mcp-server/src/server.py)

4 инструмента, HTTP transport на :27183/mcp/sse:
- `search_project(query, project?, top_k?)` — семантический поиск
- `list_projects()` — список проиндексированных проектов
- `get_graph_summary(project?)` — архитектурное резюме из community summaries
- `get_file_content(project, file_path)` — содержимое конкретного файла

## macOS App (mac-app/)

```
RAGAssistantApp.swift  — @main, MenuBarExtra
AppDelegate.swift      — запуск docker compose, polling /health
AppState.swift         — ObservableObject, health polling каждые 15с
MenuBarView.swift      — WKWebView → Next.js UI, JavaScript bridge
SettingsView.swift     — нативное окно настроек (Form)
HotkeyService.swift    — Carbon RegisterEventHotKey (⌥Space)
KeychainService.swift  — ANTHROPIC_API_KEY в macOS Keychain
NotificationBridge.swift — JS → UNUserNotification
```

## Правила написания кода

- Все функции — docstrings на английском
- Бизнес-логика — комментарии на русском
- Пути — только через `get_settings()`, никаких захардкоженных строк
- Исключения — кидать конкретные классы из `exceptions.py`, не голый `Exception`
- SSE — всегда оборачивать в `safe_sse_stream()` из `middleware/error_handler.py`
- Логи — через `logging.getLogger(__name__)`, extra-поля для структуры
- Параллелизм — `asyncio.Lock` для защиты состояния, `Semaphore` для rate limits
- Тесты — мокировать ChromaDB и Anthropic, не делать реальных вызовов

## Инструкции для ИИ (совместимость с Serena MCP / RAG)

- Держать код модульным: один файл = одна ответственность
- Имена функций и переменных — английский, описательные
- Документировать все публичные интерфейсы
- Перед добавлением нового эндпоинта — добавить исключение в `exceptions.py`
- Перед добавлением нового сервиса — добавить синглтон в `dependencies.py`
- SSE события: поле `type` обязательно, формат `data: {...}\n\n`
- GraphRAG: entity extraction батчами через `asyncio.gather` + `Semaphore(3)`
- Embedding кэш: использовать `embedding_cache.get_embedding()`, не модель напрямую
