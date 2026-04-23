#!/usr/bin/env bash
# backup.sh — бэкап ChromaDB и Knowledge Graph на облако / локальную машину
# Запуск: ./scripts/backup.sh
# Cron на VPS: 0 3 * * * /home/deploy/rag-dev-assistant/scripts/backup.sh

set -euo pipefail

BACKUP_DIR="/tmp/rag-backup-$(date +%Y%m%d_%H%M%S)"
ARCHIVE="${BACKUP_DIR}.tar.gz"
DATA_DIR="${DATA_DIR:-/home/deploy/rag-dev-assistant/data}"

echo "📦 RAG Dev Assistant — бэкап $(date '+%d.%m.%Y %H:%M')"
echo "   Источник: $DATA_DIR"

# Создаём папку для бэкапа
mkdir -p "$BACKUP_DIR"

# Копируем данные из Docker volumes (если они есть на диске)
if [ -d "$DATA_DIR" ]; then
    cp -r "$DATA_DIR" "$BACKUP_DIR/data"
    echo "   ✅ Данные скопированы"
else
    echo "   ⚠️  Папка данных не найдена: $DATA_DIR"
    echo "   Пробуем через docker cp..."
    docker cp rag-dev-assistant-backend-1:/app/data "$BACKUP_DIR/data" 2>/dev/null || \
        echo "   ❌ docker cp тоже не сработал"
fi

# Создаём архив
tar -czf "$ARCHIVE" -C "$(dirname "$BACKUP_DIR")" "$(basename "$BACKUP_DIR")"
SIZE=$(du -sh "$ARCHIVE" | cut -f1)
echo "   📁 Архив: $ARCHIVE ($SIZE)"

# Проверка целостности архива
echo -n "   Проверяю целостность... "
if tar -tzf "$ARCHIVE" > /dev/null 2>&1; then
    echo "✅ OK"
else
    echo "❌ АРХИВ ПОВРЕЖДЁН!"
    rm -f "$ARCHIVE"
    err "Архив повреждён и удалён. Проверь свободное место на диске."
fi

# Очистка временной папки
rm -rf "$BACKUP_DIR"

# ── Отправка на облако ──────────────────────────────────────────────────────
# Настройка через переменные окружения (добавь в .env или crontab):
#   BACKUP_RSYNC_TARGET="backup-user@backup-server:/backups/rag/"
#   BACKUP_RCLONE_TARGET="gdrive:backups/rag/"
#   BACKUP_SCP_TARGET="user@your-mac:~/Backups/rag/"

if [ -n "${BACKUP_RSYNC_TARGET:-}" ]; then
    echo "   Отправляю rsync → $BACKUP_RSYNC_TARGET"
    if rsync -az --timeout=60 "$ARCHIVE" "$BACKUP_RSYNC_TARGET" 2>/dev/null; then
        ok "rsync успешен"
    else
        warn "rsync упал (проверь SSH ключ и адрес)"
    fi
fi

if [ -n "${BACKUP_RCLONE_TARGET:-}" ]; then
    echo "   Отправляю rclone → $BACKUP_RCLONE_TARGET"
    if command -v rclone &>/dev/null; then
        if rclone copy "$ARCHIVE" "$BACKUP_RCLONE_TARGET" --log-level ERROR 2>/dev/null; then
            ok "rclone успешен"
        else
            warn "rclone упал (проверь конфиг: rclone config)"
        fi
    else
        warn "rclone не установлен. Установи: https://rclone.org/install/"
    fi
fi

if [ -n "${BACKUP_SCP_TARGET:-}" ]; then
    echo "   Отправляю scp → $BACKUP_SCP_TARGET"
    if scp -o ConnectTimeout=10 "$ARCHIVE" "$BACKUP_SCP_TARGET" 2>/dev/null; then
        ok "scp успешен"
    else
        warn "scp упал (проверь SSH ключ и адрес)"
    fi
fi

# ── Локальное хранение (оставляем последние 7 бэкапов) ─────────────────────
BACKUP_STORE="${BACKUP_STORE:-/home/deploy/backups/rag}"
mkdir -p "$BACKUP_STORE"
cp "$ARCHIVE" "$BACKUP_STORE/"

# Удаляем старые бэкапы
find "$BACKUP_STORE" -name "*.tar.gz" -mtime +7 -delete
KEPT=$(find "$BACKUP_STORE" -name "*.tar.gz" | wc -l | tr -d ' ')
echo "   🗂  Хранится бэкапов: $KEPT"

# Удаляем архив из /tmp
rm -f "$ARCHIVE"

# ── Уведомление в Telegram ─────────────────────────────────────────────────
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${ADMIN_TELEGRAM_ID:-}" ]; then
    curl -s -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${ADMIN_TELEGRAM_ID}" \
        -d "text=💾 RAG бэкап готов: ${SIZE} ($(date '+%d.%m %H:%M'))" \
        > /dev/null
fi

echo "✅ Бэкап завершён"
