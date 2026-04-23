# Техническое задание: RAG Dev Assistant
## Версия 3.0 — Продуктовая архитектура

| Поле | Значение |
|------|----------|
| **Название** | RAG Dev Assistant |
| **Версия документа** | 3.0 |
| **Дата** | 2026-04-12 |
| **Автор** | PVMaksim |
| **Статус** | Утверждён |
| **Репозиторий** | `PVMaksim/rag-dev-assistant` |
| **Папка на VPS** | `/home/deploy/rag-dev-assistant` |
| **SSH ключ deploy** | `github-actions-key` |

---

## 1. Цель и видение продукта

### Фаза 1 — Личный инструмент (текущая цель)
Docker-приложение, работающее локально на Mac. macOS SwiftUI-клиент в menu bar для быстрого поиска по своим IT-проектам + MCP-сервер для любых AI-ассистентов.

### Фаза 2 — Деплой на VPS
Тот же Docker Compose переезжает на сервер. Веб-интерфейс доступен с любого устройства. Появляется аутентификация.

### Фаза 3 — Продукт (Win/Linux/Mac)
Мульти-пользовательский SaaS. Нативные клиенты для всех ОС. Биллинг.

**Ключевая идея:** один Docker Compose файл работает и локально, и на VPS — меняется только `.env`. Никакого переписывания кода между фазами.

---

## 2. Архитектура — почему именно так

### Центральный принцип: Web UI как основа всех клиентов

```
┌─────────────────────────────────────────────────────────────────┐
│                         КЛИЕНТЫ                                 │
│                                                                  │
│  macOS SwiftUI App          Windows / Linux         Любой AI    │
│  ┌─────────────────┐        ┌──────────────┐   ┌─────────────┐ │
│  │ Menu Bar Icon   │        │              │   │ Claude Desk │ │
│  │ Global Hotkey   │        │   Browser    │   │ Cursor      │ │
│  │ ┌─────────────┐ │        │   ┌────────┐ │   │ Windsurf    │ │
│  │ │  WKWebView  │ │        │   │Web UI  │ │   │ Any MCP     │ │
│  │ │  (Web UI)   │ │        │   └────────┘ │   └─────────────┘ │
│  │ └─────────────┘ │        └──────┬───────┘         │         │
│  └────────┬────────┘               │                 │         │
└───────────┼───────────────────────┼─────────────────┼─────────┘
            │        HTTPS          │      MCP Proto  │
┌───────────▼───────────────────────▼─────────────────▼─────────┐
│                  DOCKER COMPOSE                                  │
│  ┌───────────┐  ┌────────────┐  ┌──────────┐  ┌───────────┐  │
│  │  nginx    │  │  frontend  │  │ backend  │  │ mcp-server│  │
│  │ :80/:443  │  │  Next.js   │  │ FastAPI  │  │  :27183   │  │
│  │  reverse  │  │  :3000     │  │  :8000   │  │           │  │
│  │  proxy    │  └────────────┘  └─────┬────┘  └───────────┘  │
│  └───────────┘                        │                        │
│                          ┌────────────┴──────────┐            │
│                    ┌─────▼──────┐  ┌─────────────▼──┐        │
│                    │  ChromaDB  │  │  SQLite Graph  │        │
│                    │  (volume)  │  │  (volume)      │        │
│                    └────────────┘  └────────────────┘        │
└────────────────────────────────────────────────────────────────┘
         │ локально                    │ VPS
         │ localhost:80                │ https://rag.yourdomain.com
```

**Почему WKWebView в SwiftUI вместо нативного Swift UI:**
- Web UI уже написан один раз (Next.js) — на нём работают и Mac, и Win, и Linux
- SwiftUI-обёртка тонкая: даёт menu bar, глобальный хоткей, нативные уведомления, Keychain
- Windows/Linux — просто браузер, никаких нативных клиентов в Phase 3 не нужно
- Экономит 2–3 недели разработки

**Почему не Electron вместо SwiftUI:**
- 150MB overhead против 2MB SwiftUI wrapper
- Нет нативного menu bar, нет Keychain, нет глобального хоткея на уровне ОС

