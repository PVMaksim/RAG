# RAG Dev Assistant

Семантический поиск по IT-проектам с Knowledge Graph и MCP-сервером.

Позволяет за секунды найти любой код в своих проектах и подключить Claude Desktop / Cursor / Windsurf к кодовой базе — без загрузки файлов в контекст (экономия до 95% токенов).

## Возможности

- **🔍 Семантический поиск** — спросить «где обрабатываются ошибки?» и получить файлы с релевантностью
- **💬 Ответ через Claude** — LLM отвечает на основе найденных чанков кода (SSE стриминг)
- **🔧 Патчинг кода** — Claude предлагает конкретный diff для задачи
- **🕸 Knowledge Graph** — граф зависимостей между файлами, кластеризация по Louvain
- **🌐 GlobalRAG** — архитектурные вопросы по всем проектам через community summaries
- **🔌 MCP сервер** — подключение AI-ассистентов к поиску по коду

## Быстрый старт

```bash
git clone https://github.com/PVMaksim/rag-dev-assistant
cd rag-dev-assistant
./scripts/setup.sh      # проверит Docker, создаст .env, запросит API ключ
```

Или вручную:
```bash
cp .env.example .env
# Добавь ANTHROPIC_API_KEY и путь к проектам
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Открой **http://localhost:8080** → Проекты → добавь папку → Поиск.

## MCP — подключение AI-ассистентов

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "rag": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:27183/mcp/sse"]
    }
  }
}
```

**Cursor / Windsurf** (`.cursor/mcp.json` в папке проекта):
```json
{
  "mcpServers": {
    "rag": { "url": "http://localhost:27183/mcp/sse" }
  }
}
```

После подключения Claude сам ищет релевантный код вместо того чтобы ты вставлял файлы в чат.

## Деплой на VPS

```bash
# 1. Добавь в GitHub Secrets:
#    VPS_HOST, SSH_PRIVATE_KEY, DOMAIN, TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID

# 2. SSL сертификат (один раз):
DOMAIN=rag.yourdomain.com EMAIL=you@email.com ./scripts/init_ssl.sh

# 3. Деплой — автоматически при push в main:
git push origin main

# 4. Или вручную:
ssh deploy@your-vps "cd /home/deploy/rag-dev-assistant && git pull && docker-compose up -d --build"
```

После деплоя замени `localhost:27183` на `https://rag.yourdomain.com` в конфиге MCP.

## Переменные окружения

Все переменные с описанием — в `.env.example`. Обязательные:

| Переменная | Описание |
|------------|---------|
| `ANTHROPIC_API_KEY` | Ключ с console.anthropic.com (формат `sk-ant-...`) |
| `TELEGRAM_BOT_TOKEN` | Бот для алертов об ошибках (опционально) |
| `ADMIN_TELEGRAM_ID` | Твой Telegram ID (опционально) |

## Структура проекта

```
backend/src/         FastAPI: config, services, routers, storage, middleware
frontend/src/        Next.js: страницы Search, Projects, Graph, Settings
mcp-server/src/      MCP сервер: 4 инструмента для AI-ассистентов
mac-app/             SwiftUI: menu bar иконка + WKWebView клиент
docker/              Dockerfiles + nginx конфиг
scripts/             setup.sh, backup.sh, restore.sh, health_check.sh
.github/workflows/   ci.yml, deploy.yml, release-mac.yml
```

## Тестирование

```bash
# Все тесты с покрытием
docker-compose exec backend pytest tests/ -v --cov=src --cov-report=term-missing

# Только быстрые юнит-тесты
docker-compose exec backend pytest tests/ -v -k "not integration"

# Health check всех сервисов
./scripts/health_check.sh
```

## Бэкап и восстановление

```bash
# Создать бэкап (ChromaDB + graph.db)
./scripts/backup.sh

# Восстановить из бэкапа
./scripts/restore.sh /path/to/rag-backup-20260415.tar.gz

# Предварительный просмотр без изменений
./scripts/restore.sh /path/to/backup.tar.gz --dry-run
```

## macOS приложение

Собирается через Xcode из `mac-app/RAGAssistant.xcodeproj`.  
При каждом теге `v*` GitHub Actions собирает `.dmg` и публикует в Releases.

Приложение появляется как иконка в menu bar. Глобальный хоткей `⌥Space`.  
При первом запуске укажи URL бэкенда в настройках (⌘,).
