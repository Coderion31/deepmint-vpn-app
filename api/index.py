"""Vercel serverless-обёртка для Flask-бэкенда deepmint.vpn."""
import os
import sys

# Корень репозитория — на Vercel это текущая папка функции + ../.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # корень репо
_SERVER = os.path.join(_ROOT, "server")
if _SERVER not in sys.path:
    sys.path.insert(0, _SERVER)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# DATA_DIR должен указывать на writable-папку serverless (задано в vercel.json,
# но продублируем на случай ручного запуска).
os.environ.setdefault("DATA_DIR", "/tmp")

from email_server import app  # noqa: E402

# Vercel Python-функции ожидают объект с атрибутом handler/app.
handler = app