---

## 3. Структура проекта (финальная)

```
rag-dev-assistant/
│
├── .github/
│   └── workflows/
│       ├── deploy.yml          # Push в main → деплой на VPS
│       └── release-mac.yml     # Тег v* → собрать .dmg → GitHub Release
│
├── docker/
│   ├── backend/
│   │   └── Dockerfile          # Python 3.12 + FastAPI
│   ├── frontend/
│   │   └── Dockerfile          # Node.js 20 + Next.js build
│   └── nginx/
│       ├── nginx.conf          # Reverse proxy + SSL termination
│       └── nginx.dev.conf      # Конфиг для локальной разработки
│
├── backend/                    # Python FastAPI сервис
│   ├── src/
│   │   ├── main.py             # FastAPI app, подключение роутеров
│   │   ├── config.py           # Pydantic Settings из .env
│   │   ├── routers/
│   │   │   ├── search.py       # POST /search, /answer, /patch (SSE)
│   │   │   ├── projects.py     # CRUD проектов + POST /scan (SSE прогресс)
│   │   │   ├── graph.py        # GET /graph/{project}, POST /graph/build
│   │   │   └── health.py       # GET /health
│   │   ├── services/
│   │   │   ├── scanner.py      # Рефакторинг scan.py → класс
│   │   │   ├── query_engine.py # Рефакторинг query.py → класс
│   │   │   ├── graphrag.py     # GraphRAG pipeline (новый)
│   │   │   └── notifier.py     # Telegram уведомления об ошибках
│   │   ├── storage/
│   │   │   ├── chroma_store.py # ChromaDB клиент
│   │   │   └── graph_store.py  # SQLite: nodes, edges, communities
│   │   └── middleware/
│   │       └── error_handler.py
│   ├── tests/
│   ├── rag-rules.yaml          # Правила сканирования (из текущего проекта)
│   └── requirements.txt
│
├── frontend/                   # Next.js веб-приложение
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx        # Главная → редирект на /search
│   │   │   ├── search/
│   │   │   │   └── page.tsx    # 🔍 Поиск
│   │   │   ├── projects/
│   │   │   │   └── page.tsx    # 📁 Управление проектами
│   │   │   ├── graph/
│   │   │   │   └── page.tsx    # 🕸 Граф знаний
│   │   │   └── settings/
│   │   │       └── page.tsx    # ⚙ Настройки
│   │   ├── components/
│   │   │   ├── SearchPanel/    # Поле поиска + переключатели режима
│   │   │   ├── ResultsPanel/   # Ответ LLM + источники
│   │   │   ├── GraphViewer/    # Интерактивный граф (D3.js / react-force-graph)
│   │   │   ├── ProjectsList/   # Список проектов + прогресс сканирования
│   │   │   └── Sidebar/        # Навигация
│   │   ├── hooks/
│   │   │   ├── useSearch.ts    # Поиск + SSE стриминг
│   │   │   └── useProjects.ts
│   │   └── lib/
│   │       └── api.ts          # HTTP клиент к FastAPI
│   ├── package.json
│   └── tsconfig.json
│
├── mcp-server/                 # MCP сервер (отдельный процесс)
│   ├── src/
│   │   └── server.py           # MCP tools поверх RAG API
│   └── requirements.txt
│
├── mac-app/                    # SwiftUI macOS клиент (Xcode проект)
│   ├── RAGAssistant/
│   │   ├── App/
│   │   │   └── RAGAssistantApp.swift
│   │   ├── Views/
│   │   │   ├── MenuBarView.swift    # Иконка + popup
│   │   │   └── WebContentView.swift # WKWebView → Web UI
│   │   └── Services/
│   │       ├── HotkeyService.swift
│   │       ├── KeychainService.swift
│   │       └── NotificationBridge.swift
│   └── RAGAssistant.xcodeproj
│
├── scripts/
│   ├── backup.sh               # Бэкап ChromaDB + SQLite → облако
│   ├── health_check.sh         # Проверка всех сервисов
│   └── init_ssl.sh             # Первичная выдача Let's Encrypt
│
├── docs/
│   └── mcp-setup.md            # Инструкция: подключить MCP к Claude Desktop/Cursor
│
├── .env.example                # Все переменные с описанием
├── .env                        # Реальные значения (в .gitignore)
├── docker-compose.yml          # Production + VPS
├── docker-compose.dev.yml      # Локальная разработка (override)
├── CLAUDE.md
├── MEMORY.md
└── README.md
```

