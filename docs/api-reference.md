# API Reference — RAG Dev Assistant

**Base URL:** `http://localhost:8080/api` (локально) · `https://rag.yourdomain.com/api` (VPS)

**Interactive docs:** `/api/docs` (Swagger UI) · `/api/redoc` (ReDoc)

---

## Поиск

### `POST /search/`
Семантический поиск без LLM. Возвращает top-K чанков.

**Rate limit:** 30/мин

```json
// Request
{
  "query":   "где обрабатывается авторизация",
  "project": "my_bot",          // опционально — фильтр по проекту
  "top_k":   5,                  // 1–20, дефолт 5
  "mode":    "search"
}

// Response 200
{
  "chunks": [
    {
      "project":         "my_bot",
      "file":            "src/middlewares/error_handler.py",
      "role":            "code",
      "score":           0.87,
      "content_preview": "async def handle_error(bot: Bot..."
    }
  ]
}

// Response 404 — пустой индекс
{ "error": "EmptyIndexError", "message": "Ничего не найдено...", "request_id": "uuid" }
```

---

### `POST /search/answer` · SSE
Поиск + ответ Claude. Server-Sent Events стриминг.

**Rate limit:** 20/мин

```
// Request (то же что /search/, mode: "answer")
// SSE события:
data: {"type":"sources","chunks":[{"file":"...","score":0.87}]}
data: {"type":"token","text":"В проекте"}
data: {"type":"token","text":" my_bot"}
...
data: {"type":"done","total_tokens":342}

// При ошибке:
data: {"type":"error","message":"...","request_id":"uuid"}
```

Поддерживает многоходовой диалог через поле `history`:
```json
{
  "query": "а как это тестируется?",
  "history": [
    {"role": "user",      "content": "где авторизация?"},
    {"role": "assistant", "content": "В src/auth.py..."}
  ]
}
```

---

### `POST /search/patch` · SSE
Генерация патча кода. Те же SSE события что и `/answer`.

**Rate limit:** 10/мин

---

### `POST /search/global` · SSE
GlobalRAG — запросы уровня всей кодовой базы через community summaries.
Требует построенного Knowledge Graph.

**Rate limit:** 10/мин

---

## Проекты

### `GET /projects/`
Список всех проиндексированных проектов.

```json
{
  "projects": [
    {
      "name":         "my_bot",
      "file_count":   118,
      "project_type": "telegram_bot",
      "has_graph":    true,
      "graph_stats":  {"nodes": 45, "edges": 30, "communities": 5}
    }
  ]
}
```

---

### `POST /projects/`
Добавить проект по локальному пути.

```json
// Request
{ "path": "/app/projects/my_bot", "name": "my_bot" }

// Response 200
{ "status": "ok", "name": "my_bot", "path": "/app/projects/my_bot" }
```

---

### `DELETE /projects/{name}`
Удалить проект из всех индексов (ChromaDB + Knowledge Graph).

---

### `POST /projects/{name}/scan` · SSE
Сканировать проект из `PROJECTS_BASE_PATH/{name}`.

```
data: {"type":"start","project":"my_bot","files_total":120}
data: {"type":"progress","files_scanned":45,"files_indexed":30,"current_file":"src/main.py"}
data: {"type":"done","files_indexed":118,"duration_sec":8.4}
```

---

### `POST /projects/{name}/graph/estimate`
Оценить стоимость построения Knowledge Graph.

```json
{ "file_count": 118, "estimated_tokens": 141600, "estimated_cost_display": "~$0.003" }
```

---

### `POST /projects/{name}/graph/build` · SSE
Построить Knowledge Graph (entity extraction → community detection → summaries).

```
data: {"type":"start","total_files":118,"phase":"entity_extraction"}
data: {"type":"progress","phase":"entity_extraction","processed":60,"total":118}
data: {"type":"progress","phase":"community_detection"}
data: {"type":"progress","phase":"community_summaries"}
data: {"type":"done","nodes":45,"edges":30,"communities":5}
```

---

### `POST /projects/git/clone` · SSE
Клонировать Git репозиторий и сразу проиндексировать.

```json
// Request
{ "git_url": "https://github.com/user/repo.git", "project_name": "my-repo" }
```

---

### `POST /projects/git/pull/{name}` · SSE
Обновить существующий Git проект и переиндексировать.

---

## Knowledge Graph

### `GET /graph/{project_name}`
Данные графа для визуализации (react-force-graph формат).

