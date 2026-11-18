"""mailbridge — мини-сервер отправки кодов для deepmint.vpn.

Живёт на h1cloud (где SMTP не блокируется). Render-сервер зовёт его по HTTP:
    POST /send  {email: "...", code: "123456"}  -> 200 {ok:true}

Обязательные env (или дефолты):
    SMTP_APP_PASS  — пароль приложения Gmail (уже есть в проекте)
    MAILBRIDGE_KEY — секрет, который присылает Render (против спама)
"""
import json
import os
import smtplib
import socket
from email.header import Header
from email.mime.text import MIMEText

from flask import Flask, jsonify, request

app = Flask(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "bunseriy@gmail.com")
SMTP_APP_PASS = os.environ.get("SMTP_APP_PASS", "mcpzuicanobwsdsu")
KEY = os.environ.get("MAILBRIDGE_KEY", "deepmint-bridge-2026")


def _resolve_ipv4():
    """Берём A-запись, чтобы не спотыкаться на отсутствии IPv6."""
    try:
        infos = socket.getaddrinfo(SMTP_HOST, SMTP_PORT, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return infos[0][4][0]
    except OSError:
        pass
    return SMTP_HOST


def _send_mail(to_email, code):
    msg = MIMEText(
        f"Код подтверждения для входа в deepmint.vpn:\n\n{code}\n\n"
        "Никому не сообщайте этот код. Он действует 5 минут.",
        "plain", "utf-8",
    )
    msg["Subject"] = Header("Код входа — deepmint.vpn", "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    s = smtplib.SMTP(_resolve_ipv4(), SMTP_PORT, timeout=25)
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


@app.route("/health")
def health():
    return jsonify(ok=True)


@app.route("/send", methods=["POST"])
def send():
    if (request.headers.get("X-Mailbridge-Key") or "") != KEY:
        return jsonify(ok=False, error="bad key"), 403
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="bad email"), 400
    if not code:
        return jsonify(ok=False, error="empty code"), 400
    try:
        _send_mail(email, code)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
    return jsonify(ok=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8081"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, threaded=True)