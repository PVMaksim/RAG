#!/usr/bin/env bash
# setup.sh — первоначальная настройка RAG Dev Assistant
# Запуск: ./scripts/setup.sh
#
# Что делает:
#   1. Проверяет зависимости (Docker, docker-compose)
#   2. Копирует .env.example → .env если .env не существует
#   3. Запрашивает ANTHROPIC_API_KEY интерактивно
#   4. Проверяет путь к проектам в docker-compose.dev.yml
#   5. Запускает docker-compose и проверяет health

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $1${RESET}"; }
err()  { echo -e "${RED}❌ $1${RESET}"; exit 1; }
ask()  { echo -e "${YELLOW}?  $1${RESET}"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     RAG Dev Assistant — первый запуск    ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Проверка зависимостей ──────────────────────────────────────────────────

echo "Проверяю зависимости..."

if ! command -v docker &>/dev/null; then
    err "Docker не установлен. Скачай на docker.com"
fi
ok "Docker $(docker --version | grep -o '[0-9.]*' | head -1)"

if ! docker compose version &>/dev/null && ! command -v docker-compose &>/dev/null; then
    err "docker compose не найден. Обнови Docker Desktop до последней версии."
fi
ok "docker compose доступен"

if ! docker info &>/dev/null; then
    err "Docker не запущен. Запусти Docker Desktop."
fi
ok "Docker daemon запущен"

echo ""

# ── 2. Файл .env ──────────────────────────────────────────────────────────────

echo "Настройка .env..."

if [ -f ".env" ]; then
    warn ".env уже существует — пропускаю создание"
else
    cp .env.example .env
    ok ".env создан из .env.example"
fi

# ── 3. ANTHROPIC_API_KEY ──────────────────────────────────────────────────────

CURRENT_KEY=$(grep "^ANTHROPIC_API_KEY=" .env | cut -d= -f2 | tr -d '"')

if [ -z "$CURRENT_KEY" ] || [ "$CURRENT_KEY" = "sk-ant-..." ]; then
    echo ""
    ask "Введи Anthropic API ключ (console.anthropic.com):"
    read -r -s API_KEY
    echo ""

    if [ -z "$API_KEY" ]; then
        err "API ключ не может быть пустым"
    fi

    if [[ ! "$API_KEY" =~ ^sk- ]]; then
        err "Неверный формат ключа. Ожидается: sk-ant-..."
    fi

    # Заменяем в .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${API_KEY}|" .env
    else
        sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${API_KEY}|" .env
    fi
    ok "ANTHROPIC_API_KEY сохранён в .env"
else
    ok "ANTHROPIC_API_KEY уже задан"
fi

# ── 4. Путь к проектам ────────────────────────────────────────────────────────

echo ""
echo "Настройка пути к проектам..."

DEFAULT_PROJECTS="$HOME/Documents/Projects"
ask "Где лежат твои проекты? [${DEFAULT_PROJECTS}]:"
read -r PROJECTS_PATH
PROJECTS_PATH="${PROJECTS_PATH:-$DEFAULT_PROJECTS}"

if [ ! -d "$PROJECTS_PATH" ]; then
    warn "Папка не найдена: $PROJECTS_PATH"
    ask "Создать? [y/N]:"
    read -r CREATE_DIR
    if [[ "$CREATE_DIR" =~ ^[Yy]$ ]]; then
        mkdir -p "$PROJECTS_PATH"
        ok "Создана: $PROJECTS_PATH"
    else
        warn "Продолжаю без монтирования проектов. Измени путь в docker-compose.dev.yml позже."
        PROJECTS_PATH=""
    fi
fi

if [ -n "$PROJECTS_PATH" ]; then
    # Обновляем docker-compose.dev.yml
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|~/Documents/Projects|${PROJECTS_PATH}|g" docker-compose.dev.yml
    else
        sed -i "s|~/Documents/Projects|${PROJECTS_PATH}|g" docker-compose.dev.yml
    fi
    ok "Путь обновлён в docker-compose.dev.yml: $PROJECTS_PATH"
fi

# ── 5. Telegram (опционально) ─────────────────────────────────────────────────

echo ""
ask "Настроить Telegram уведомления об ошибках? [y/N]:"
read -r SETUP_TG
if [[ "$SETUP_TG" =~ ^[Yy]$ ]]; then
    ask "Telegram Bot Token (от @BotFather):"
    read -r TG_TOKEN
    ask "Твой Telegram ID (от @userinfobot):"
    read -r TG_ID

    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TG_TOKEN}|" .env
        sed -i '' "s|^ADMIN_TELEGRAM_ID=.*|ADMIN_TELEGRAM_ID=${TG_ID}|" .env
    else
        sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TG_TOKEN}|" .env
        sed -i "s|^ADMIN_TELEGRAM_ID=.*|ADMIN_TELEGRAM_ID=${TG_ID}|" .env
    fi
    ok "Telegram настроен"
fi

# ── 6. Сборка и запуск ────────────────────────────────────────────────────────

echo ""
echo "Запускаю Docker Compose..."
echo "(первая сборка может занять 5–10 минут — скачивает sentence-transformers модель)"
echo ""

docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

echo ""
echo "Жду запуска бэкенда (до 90 секунд)..."

MAX_WAIT=90
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        break
    fi
    sleep 3
    WAITED=$((WAITED + 3))
    printf "."
done
echo ""

if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    ok "Бэкенд запущен!"
    HEALTH=$(curl -s http://localhost:8080/health)
    echo "   $HEALTH"
else
    warn "Бэкенд ещё не готов. Проверь логи: docker compose logs backend"
fi

# ── 7. Итог ───────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║              Готово! 🎉                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Web UI:    http://localhost:8080"
echo "  API docs:  http://localhost:8080/api/docs"
echo "  MCP:       http://localhost:27183/mcp/sse"
echo ""
echo "  Следующие шаги:"
echo "  1. Открой http://localhost:8080"
echo "  2. Перейди в Проекты → добавь папку с проектом"
echo "  3. Дождись сканирования"
echo "  4. Перейди в Поиск и задай вопрос"
echo ""
echo "  MCP для Claude Desktop:"
echo '  Добавь в ~/Library/Application Support/Claude/claude_desktop_config.json:'
echo '  {"mcpServers":{"rag":{"command":"npx","args":["mcp-remote","http://localhost:27183/mcp/sse"]}}}'
echo ""
