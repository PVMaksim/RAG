#!/usr/bin/env bash
# restore.sh — восстановление данных RAG Dev Assistant из бэкапа
#
# Использование:
#   ./scripts/restore.sh /path/to/rag-backup-20260415_030001.tar.gz
#   ./scripts/restore.sh /path/to/rag-backup-20260415_030001.tar.gz --dry-run

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✅ $1${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $1${RESET}"; }
err()  { echo -e "${RED}❌ $1${RESET}"; exit 1; }

BACKUP_FILE="${1:-}"
DRY_RUN=false
[ "${2:-}" = "--dry-run" ] && DRY_RUN=true

# ── Валидация ─────────────────────────────────────────────────────────────────

if [ -z "$BACKUP_FILE" ]; then
    echo "Использование: $0 <backup.tar.gz> [--dry-run]"
    echo ""
    echo "Пример: $0 /home/deploy/backups/rag/rag-backup-20260415_030001.tar.gz"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    err "Файл бэкапа не найден: $BACKUP_FILE"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   RAG Dev Assistant — Восстановление     ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Бэкап: $BACKUP_FILE"
echo "  Размер: $(du -sh "$BACKUP_FILE" | cut -f1)"
if $DRY_RUN; then
    warn "Режим DRY-RUN — данные не будут изменены"
fi
echo ""

# ── Распаковка во временную папку ─────────────────────────────────────────────

TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "Распаковываю бэкап..."
tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR"
ok "Распаковано в $TEMP_DIR"

# Проверяем структуру
BACKUP_DATA="$TEMP_DIR/$(ls "$TEMP_DIR")/data"
if [ ! -d "$BACKUP_DATA" ]; then
    err "Неверная структура бэкапа. Ожидается папка 'data/' внутри архива."
fi

echo ""
echo "Содержимое бэкапа:"
find "$BACKUP_DATA" -type f | while read f; do
    SIZE=$(du -sh "$f" | cut -f1)
    echo "  • $(basename "$f") ($SIZE)"
done
echo ""

# ── Проверяем запущенные контейнеры ───────────────────────────────────────────

if docker compose ps --services --filter status=running 2>/dev/null | grep -q "backend"; then
    warn "Backend контейнер запущен. Рекомендуется остановить его перед восстановлением."
    echo -n "Остановить? [y/N]: "
    read -r STOP_CONTAINERS
    if [[ "$STOP_CONTAINERS" =~ ^[Yy]$ ]] && ! $DRY_RUN; then
        docker compose stop backend
        ok "Backend остановлен"
    fi
fi

# ── Определяем пути для восстановления ────────────────────────────────────────

# Вариант 1: Docker volumes (prod)
CHROMA_VOLUME=$(docker volume inspect rag-dev-assistant_chroma_data 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Mountpoint'])" 2>/dev/null || echo "")

GRAPH_VOLUME=$(docker volume inspect rag-dev-assistant_graph_data 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Mountpoint'])" 2>/dev/null || echo "")

# Вариант 2: Локальные данные (dev)
LOCAL_DATA="${DATA_DIR:-$(pwd)/data}"

echo "Определены пути:"
echo "  ChromaDB volume: ${CHROMA_VOLUME:-не найден}"
echo "  Graph volume:    ${GRAPH_VOLUME:-не найден}"
echo "  Локальные данные: $LOCAL_DATA"
echo ""

# ── Восстановление ChromaDB ───────────────────────────────────────────────────

restore_chroma() {
    local src="$BACKUP_DATA/chroma_db"
    if [ ! -d "$src" ]; then
        warn "ChromaDB данные не найдены в бэкапе — пропускаю"
        return
    fi

    if $DRY_RUN; then
        warn "[DRY-RUN] Бы восстановил ChromaDB из $src"
        return
    fi

    if [ -n "$CHROMA_VOLUME" ] && [ -d "$CHROMA_VOLUME" ]; then
        echo "Восстанавливаю ChromaDB → Docker volume..."
        rm -rf "${CHROMA_VOLUME:?}/"*
        cp -r "$src/." "$CHROMA_VOLUME/"
        ok "ChromaDB восстановлена в Docker volume"
    elif [ -d "$LOCAL_DATA" ]; then
        echo "Восстанавливаю ChromaDB → $LOCAL_DATA/chroma_db..."
        rm -rf "$LOCAL_DATA/chroma_db"
        cp -r "$src" "$LOCAL_DATA/chroma_db"
        ok "ChromaDB восстановлена локально"
    else
        warn "Не удалось найти целевую папку для ChromaDB"
    fi
}

# ── Восстановление Knowledge Graph ───────────────────────────────────────────

restore_graph() {
    local src="$BACKUP_DATA/graph.db"
    if [ ! -f "$src" ]; then
        warn "graph.db не найден в бэкапе — пропускаю"
        return
    fi

    if $DRY_RUN; then
        warn "[DRY-RUN] Бы восстановил graph.db из $src"
        return
    fi

    if [ -n "$GRAPH_VOLUME" ] && [ -d "$GRAPH_VOLUME" ]; then
        echo "Восстанавливаю graph.db → Docker volume..."
        cp "$src" "$GRAPH_VOLUME/graph.db"
        ok "graph.db восстановлен в Docker volume"
    elif [ -d "$LOCAL_DATA" ]; then
        echo "Восстанавливаю graph.db → $LOCAL_DATA/graph.db..."
        cp "$src" "$LOCAL_DATA/graph.db"
        ok "graph.db восстановлен локально"
    else
        warn "Не удалось найти целевую папку для graph.db"
    fi
}

restore_chroma
restore_graph

# ── Перезапуск ────────────────────────────────────────────────────────────────

if ! $DRY_RUN; then
    echo ""
    echo -n "Перезапустить backend? [Y/n]: "
    read -r RESTART
    if [[ ! "$RESTART" =~ ^[Nn]$ ]]; then
        docker compose start backend 2>/dev/null || docker compose up -d backend
        echo "Жду запуска..."
        sleep 10
        if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
            ok "Backend запущен и отвечает"
        else
            warn "Backend не отвечает. Проверь: docker compose logs backend"
        fi
    fi
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           Восстановление готово          ║"
echo "╚══════════════════════════════════════════╝"