---

## 4. Docker Compose — полная конфигурация

### docker-compose.yml (production / VPS)
```yaml
version: '3.9'

services:
  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf
      - certbot_data:/etc/letsencrypt
      - certbot_www:/var/www/certbot
    depends_on: [frontend, backend]
    logging:
      driver: "json-file"
      options: { max-size: "10m", max-file: "3" }

  frontend:
    build: ./docker/frontend
    restart: unless-stopped
    environment:
      - NEXT_PUBLIC_API_URL=/api    # через nginx
    logging:
      driver: "json-file"
      options: { max-size: "10m", max-file: "3" }

  backend:
    build: ./docker/backend
    restart: unless-stopped
    env_file: .env
    volumes:
      - chroma_data:/app/data/chroma_db
      - graph_data:/app/data/graph.db
      - projects_data:/app/projects   # проекты для сканирования
    logging:
      driver: "json-file"
      options: { max-size: "10m", max-file: "3" }

  mcp-server:
    build: ./docker/mcp
    restart: unless-stopped
    env_file: .env
    ports:
      - "27183:27183"   # MCP HTTP transport
    depends_on: [backend]
    logging:
      driver: "json-file"
      options: { max-size: "10m", max-file: "3" }

volumes:
  chroma_data:      # ChromaDB — эмбеддинги и чанки
  graph_data:       # SQLite — Knowledge Graph
  projects_data:    # Файлы проектов для сканирования (Phase 2+)
  certbot_data:
  certbot_www:
```

### docker-compose.dev.yml (локальная разработка на Mac)
```yaml
version: '3.9'

# docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

services:
  nginx:
    ports:
      - "8080:80"   # локально на порту 8080

  frontend:
    build:
      context: .
      dockerfile: ./docker/frontend/Dockerfile.dev
    volumes:
      - ./frontend:/app          # hot reload
      - /app/node_modules
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8080/api

  backend:
    build:
      context: .
      dockerfile: ./docker/backend/Dockerfile.dev
    volumes:
      - ./backend/src:/app/src   # hot reload
      - ~/Documents/Projects:/app/projects  # твои локальные проекты
    environment:
      - DEBUG=true

  mcp-server:
    ports:
      - "27183:27183"
```

**Ключевое решение для проектов (локально vs VPS):**

| Режим | Где лежат проекты | Как сканируются |
|-------|-------------------|-----------------|
| Local Dev | `~/Documents/Projects` → volume mount | Docker видит Mac-файлы напрямую |
| VPS Phase 2 | `/home/deploy/rag/projects` на VPS | `git clone` из GitHub Actions при деплое |
| VPS Phase 3 | Загружаются пользователем через UI | Upload API или git URL |

---

## 5. Backend — FastAPI endpoints

### Полный список API

```
GET  /health                           → статус всех сервисов

# Проекты
GET  /api/projects                     → список проектов
POST /api/projects                     → добавить {path, name}
DEL  /api/projects/{name}              → удалить
POST /api/projects/{name}/scan         → запустить сканирование (SSE)
GET  /api/projects/{name}/stats        → статистика индекса

# Поиск (RAG)
POST /api/search                       → семантический поиск без LLM
POST /api/answer                       → поиск + ответ Claude (SSE stream)
POST /api/patch                        → режим патчинга кода (SSE stream)

# GraphRAG
POST /api/graph/build                  → построить граф знаний (SSE прогресс)
GET  /api/graph/{project}              → nodes + edges для визуализации
GET  /api/graph/summaries              → community summaries
POST /api/graph/query                  → глобальный GraphRAG запрос (SSE)

# Конфиг (Phase 2 → auth)
GET  /api/settings                     → текущие настройки
PUT  /api/settings                     → обновить (кроме API key — только через env)
```

