#!/usr/bin/env bash
# Установка бэкенда deepmint.vpn на h1cloud (Ubuntu): Flask-бэкенд + Caddy (HTTPS)
# Запуск от root:  bash /root/deploy_deepmint.sh
set -euo pipefail

SUBDOMAIN="${1:-deepmain}"          # имя поддомена duckdns.org
PUBLIC_IP="${2:-179.254.115.142}"   # IP сервера

echo "==> Обновляю систему и ставлю зависимости"
apt-get update -y
apt-get install -y python3 python3-pip caddy curl unzip

echo "==> Кладу бэкенд в /opt/deepmint"
mkdir -p /opt/deepmint
cd /opt/deepmint
if [ ! -d repo/.git ]; then
  git clone https://github.com/Coderion31/deepmint-vpn-app.git repo
else
  git -C repo pull --ff-only || true
fi

echo "==> Устанавливаю python-зависимости"
pip3 install --break-system-packages flask flask_cors gunicorn 2>/dev/null || pip3 install flask flask_cors gunicorn

echo "==> Настраиваю .env (создайте/отредактируйте /opt/deepmint/.env с секретами из Render)"
if [ ! -f /opt/deepmint/.env ]; then
  cp /opt/deepmint/repo/.env.template /opt/deepmint/.env 2>/dev/null || true
  echo "  ВАЖНО: заполните /opt/deepmint/.env значениями из Render и запустите скрипт снова"
  exit 0
fi

echo "==> Caddy: бесплатный HTTPS через DuckDNS"
cat > /etc/caddy/Caddyfile <<CADDY
${SUBDOMAIN}.duckdns.org {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
CADDY
systemctl enable caddy
systemctl restart caddy

echo "==> Служба бэкенда (автозапуск, перезапуск при сбоях)"
cat > /etc/systemd/system/deepmint-backend.service <<SVC
[Unit]
Description=deepmint.vpn backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/deepmint
EnvironmentFile=/opt/deepmint/.env
ExecStart=/usr/bin/python3 /opt/deepmint/repo/server/email_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC
systemctl daemon-reload
systemctl enable deepmint-backend
systemctl restart deepmint-backend

echo "==> Готово. Проверка:"
sleep 3
echo "-- бэкенд по http://127.0.0.1:8080/api/health:"
curl -s http://127.0.0.1:8080/api/health || echo "  (не отвечает — смотрите journalctl -u deepmint-backend)"
echo ""
echo "-- HTTPS снаружи: https://${SUBDOMAIN}.duckdns.org/api/health"
echo "Дождитесь, пока DNS DuckDNS укажет на ${PUBLIC_IP}, и сертификат выпустится автоматически (1-2 мин)."