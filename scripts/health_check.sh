#!/usr/bin/env bash
# health_check.sh — быстрая проверка всех сервисов
# Запуск: ./scripts/health_check.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
PASS=0; FAIL=0

check() {
    local name="$1" url="$2"
    if curl -sf --max-time 5 "$url" > /dev/null 2>&1; then
        echo "  ✅ $name"
        ((PASS++))
    else
        echo "  ❌ $name ($url)"
        ((FAIL++))
    fi
}

echo "🔍 RAG Dev Assistant — Health Check ($(date '+%H:%M:%S'))"
echo "   Base URL: $BASE_URL"
echo ""

check "nginx"         "$BASE_URL/"
check "backend /health" "$BASE_URL/health"
check "frontend"      "$BASE_URL/"
check "MCP server"    "http://localhost:27183/mcp/sse"

echo ""
echo "Docker контейнеры:"
docker-compose ps 2>/dev/null || echo "  (docker-compose недоступен)"

echo ""
if [ $FAIL -eq 0 ]; then
    echo "✅ Все проверки пройдены ($PASS/$((PASS+FAIL)))"
else
    echo "❌ Проблемы: $FAIL из $((PASS+FAIL)) проверок провалились"
    exit 1
fi