### SSE формат для прогресса сканирования
```
POST /api/projects/my_bot/scan

data: {"type":"start","total_files":120,"project":"my_bot"}
data: {"type":"progress","scanned":45,"indexed":30,"current_file":"src/handlers/start.py"}
data: {"type":"progress","scanned":90,"indexed":78,"current_file":"src/config.py"}
data: {"type":"done","indexed":118,"skipped":2,"duration_sec":8.4}
```

### SSE формат для ответа Claude
```
POST /api/answer {"query": "обработка ошибок", "project": "my_bot"}

data: {"type":"sources","chunks":[{"file":"src/middlewares/error_handler.py","score":0.87}]}
data: {"type":"token","text":"В"}
data: {"type":"token","text":" проекте"}
data: {"type":"token","text":" my_bot"}
...
data: {"type":"done","total_tokens":342}
```

---

## 6. MCP Server — инструменты для AI

### Что такое MCP и зачем

Model Context Protocol (Anthropic, 2024) — стандарт для подключения внешних инструментов к AI-ассистентам. Поддерживается: Claude Desktop, Cursor, Windsurf, Continue.dev, любой MCP-клиент.

**Сценарий использования:**
1. Ты открываешь новый чат с Claude
2. Claude автоматически видит инструмент `search_rag`
3. Вместо того чтобы вставлять код проекта в чат — Claude сам ищет нужные части
4. Экономия: **95% токенов** при работе с кодовой базой

### MCP Tools (4 инструмента)

```python
# mcp-server/src/server.py

@mcp.tool()
async def search_project(
    query: str,
    project: str | None = None,    # None = по всем проектам
    top_k: int = 5
) -> list[dict]:
    """
    Semantic search over indexed IT projects.
    Use this when you need to find code, configs, or docs
    related to a specific concept or functionality.
    
    Returns list of relevant code chunks with file paths and scores.
    """

@mcp.tool()
async def list_projects() -> list[dict]:
    """
    List all indexed projects with their stats.
    Call this first to understand what projects are available.
    """

@mcp.tool()
async def get_file_content(
    project: str,
    file_path: str
) -> str:
    """
    Get full content of a specific file from an indexed project.
    Use after search_project when you need to see the complete file.
    """

@mcp.tool()
async def get_graph_summary(
    project: str | None = None   # None = cross-project summary
) -> str:
    """
    Get a high-level architectural summary of a project or all projects.
    Use this to quickly understand project architecture without reading code.
    Perfect for onboarding: start a session by calling this first.
    """
```

### Подключение к Claude Desktop
```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "rag-dev-assistant": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:27183/mcp"],
      "env": {}
    }
  }
}
```

### Подключение к Cursor
```json
// .cursor/mcp.json в папке проекта
{
  "mcpServers": {
    "rag": {
      "url": "http://localhost:27183/mcp"
    }
  }
}
```

**Phase 2 (VPS):** заменить `localhost:27183` на `https://rag.yourdomain.com/mcp` + добавить API-key аутентификацию.

---

## 7. Frontend — Web UI (Next.js)

### Страница 🔍 Поиск (главная)

```
┌──────────┬──────────────────────────────────────────────────────┐
│          │  🔍 Поиск по проектам                                 │
│ 📁 Scan  │                                                       │
│          │  ┌────────────────────────────────────────────────┐   │
│ 🔍 Search│  │ где обрабатывается авторизация?                │   │
│ ◄ active │  └────────────────────────────────────────────────┘   │
│          │                                                       │
│ 🕸 Graph  │  [◉ Ответ] [○ Поиск] [○ Патч]   [Все проекты ▼]   │
│          │  [○ Локальный RAG]  [○ GlobalRAG]                    │
│ ⚙ Настр. │  ─────────────────────────────────────────────────   │
│          │                                                       │
│ 🔌 MCP   │  В проекте **my_bot** авторизация реализована       │
│  ● онлайн│  через middleware в файле...                         │
│          │  ▌  (стриминг)                                       │
│          │                                                       │
│          │  ─────── Источники ──────────────────────────────    │
│          │  ● [0.87] my_bot / src/middlewares/error_handler.py  │
│          │  ● [0.72] my_bot / src/config.py                     │
│          │  ● [0.65] my_bot / src/main.py                       │
│          │                                                       │
│          │  [📋 Копировать] [🔄 Переспросить]                    │
└──────────┴──────────────────────────────────────────────────────┘
```

