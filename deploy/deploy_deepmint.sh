#!/usr/bin/env bash
# Установка бэкенда deepmint.vpn на VPS (Debian/Ubuntu, root):
#   Flask-бэкенд (платёж Platega + коды по почте) + Caddy (HTTPS через DuckDNS)
# Запуск одной командой (поддомен + base64-содержимое .env):
#   curl -fsSL https://raw.githubusercontent.com/Coderion31/deepmint-vpn-app/main/deploy/deploy_deepmint.sh | bash -s deepmain '<BASE64_ENV>'
set -euo pipefail

SUBDOMAIN="${1:-deepmain}"
ENV_B64="${2:-}"

if [ "$(id -u)" != "0" ]; then
  echo "ОШИБКА: запустите от root (sudo -i или пользователь root)"
  exit 1
fi

echo "==> 1/6 Обновляю систему"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-pip curl unzip ca-certificates gnupg apt-transport-https

echo "==> 2/6 Python-зависимости"
pip3 install --break-system-packages flask flask_cors 2>/dev/null || pip3 install flask flask_cors

echo "==> 3/6 Caddy (официальный репозиторий)"
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -y
  apt-get install -y caddy
fi

echo "==> 4/6 Код бэкенда"
mkdir -p /opt/deepmint
cd /opt/deepmint
if [ ! -d repo/.git ]; then
  git clone https://github.com/Coderion31/deepmint-vpn-app.git repo
else
  git -C repo pull --ff-only || true
fi

echo "==> 5/6 Переменные окружения"
if [ -n "$ENV_B64" ]; then
  echo "$ENV_B64" | base64 -d > /opt/deepmint/.env
  chmod 600 /opt/deepmint/.env
elif [ ! -f /opt/deepmint/.env ]; then
  cp /opt/deepmint/repo/.env.template /opt/deepmint/.env
  chmod 600 /opt/deepmint/.env
  echo "ВНИМАНИЕ: /opt/deepmint/.env создан из шаблона — заполните его реальными значениями"
fi
# безопасный дефолт: слушаем только localhost (наружу отдаёт Caddy)
if grep -q '^HOST=' /opt/deepmint/.env; then
  sed -i 's/^HOST=.*/HOST=127.0.0.1/' /opt/deepmint/.env
fi

echo "==> 6/6 Caddy + systemd"
cat > /etc/caddy/Caddyfile <<CADDY
${SUBDOMAIN}.duckdns.org {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
}
CADDY

cat > /etc/systemd/system/deepmint-backend.service <<SVC
[Unit]
Description=deepmint.vpn backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/deepmint/repo/server
EnvironmentFile=/opt/deepmint/.env
ExecStart=/usr/bin/python3 /opt/deepmint/repo/server/email_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable caddy >/dev/null 2>&1 || true
systemctl restart caddy
systemctl enable deepmint-backend
systemctl restart deepmint-backend

echo ""
echo "==> ГОТОВО. Проверка:"
sleep 4
echo "-- локально (http://127.0.0.1:8080/api/health):"
curl -s http://127.0.0.1:8080/api/health || echo "   (не отвечает — смотрите: journalctl -u deepmint-backend -n 50)"
echo ""
echo "-- снаружи (https://${SUBDOMAIN}.duckdns.org/api/health):"
curl -s "https://${SUBDOMAIN}.duckdns.org/api/health" || echo "   (сертификат может выпускаться 1-2 мин, повторите)"
echo ""