```json
{
  "nodes": [{"id":"abc","name":"main.py","type":"entrypoint","community":0}],
  "links": [{"source":"abc","target":"def","relation":"registers"}],
  "stats": {"nodes":45,"edges":30,"communities":5},
  "communities": [{"id":0,"title":"Entry Points","node_count":3}]
}
```

---

### `GET /graph/summaries?project=name`
Community summaries для GlobalRAG.

---

## Загрузка

### `POST /upload/zip` · SSE · multipart/form-data
Загрузить ZIP архив и сразу проиндексировать.

```
// Form fields:
// file: <zip file>
// project_name: "my-project" (опционально)

data: {"type":"upload_start","filename":"project.zip","project":"my-project"}
data: {"type":"upload_done","size_mb":12.4}
data: {"type":"progress","files_scanned":45,...}
data: {"type":"done","files_indexed":118}
```

**Ограничения:** 100MB, 10 000 файлов, 5 запросов/мин

---

### `GET /upload/limits`
Текущие ограничения на загрузку.

---

## Webhook

### `POST /webhook/github`
GitHub Webhook endpoint. Верифицирует HMAC-SHA256 подпись.

**Настройка:** GitHub → repo → Settings → Webhooks → Add webhook

```
Payload URL:  https://rag.yourdomain.com/api/webhook/github
Content type: application/json
Secret:       значение WEBHOOK_SECRET из .env
Events:       Just the push event
```

---

## Настройки

### `GET /settings/`
Текущие настройки (без секретов).

```json
{
  "claude_model":      "claude-sonnet-4-20250514",
  "default_top_k":     5,
  "has_anthropic_key": true,
  "has_telegram":      false,
  "disk_free_gb":      12.4
}
```

---

### `PUT /settings/`
Обновить изменяемые настройки в runtime.

```json
// Request
{ "default_top_k": 10, "debug": false }

// Response
{ "status": "updated", "changed": {"default_top_k": 10} }
```

---

## Мониторинг

### `GET /health`
Статус всех компонентов.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "checks": {
    "chroma":           {"status": "ok", "projects": 3},
    "graph_store":      {"status": "ok", "stats": {"nodes": 150}},
    "anthropic":        {"status": "ok", "model": "claude-sonnet-4-20250514"},
    "embedding_cache":  {"status": "ok", "hit_rate": 78.5, "currsize": 124},
    "disk":             {"status": "ok", "free_gb": 12.4, "used_pct": 68.2}
  }
}
```

`status` может быть: `ok` · `degraded` · `error`
`disk.status`: `ok` (< 80%) · `warning` (80–90%) · `critical` (> 90%)

---

### `GET /metrics`
Prometheus метрики. Формат text/plain.

```
# HELP rag_uptime_seconds Application uptime in seconds
rag_uptime_seconds 3600
# HELP rag_indexed_projects_total Total number of indexed projects
rag_indexed_projects_total 3
...
```

---

## MCP Server (порт 27183)

**Endpoint:** `http://localhost:27183/mcp/sse`

Инструменты для AI-ассистентов (Claude Desktop, Cursor, Windsurf):

| Tool | Описание |
|------|---------|
| `search_project(query, project?, top_k?)` | Семантический поиск по коду |
| `list_projects()` | Список проиндексированных проектов |
| `get_graph_summary(project?)` | Архитектурное резюме |
| `get_file_content(project, file_path)` | Содержимое файла |

**Auth (если задан `MCP_API_KEY`):**
```
Authorization: Bearer <MCP_API_KEY>
```

---

## Коды ошибок

| HTTP | Error | Описание |
|------|-------|---------|
| 400 | `RAGError` | Ошибка валидации запроса |
| 403 | `Forbidden` | Неверный webhook/MCP ключ |
| 404 | `ProjectNotFoundError` | Проект не найден в индексе |
| 404 | `EmptyIndexError` | Нет результатов поиска |
| 404 | `GraphNotBuiltError` | Knowledge Graph не построен |
| 409 | `ProjectAlreadyScanningError` | Проект уже сканируется |
| 422 | Validation Error | Неверные параметры запроса |
| 429 | Rate Limited | Превышен лимит запросов |
| 500 | `InternalServerError` | Внутренняя ошибка |
| 503 | `StorageError` | ChromaDB/SQLite недоступны |

Все ошибки имеют формат:
```json
{ "error": "ErrorClassName", "message": "...", "request_id": "uuid" }
```