### Страница 📁 Scan (управление проектами)

```
┌──────────┬──────────────────────────────────────────────────────┐
│          │  📁 Проекты                          [+ Добавить]    │
│ 📁 Scan  │                                                       │
│ ◄ active │  ┌────────────────────────────────────────────────┐  │
│          │  │  my_bot             Python · Telegram Bot       │  │
│ 🔍 Search│  │  118 файлов · проиндексирован 2ч назад          │  │
│          │  │  ChromaDB ✓  Knowledge Graph ✓                  │  │
│ 🕸 Graph  │  │                            [↺ Ресканировать] [🗑]│  │
│          │  ├────────────────────────────────────────────────┤  │
│ ⚙ Настр. │  │  fastapi_service    Python · FastAPI            │  │
│          │  │  89 файлов · проиндексирован вчера              │  │
│ 🔌 MCP   │  │  ChromaDB ✓  Knowledge Graph —                  │  │
│          │  │                            [↺ Ресканировать] [🗑]│  │
│          │  └────────────────────────────────────────────────┘  │
│          │                                                       │
│          │  ┌─── Перетащи папку проекта сюда ───────────────┐   │
│          │  │            или нажми + Добавить               │   │
│          │  └────────────────────────────────────────────────┘  │
│          │                                                       │
│          │  ┌─────────────────────────────────────────────┐     │
│          │  │ 🕸 Построить граф знаний для всех проектов   │     │
│          │  │    Оценка: ~4,200 токенов · ~$0.005         │     │
│          │  │                          [Запустить]        │     │
│          │  └─────────────────────────────────────────────┘     │
└──────────┴──────────────────────────────────────────────────────┘
```

### Страница 🕸 Граф знаний

```
┌──────────┬──────────────────────────────────────────────────────┐
│          │  🕸 Knowledge Graph    [Проект: Все ▼]               │
│          │                                                       │
│ 🕸 Graph  │  ┌─────────────────────────────────────────────┐    │
│ ◄ active │  │                                             │    │
│          │  │   ●main.py                                  │    │
│          │  │    │registers                               │    │
│          │  │  ●handlers/ ── uses ──→ ●models.py          │    │
│          │  │    │                       │                │    │
│          │  │  ●keyboards/    ●config ──→●connection.py   │    │
│          │  │                                             │    │
│          │  │  [D3.js force-directed graph]               │    │
│          │  │  Zoom / Pan / Клик по ноде                  │    │
│          │  └─────────────────────────────────────────────┘    │
│          │                                                       │
│          │  [Выбрана нода: src/handlers/start.py]               │
│          │  Тип: code · Роль: handler                           │
│          │  Связи: registers ← main.py                          │
│          │         uses → database/models.py                    │
│          │  [Открыть файл] [Искать похожее]                     │
└──────────┴──────────────────────────────────────────────────────┘
```

**Библиотека для графа:** `react-force-graph` (WebGL, до 10,000 нод без тормозов).

---

## 8. GraphRAG Pipeline (детально)

### Шаг 1: Entity Extraction (при нажатии "Построить граф знаний")

```python
# backend/src/services/graphrag.py

ENTITY_EXTRACTION_PROMPT = """
Ты анализируешь код IT-проекта. Извлеки сущности и связи.

Код файла {file_path}:
{content}

Верни JSON:
{
  "entities": [
    {"name": "notify_admin", "type": "function", "description": "..."},
    {"name": "ErrorHandler", "type": "class", "description": "..."}
  ],
  "relations": [
    {"from": "main.py", "to": "handlers/start.py", "type": "registers"},
    {"from": "handlers/start.py", "to": "database/models.py", "type": "uses"}
  ]
}

Типы сущностей: function | class | module | config | entrypoint
Типы связей: uses | imports | registers | implements | calls | depends_on | configures
"""
```

