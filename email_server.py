"""
Email-верификация для deepmint.vpn.

Запускается как отдельный Flask-сервер на localhost:<port>.
API:
  POST /api/email/send   {email}          -> 200 {ok:true, detail:"code sent"}
  POST /api/email/verify {email, code}    -> 200 {ok:true, email} | 401 {ok:false, error}
  GET  /api/health                         -> 200 {ok:true}

Коды хранятся в памяти, срок жизни 5 минут, лимит 5 запросов кода в час на адрес.
Секреты читаются из окружения:
  SMTP_USER, SMTP_APP_PASS (иначе берутся значения ниже для локального запуска).
"""
import json
import os
import random
import smtplib
import threading
import time
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path

from flask import Flask, jsonify, request

# CORS: разрешаем запросы откуда угодно (GitHub Pages, локальный file://, Telegram WebApp)
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "bunseriy@gmail.com")
SMTP_APP_PASS = os.environ.get("SMTP_APP_PASS", "mcpzuicanobwsdsu")
CODE_TTL = 300
RATE_LIMIT_HOUR = 5
STATE_FILE = Path(__file__).resolve().parent / "email_codes.json"
_codes = {}   # email -> {"code": str, "expires": ts, "sent": ts, "count": n}


def _load_state():
    global _codes
    try:
        if STATE_FILE.exists():
            _codes = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _codes = {}


def _save_state():
    try:
        STATE_FILE.write_text(json.dumps(_codes, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _send_email(to_email, code):
    msg = MIMEText(
        f"Код подтверждения для входа в deepmint.vpn:\n\n{code}\n\n"
        "Никому не сообщайте этот код. Он действует 5 минут.",
        "plain", "utf-8",
    )
    msg["Subject"] = Header("Код входа — deepmint.vpn", "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    try:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_APP_PASS)
        s.sendmail(SMTP_USER, [to_email], msg.as_string())
    finally:
        try:
            s.quit()
        except Exception:
            pass


@app.post("/api/email/send")
def send_code():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="Неверный email"), 400

    now = time.time()
    rec = _codes.get(email)
    if rec:
        # сброс лимита за час
        if now - rec.get("sent", 0) > 3600:
            rec["count"] = 0
        if rec.get("count", 0) >= RATE_LIMIT_HOUR:
            return jsonify(ok=False, error="Слишком много запросов. Попробуйте позже"), 429

    code = f"{random.randint(0, 999999):06d}"
    try:
        _send_email(email, code)
    except Exception as e:
        return jsonify(ok=False, error=f"Не удалось отправить письмо: {e}"), 500

    _codes[email] = {
        "code": code,
        "expires": now + CODE_TTL,
        "sent": now,
        "count": (rec.get("count", 0) if rec else 0) + 1,
    }
    _save_state()
    return jsonify(ok=True, detail="code sent")


@app.post("/api/email/verify")
def verify_code():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not email or not code:
        return jsonify(ok=False, error="Пустые поля"), 400

    rec = _codes.get(email)
    if not rec:
        return jsonify(ok=False, error="Код не запрашивался"), 401
    if time.time() > rec.get("expires", 0):
        _codes.pop(email, None)
        _save_state()
        return jsonify(ok=False, error="Код истёк"), 401
    if rec["code"] != code:
        return jsonify(ok=False, error="Неверный код"), 401

    _codes.pop(email, None)
    _save_state()
    return jsonify(ok=True, email=email)


SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "bunseriy@gmail.com")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "support1234")
CHAT_FILE = Path(__file__).resolve().parent / "chat_messages.json"
_msg_lock = threading.Lock()


def _load_messages():
    try:
        if CHAT_FILE.exists():
            data = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def _save_messages(msgs):
    try:
        CHAT_FILE.write_text(json.dumps(msgs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _strip_role(text, role):
    """Убираем служебный префикс __support__/__user__, если он есть."""
    prefix = "__" + role + "__"
    if text.startswith(prefix):
        return text[len(prefix):], True
    return text, False


@app.post("/api/support")
def support_message():
    """Добавляет сообщение в общий чат поддержки. role: user|admin."""
    data = request.get_json(silent=True) or {}
    raw = (data.get("message") or "").strip()
    role = (data.get("role") or "user").strip()
    name = (data.get("name") or "Пользователь").strip()
    if role == "admin":
        key = (data.get("key") or "").strip()
        if not key or key != ADMIN_KEY:
            return jsonify(ok=False, error="Нет доступа"), 403
    if not raw:
        return jsonify(ok=False, error="Пустое сообщение"), 400
    msgs = _load_messages()
    msgs.append({
        "id": len(msgs) + 1,
        "role": role,
        "name": name,
        "text": raw,
        "ts": time.time(),
    })
    _save_messages(msgs)
    return jsonify(ok=True, detail="message saved")


@app.get("/api/support")
def support_list():
    """Возвращает переписку. С админ-ключом — все сообщения с ролями."""
    key = (request.args.get("key") or "").strip()
    msgs = _load_messages()
    if key and key == ADMIN_KEY:
        return jsonify(ok=True, messages=msgs)
    # Пользователю — без ролей (для простоты показываем последние 50)
    pub = [{"text": m["text"], "role": m["role"]} for m in msgs[-50:]]
    return jsonify(ok=True, messages=pub)


@app.get("/api/health")
def health():
    return jsonify(ok=True)


_load_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("EMAIL_SERVER_PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)