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
import uuid
import urllib.request
import urllib.error
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

PLATEGA_BASE = "https://app.platega.io"
PLATEGA_MERCHANT_ID = os.environ.get("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.environ.get("PLATEGA_SECRET", "")
PLATEGA_RETURN_URL = os.environ.get("PLATEGA_RETURN_URL", "https://coderion31.github.io/deepmint-vpn-app/")

PLANS = {
    "trial": {"label": "Пробная — 72 часа", "price": "0.00", "days": "trial"},
    "30": {"label": "30 дней", "price": "199.00"},
    "90": {"label": "90 дней", "price": "549.00"},
    "180": {"label": "180 дней", "price": "999.00"},
    "360": {"label": "360 дней", "price": "1799.00"},
}


def _platega_request(method, path, body=None, idem=None):
    """Выполняет запрос к API Platega. Возвращает (status, json)."""
    url = PLATEGA_BASE + path
    headers = {
        "X-MerchantId": PLATEGA_MERCHANT_ID,
        "X-Secret": PLATEGA_SECRET,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
        if idem:
            headers["Idempotency-Key"] = idem
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw) if raw else {}
        except ValueError:
            return e.code, {"raw": raw}
    except urllib.error.URLError as e:
        return 0, {"error": str(e.reason)}


@app.post("/api/paylink")
def create_paylink():
    """Создаёт одноразовую платёжную ссылку Platega для выбранного тарифа.
    Тело: {plan: "30", email: "user@mail.ru"}"""
    data = request.get_json(silent=True) or {}
    plan_key = (data.get("plan") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if plan_key not in PLANS:
        return jsonify(ok=False, error="Неизвестный тариф"), 400
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="Укажите корректную почту"), 400
    plan = PLANS[plan_key]
    if plan["price"] == "0.00":
        return jsonify(ok=True, trial=True, label=plan["label"])
    body = {
        "usageMode": 1,
        "paymentMode": 0,
        "currency": "RUB",
        "minAmount": plan["price"],
        "maxAmount": plan["price"],
        "name": plan["label"],
        "description": f"deepmint.vpn — {plan['label']}",
        "orderId": f"DM-{int(time.time())}",
        "payload": email,
        "return": PLATEGA_RETURN_URL,
        "failedUrl": PLATEGA_RETURN_URL,
    }
    status, resp = _platega_request(
        "POST", "/v2/payment-links", body=body, idem=f"dm-{uuid.uuid4()}"
    )
    if status in (200, 201):
        return jsonify(ok=True, url=resp.get("url"), id=resp.get("id"), label=plan["label"], price=plan["price"])
    return jsonify(
        ok=False,
        error=resp.get("message") or resp.get("raw") or f"Ошибка Platega ({status})",
        code=resp.get("code"),
    ), 502 if status else 503


def _load_messages():
    """Формат: {ticket_id: [ {role, name, text, ts}, ... ]}"""
    try:
        if CHAT_FILE.exists():
            data = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _save_messages(msgs):
    try:
        CHAT_FILE.write_text(json.dumps(msgs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _new_ticket_id(tickets):
    """Числовой id следующего тикета."""
    max_id = 0
    for tid in tickets.keys():
        try:
            n = int(tid)
            if n > max_id:
                max_id = n
        except (TypeError, ValueError):
            pass
    return str(max_id + 1)


@app.post("/api/support")
def support_message():
    """Добавляет сообщение в тикет. Пользователь: ticket_id (создаётся при первом сообщении).
    Поддержка: key + ticket_id."""
    data = request.get_json(silent=True) or {}
    raw = (data.get("message") or "").strip()
    role = (data.get("role") or "user").strip()
    name = (data.get("name") or "Пользователь").strip()
    ticket_id = (data.get("ticket_id") or "").strip()
    if role == "admin":
        key = (data.get("key") or "").strip()
        if not key or key != ADMIN_KEY:
            return jsonify(ok=False, error="Нет доступа"), 403
    if not raw:
        return jsonify(ok=False, error="Пустое сообщение"), 400
    tickets = _load_messages()
    if not ticket_id or ticket_id not in tickets:
        ticket_id = _new_ticket_id(tickets)
    msgs = tickets.setdefault(ticket_id, [])
    msgs.append({
        "role": role,
        "name": name,
        "text": raw,
        "ts": time.time(),
    })
    _save_messages(tickets)
    return jsonify(ok=True, detail="message saved", ticket_id=ticket_id)


@app.get("/api/support")
def support_list():
    """Без ключа: (ticket_id = свой чат). С админ-ключом: список тикетов."""
    key = (request.args.get("key") or "").strip()
    ticket_id = (request.args.get("ticket_id") or "").strip()
    tickets = _load_messages()
    if key and key == ADMIN_KEY:
        # Для поддержки: список тикетов с последним сообщением и числом сообщений
        summary = []
        for tid, msgs in tickets.items():
            last = msgs[-1] if msgs else {}
            summary.append({
                "ticket_id": tid,
                "name": msgs[0].get("name", "") if msgs else "",
                "last": last.get("text", ""),
                "count": len(msgs),
                "ts": last.get("ts", 0),
            })
        summary.sort(key=lambda t: t["ts"], reverse=True)
        return jsonify(ok=True, tickets=summary)
    if ticket_id:
        return jsonify(ok=True, messages=tickets.get(ticket_id, []), ticket_id=ticket_id)
    return jsonify(ok=True, messages=[], ticket_id="")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


_load_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("EMAIL_SERVER_PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)