### Шаг 2: Community Detection
```python
import networkx as nx
from networkx.algorithms.community import louvain_communities

def detect_communities(nodes, edges) -> dict[int, list[str]]:
    G = nx.Graph()
    G.add_nodes_from([n["id"] for n in nodes])
    G.add_edges_from([(e["source"], e["target"]) for e in edges])
    communities = louvain_communities(G, seed=42)
    return {i: list(community) for i, community in enumerate(communities)}
```

### Шаг 3: Community Summaries (для GlobalRAG)
```python
COMMUNITY_SUMMARY_PROMPT = """
Ты анализируешь кластер взаимосвязанных файлов IT-проекта.

Файлы в кластере:
{node_names_and_descriptions}

Напиши краткое (3-5 предложений) техническое резюме этого кластера:
- Что эти файлы делают вместе?
- Какую архитектурную роль выполняют?
- Ключевые паттерны/технологии?
"""
```

### Шаг 4: GlobalRAG Query
```python
async def global_query(query: str) -> str:
    """
    Вместо поиска по чанкам — ищем по community summaries.
    Позволяет отвечать на вопросы уровня всей архитектуры.
    """
    # Ищем релевантные community summaries
    relevant_summaries = await search_summaries(query, top_k=10)
    
    # Просим Claude синтезировать ответ
    context = format_summaries(relevant_summaries)
    return await llm.answer(query, context, mode="global_synthesis")
```

---

## 9. macOS App (Swift/SwiftUI) — тонкий клиент

### Что делает Swift-часть (только то, что нельзя сделать в браузере)

```swift
// RAGAssistantApp.swift
@main struct RAGAssistantApp: App {
    var body: some Scene {
        MenuBarExtra("RAG", systemImage: "brain.head.profile") {
            MenuBarView()
        }
        .menuBarExtraStyle(.window)  // popup окно
    }
}

// MenuBarView.swift
struct MenuBarView: View {
    @State private var backendURL = UserDefaults.standard.string(
        forKey: "backendURL") ?? "http://localhost:8080"
    
    var body: some View {
        WebContentView(url: URL(string: backendURL)!)
            .frame(width: 900, height: 650)
    }
}

// WebContentView.swift — WKWebView, показывает Next.js UI
struct WebContentView: NSViewRepresentable {
    let url: URL
    func makeNSView(context: Context) -> WKWebView { WKWebView() }
    func updateNSView(_ webView: WKWebView, context: Context) {
        webView.load(URLRequest(url: url))
    }
}
```

**Что делает Swift:**
- Menu bar иконка + popup
- Глобальный хоткей (⌥Space) через `Carbon.framework`
- macOS уведомления при завершении сканирования (через JavaScript bridge)
- ANTHROPIC_API_KEY → macOS Keychain (один раз при первом запуске)
- Запуск Docker backend при старте приложения (Phase 1)
- В Phase 2+: просто URL настраивается на VPS

**Что НЕ делает Swift (всё в Web UI):**
- Весь UI поиска, проектов, графа — в Next.js
- Логика — в Python

---

## 10. Переменные окружения (.env.example)

```bash
# ── ОБЯЗАТЕЛЬНЫЕ ──────────────────────────────────────────

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...

# Telegram уведомления об ошибках (стандарт PVMaksim)
ADMIN_TELEGRAM_ID=123456789
TELEGRAM_BOT_TOKEN=bot_token_here

# ── ПУТИ (переопределяются при деплое на VPS) ──────────────

# Локальная разработка: ./data/chroma_db
# VPS: /home/deploy/rag-dev-assistant/data/chroma_db
CHROMA_DB_PATH=/app/data/chroma_db
GRAPH_DB_PATH=/app/data/graph.db
PROJECTS_BASE_PATH=/app/projects

# ── МОДЕЛИ ────────────────────────────────────────────────

# Claude модель для ответов и GraphRAG
CLAUDE_MODEL=claude-sonnet-4-20250514

# Embedding модель (офлайн)
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Кол-во чанков по умолчанию
DEFAULT_TOP_K=5

# ── MCP SERVER ────────────────────────────────────────────

MCP_SERVER_PORT=27183
# В Phase 2: добавить MCP_API_KEY для аутентификации

# ── PHASE 2: АУТЕНТИФИКАЦИЯ (оставить пустым в Phase 1) ──

# APP_SECRET_KEY=  # JWT secret
# AUTH_ENABLED=false

# ── NGINX / SSL (нужен только на VPS) ────────────────────

# DOMAIN=rag.yourdomain.com
# CERTBOT_EMAIL=your@email.com
```

