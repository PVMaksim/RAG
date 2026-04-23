# MEMORY.md — RAG Dev Assistant

## Последняя сессия: 2026-04-20

### Сделано

**Production-ready улучшения:**
- `/health`: disk space monitoring (ok/warning/critical), Telegram alert при critical
- `routers/settings.py`: `GET /api/settings/` (без секретов) + `PUT /api/settings/` (runtime)
- `nginx.conf`: `limit_req_zone` двухуровневая защита (search 20/min, upload 5/min, api 60/min)
- `ruff.toml`: конфиг линтера, обновлён CI с `ruff format --check`
- `.pre-commit-config.yaml`: ruff lint+format + trailing whitespace + YAML/JSON check + tsc

**Новые фичи:**
- `query_engine.py`: `patch_stream()` теперь тоже поддерживает history (последние 4 сообщения)
- `docs/api-reference.md`: полная документация всех эндпоинтов
- `mac-app/OnboardingView.swift`: 3-шаговый wizard первого запуска (welcome → configure → done)
- SSH secret mount документирован в `docker-compose.dev.yml` и `.env.example`
- `webhook.py`: авто-клонирование если проект не найден локально
- `backup.sh`: облачная отправка через `BACKUP_RSYNC/RCLONE/SCP_TARGET` env vars
- `api.ts`: deprecated функции удалены, `makeGitPullFetcher()` добавлен
- `graph/page.tsx`: экспорт в JSON с датой в имени файла
- `search/page.tsx`: Escape для отмены/сброса, copy path у чанков
- `settings/page.tsx`: GitHub Webhook секция с URL и инструкцией

### Phase 2 — деплой на VPS

```bash
# Подготовка VPS (Ubuntu 22.04, 4GB RAM)
adduser deploy && usermod -aG docker deploy

# GitHub Secrets: VPS_HOST, SSH_PRIVATE_KEY, DOMAIN,
#                 TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID

# Деплой
git push origin main  # → auto-deploy через CI/CD

# SSL
DOMAIN=rag.yourdomain.com EMAIL=you@email.com ./scripts/init_ssl.sh

# .env на VPS
MCP_API_KEY=$(openssl rand -hex 32)
WEBHOOK_SECRET=$(openssl rand -hex 32)
BACKUP_RCLONE_TARGET=gdrive:backups/rag/   # или rsync/scp

# GitHub Webhook
# URL: https://rag.yourdomain.com/api/webhook/github
# Secret: $WEBHOOK_SECRET

# Cron бэкап
echo "0 3 * * * /home/deploy/rag-dev-assistant/scripts/backup.sh" | crontab -
```

### Phase 3 — продуктовые

- [ ] Multi-user: JWT auth + ChromaDB namespace isolation
- [ ] Windows: Electron wrapper (WebView2 + Next.js)
- [ ] MCP rate limiter → Redis backend
- [ ] Prometheus + Grafana dashboard (уже есть `/api/metrics`)
- [ ] `routers/metrics.py`: persist в SQLite вместо in-memory

## Известный технический долг

| Файл | Долг | Приоритет |
|------|------|-----------|
| `routers/metrics.py` | In-memory — сбрасывается при рестарте | Средний (Phase 3) |
| `mcp-server` | Rate limiter in-memory | Низкий (Phase 3) |

## Принятые решения (полный список)

| Решение | Обоснование |
|---------|-------------|
| WKWebView + SwiftUI | Один UI для Mac/Win/Linux |
| MCP HTTP transport | Работает локально и через VPS |
| Собственный GraphRAG | Меньше зависимостей, проще в Docker |
| Embedding LRU cache | Thread-safe через GIL |
| SQLite WAL | Читатели не блокируются при записи |
| Semaphore(3) для Claude API | Безопасный предел для tier-1 |
| safe_sse_stream() | Клиент всегда получает {type: error} |
| asyncio.Lock на проект | Нет race condition при scan |
| slowapi + nginx limits | Двухуровневая защита от DDoS |
| BackgroundTasks для webhook | GitHub получает 200 немедленно |
| ZIP slip через resolve() | Path traversal невозможен |
| HMAC compare_digest | Защита от timing attacks |
| BACKUP_*_TARGET через env | Не хардкодить цели бэкапа |
| Disk check в /health | Раннее обнаружение нехватки места |
| Settings GET без секретов | API ключи никогда не попадают в ответ |
