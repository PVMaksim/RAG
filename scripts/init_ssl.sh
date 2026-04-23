#!/usr/bin/env bash
# init_ssl.sh — первичная выдача SSL сертификата Let's Encrypt
# Запуск ОДИН РАЗ на VPS после первого деплоя:
#   DOMAIN=rag.yourdomain.com EMAIL=you@email.com ./scripts/init_ssl.sh

set -euo pipefail

DOMAIN="${DOMAIN:?Укажи DOMAIN=rag.yourdomain.com}"
EMAIL="${EMAIL:?Укажи EMAIL=you@email.com}"

echo "🔐 Получаю SSL сертификат для $DOMAIN..."

# Убеждаемся что nginx запущен (нужен для ACME challenge)
docker-compose up -d nginx

# Запрашиваем сертификат через certbot
docker run --rm \
    -v "$(pwd)/certbot_data:/etc/letsencrypt" \
    -v "$(pwd)/certbot_www:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

echo "✅ Сертификат получен!"
echo ""
echo "Теперь замени nginx.conf на nginx.prod.conf и перезапусти:"
echo "  cp docker/nginx/nginx.prod.conf docker/nginx/nginx.conf"
echo "  docker-compose restart nginx"