---

## 11. CI/CD (GitHub Actions)

### deploy.yml — деплой на VPS при push в main
```yaml
name: Deploy to VPS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: deploy
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /home/deploy/rag-dev-assistant
            git pull origin main
            docker-compose pull
            docker-compose up -d --build
            docker-compose ps

      - name: Health Check
        run: |
          sleep 10
          curl -f https://${{ secrets.DOMAIN }}/health || exit 1

      - name: Notify Telegram
        if: always()
        run: |
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
          -d "chat_id=${{ secrets.ADMIN_TELEGRAM_ID }}" \
          -d "text=🚀 RAG Dev Assistant: деплой ${{ job.status }}"
```

### release-mac.yml — сборка .dmg при теге v*
```yaml
name: Release macOS App

on:
  push:
    tags: ['v*']

jobs:
  build-mac:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Xcode Archive
        run: |
          cd mac-app
          xcodebuild archive -scheme RAGAssistant \
            -archivePath ./build/RAGAssistant.xcarchive
      - name: Export .app and create .dmg
        run: ./scripts/build_dmg.sh
      - name: Upload to GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          files: ./build/RAGAssistant.dmg
```

---

## 12. Plan реализации — пофазно

### Фаза 1: Работающий локальный инструмент (2–3 недели)

**Неделя 1: Backend + Docker**
- [ ] Рефакторинг `scan.py` + `query.py` → классы в `backend/src/services/`
- [ ] Убрать захардкоженные пути → `config.py` из env
- [ ] FastAPI: `/health`, `/search`, `/answer` (SSE), `/projects` CRUD, `/scan` (SSE)
- [ ] `docker-compose.yml` + `docker-compose.dev.yml`
- [ ] `.env.example` по стандарту
- [ ] Тест: `docker-compose up` → `curl /health` → OK

**Неделя 2: Web UI (Next.js)**
- [ ] Scaffold Next.js 14 + TypeScript + Tailwind
- [ ] Sidebar навигация (Scan / Search / Graph / Settings)
- [ ] SearchPanel: поле ввода, переключатели режима, выбор проекта
- [ ] ResultsPanel: стриминг ответа, список источников, кнопка копировать
- [ ] ProjectsList: список проектов, добавление, прогресс-бар сканирования (SSE)
- [ ] Тест: открыть `localhost:8080` → найти что-то в проекте → получить ответ

**Неделя 3: GraphRAG + Graph Viewer + MCP**
- [ ] `graphrag.py`: entity extraction → SQLite → community detection → summaries
- [ ] Кнопка "Построить граф знаний" с оценкой стоимости и SSE прогрессом
- [ ] `GET /graph/{project}` → nodes + edges JSON
- [ ] GraphViewer с `react-force-graph`: рендер графа, клик по ноде → детали
- [ ] MCP Server: `search_project`, `list_projects`, `get_graph_summary`, `get_file_content`
- [ ] Тест MCP в Claude Desktop: подключить → Claude находит код без вставки файлов

### Фаза 2: Деплой на VPS (1 неделя)

- [ ] `scripts/init_ssl.sh` — Certbot Let's Encrypt
- [ ] `nginx.conf` — HTTPS, reverse proxy на frontend + backend
- [ ] GitHub Actions `deploy.yml`
- [ ] Базовая аутентификация (HTTP Basic Auth через nginx или simple API key)
- [ ] `scripts/backup.sh` — ChromaDB + graph.db → облако (раз в сутки, cron)
- [ ] Telegram уведомления об ошибках backend (middleware)
- [ ] Тест: `https://rag.yourdomain.com` работает, деплой через git push

### Фаза 3: macOS SwiftUI App (1 неделя)

- [ ] Xcode проект: MenuBarExtra + SwiftUI
- [ ] `WebContentView`: WKWebView → открывает URL из настроек
- [ ] `HotkeyService`: глобальный хоткей ⌥Space
- [ ] `KeychainService`: хранить backend URL + API key
- [ ] Первый запуск: диалог "введи URL бэкенда" (localhost или VPS)
- [ ] macOS уведомления: JavaScript → WKScriptMessageHandler → UNUserNotification
- [ ] GitHub Actions → .dmg в GitHub Release

### Фаза 4: Production (будущее)

- [ ] Multi-user: JWT auth, user namespaces в ChromaDB
- [ ] Upload API: пользователь загружает проект через UI
- [ ] Billing: Stripe integration
- [ ] Windows: Electron wrapper (WKWebView → WebView2, тот же Web UI)
- [ ] Linux: Flatpak или просто "открой браузер"

---

## 13. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| sentence-transformers тяжёлые (1GB+ в Docker) | Высокая | Среднее | Multi-stage build, кэш слоёв, или OpenAI embeddings API как альтернатива |
| GraphRAG entity extraction дорогой | Средняя | Среднее | Батчинг файлов, показ оценки стоимости, кэш в SQLite |
| VPS: проекты не доступны без копирования | Средняя | Высокое | Phase 2: `git clone` из GitHub, volume mount только локально |
| react-force-graph медленно на больших графах | Низкая | Низкое | Пагинация нод, Level of Detail, фильтр по priority |
| MCP auth на VPS (токен утечёт) | Средняя | Высокое | HTTPS обязательно, MCP_API_KEY в header, rate limiting |

---

## 14. ADR — ключевые решения

### ADR-001: WKWebView вместо нативного SwiftUI

**Статус:** Принято

**Контекст:** Нужен кроссплатформенный UI (Mac + Win + Linux в будущем) и нативный menu bar на Mac.

**Решение:** SwiftUI отвечает только за menu bar + хоткей + нативные API. Весь UI — Next.js в WebView.

**Плюсы:** Один UI для всех платформ. Нет дублирования кода. Быстрее разработка.
**Минусы:** Не 100% нативный feel. Требует запущенного бэкенда.

---

### ADR-002: Docker-first с dev override

**Статус:** Принято

**Решение:** Один `docker-compose.yml` для prod/VPS. `docker-compose.dev.yml` override для локальной разработки с volume mount и hot reload.

**Плюсы:** Один конфиг. Деплой = git push. Нет "у меня локально работало".

---

### ADR-003: MCP через HTTP transport, не stdio

**Статус:** Принято

**Контекст:** stdio MCP работает только локально. HTTP MCP доступен и локально, и с VPS.

**Решение:** `mcp-server` как отдельный контейнер, HTTP transport на порту 27183.

**Плюсы:** Один конфиг MCP работает и с localhost, и с VPS URL.

---

### ADR-004: react-force-graph для Knowledge Graph

**Статус:** Принято

**Контекст:** D3.js — слишком низкоуровневый. Cytoscape.js — тяжёлый и некрасивый. Vis.js — устаревший.

**Решение:** `react-force-graph` (WebGL рендер, до 50K нод, активно поддерживается).

---

## 15. Критерии приёмки

### Фаза 1 (обязательно перед переходом к Фазе 2)
- [ ] `docker-compose up` — все 4 сервиса зелёные
- [ ] `curl localhost:8080/health` → `{"status": "ok"}`
- [ ] Добавить проект через UI → прогресс-бар → завершено
- [ ] Запрос "обработка ошибок" → ответ с указанием файлов
- [ ] GraphRAG: кнопка → граф построен → в GraphViewer видны ноды и рёбра
- [ ] MCP: Claude Desktop подключён → Claude находит код без вставки файлов
- [ ] Глобальный запрос GraphRAG: "как устроена архитектура?" → связный ответ

### Фаза 2 (деплой)
- [ ] `https://rag.yourdomain.com` — открывается Web UI
- [ ] Push в main → автодеплой → Telegram уведомление
- [ ] MCP работает через VPS URL в Cursor
