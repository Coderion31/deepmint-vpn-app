"""
Email-РІРµСЂРёС„РёРєР°С†РёСЏ РґР»СЏ deepmint.vpn.

Р—Р°РїСѓСЃРєР°РµС‚СЃСЏ РєР°Рє РѕС‚РґРµР»СЊРЅС‹Р№ Flask-СЃРµСЂРІРµСЂ РЅР° localhost:<port>.
API:
  POST /api/email/send   {email}          -> 200 {ok:true, detail:"code sent"}
  POST /api/email/verify {email, code}    -> 200 {ok:true, email} | 401 {ok:false, error}
  GET  /api/health                         -> 200 {ok:true}

РљРѕРґС‹ С…СЂР°РЅСЏС‚СЃСЏ РІ РїР°РјСЏС‚Рё, СЃСЂРѕРє Р¶РёР·РЅРё 5 РјРёРЅСѓС‚, Р»РёРјРёС‚ 5 Р·Р°РїСЂРѕСЃРѕРІ РєРѕРґР° РІ С‡Р°СЃ РЅР° Р°РґСЂРµСЃ.
РЎРµРєСЂРµС‚С‹ С‡РёС‚Р°СЋС‚СЃСЏ РёР· РѕРєСЂСѓР¶РµРЅРёСЏ:
  SMTP_USER, SMTP_APP_PASS (РёРЅР°С‡Рµ Р±РµСЂСѓС‚СЃСЏ Р·РЅР°С‡РµРЅРёСЏ РЅРёР¶Рµ РґР»СЏ Р»РѕРєР°Р»СЊРЅРѕРіРѕ Р·Р°РїСѓСЃРєР°).
"""
import json
import logging
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

log = logging.getLogger("deepmint-server")

# CORS: СЂР°Р·СЂРµС€Р°РµРј Р·Р°РїСЂРѕСЃС‹ РѕС‚РєСѓРґР° СѓРіРѕРґРЅРѕ (GitHub Pages, Р»РѕРєР°Р»СЊРЅС‹Р№ file://, Telegram WebApp)
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "bunseriy@gmail.com")
SMTP_APP_PASS = os.environ.get("SMTP_APP_PASS", "mcpzuicanobwsdsu")
MAILBRIDGE_URL = os.environ.get("MAILBRIDGE_URL", "").strip().rstrip("/")
MAILBRIDGE_KEY = os.environ.get("MAILBRIDGE_KEY", "deepmint-bridge-2026")


def _smtp_host_ipv4():
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ IPv4-Р°РґСЂРµСЃ SMTP-С…РѕСЃС‚Р° (РЅР° С…РѕСЃС‚Р°С… Р±РµР· IPv6 avoid СЂРµР·РѕР»РІР° РІ AAAA)."""
    import socket
    try:
        infos = socket.getaddrinfo(SMTP_HOST, SMTP_PORT, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return infos[0][4][0]
    except OSError:
        pass
    return SMTP_HOST


def _send_email(to_email, code):
    """РћС‚РїСЂР°РІР»СЏРµС‚ РєРѕРґ. Р•СЃР»Рё Р·Р°РґР°РЅ MAILBRIDGE_URL (РїРѕС‡С‚РѕРІС‹Р№ СЂРµР»РµР№ РЅР° h1cloud) вЂ”
    С€Р»С‘Рј С‡РµСЂРµР· РЅРµРіРѕ, РёРЅР°С‡Рµ РЅР°РїСЂСЏРјСѓСЋ РїРѕ SMTP."""
    if MAILBRIDGE_URL:
        _send_email_via_bridge(to_email, code)
    else:
        _send_email_smtp(to_email, code)


def _send_email_via_bridge(to_email, code):
    body = json.dumps({"email": to_email, "code": code}).encode("utf-8")
    req = urllib.request.Request(
        MAILBRIDGE_URL + "/send",
        data=body,
        headers={"Content-Type": "application/json", "X-Mailbridge-Key": MAILBRIDGE_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            if resp.status == 200:
                return
            raise RuntimeError(f"bridge HTTP {resp.status}: {raw}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"bridge HTTP {e.code}: {raw}") from e


def _send_email_smtp(to_email, code):
    msg = MIMEText(
        f"РљРѕРґ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РґР»СЏ РІС…РѕРґР° РІ deepmint.vpn:\n\n{code}\n\n"
        "РќРёРєРѕРјСѓ РЅРµ СЃРѕРѕР±С‰Р°Р№С‚Рµ СЌС‚РѕС‚ РєРѕРґ. РћРЅ РґРµР№СЃС‚РІСѓРµС‚ 5 РјРёРЅСѓС‚.",
        "plain", "utf-8",
    )
    msg["Subject"] = Header("РљРѕРґ РІС…РѕРґР° вЂ” deepmint.vpn", "utf-8")
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    s = smtplib.SMTP(_smtp_host_ipv4(), SMTP_PORT, timeout=30)
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
RATE_LIMIT_HOUR = 5
# РљР°С‚Р°Р»РѕРі РґР»СЏ runtime-С…СЂР°РЅРёР»РёС‰ (email_codes/chat/payments/trial).
# РќР° Vercel С„Р°Р№Р»РѕРІР°СЏ СЃРёСЃС‚РµРјР° serverless read-only РєСЂРѕРјРµ /tmp вЂ” РїРѕСЌС‚РѕРјСѓ
# DATA_DIR РїРµСЂРµРѕРїСЂРµРґРµР»СЏРµС‚СЃСЏ С‡РµСЂРµР· env (vercel.json: DATA_DIR=/tmp).
DATA_DIR = Path(os.environ.get("DATA_DIR", "")).expanduser() if os.environ.get("DATA_DIR") else Path(__file__).resolve().parent
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
def _data_file(name):
    return DATA_DIR / name
STATE_FILE = _data_file("email_codes.json")
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


@app.post("/api/email/send")
def send_code():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="РќРµРІРµСЂРЅС‹Р№ email"), 400

    now = time.time()
    rec = _codes.get(email)
    if rec:
        # СЃР±СЂРѕСЃ Р»РёРјРёС‚Р° Р·Р° С‡Р°СЃ
        if now - rec.get("sent", 0) > 3600:
            rec["count"] = 0
        if rec.get("count", 0) >= RATE_LIMIT_HOUR:
            return jsonify(ok=False, error="РЎР»РёС€РєРѕРј РјРЅРѕРіРѕ Р·Р°РїСЂРѕСЃРѕРІ. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ"), 429

    code = f"{random.randint(0, 999999):06d}"
    try:
        _send_email(email, code)
    except Exception as e:
        return jsonify(ok=False, error=f"РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РїСЂР°РІРёС‚СЊ РїРёСЃСЊРјРѕ: {e}"), 500

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
        return jsonify(ok=False, error="РџСѓСЃС‚С‹Рµ РїРѕР»СЏ"), 400

    rec = _codes.get(email)
    if not rec:
        return jsonify(ok=False, error="РљРѕРґ РЅРµ Р·Р°РїСЂР°С€РёРІР°Р»СЃСЏ"), 401
    if time.time() > rec.get("expires", 0):
        _codes.pop(email, None)
        _save_state()
        return jsonify(ok=False, error="РљРѕРґ РёСЃС‚С‘Рє"), 401
    if rec["code"] != code:
        return jsonify(ok=False, error="РќРµРІРµСЂРЅС‹Р№ РєРѕРґ"), 401

    _codes.pop(email, None)
    _save_state()
    return jsonify(ok=True, email=email)


SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "bunseriy@gmail.com")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "support1234")
CHAT_FILE = _data_file("chat_messages.json")
_msg_lock = threading.Lock()

PLATEGA_BASE = "https://app.platega.io"
PLATEGA_MERCHANT_ID = os.environ.get("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = os.environ.get("PLATEGA_SECRET", "")
PLATEGA_RETURN_URL = os.environ.get("PLATEGA_RETURN_URL", "https://coderion31.github.io/deepmint-vpn-app/")

PLANS = {
    "trial": {"label": "РџСЂРѕР±РЅР°СЏ вЂ” 72 С‡Р°СЃР°", "price": "0.00", "days": 3},
    "30": {"label": "30 РґРЅРµР№", "price": "199.00", "days": 30},
    "90": {"label": "90 РґРЅРµР№", "price": "549.00", "days": 90},
    "180": {"label": "180 РґРЅРµР№", "price": "999.00", "days": 180},
    "360": {"label": "360 РґРЅРµР№", "price": "1799.00", "days": 360},
}

# РћРґРёРЅ email вЂ” РѕРґРЅР° РїСЂРѕР±РЅР°СЏ РїРѕРґРїРёСЃРєР°. РҐСЂР°РЅРёРј С„Р°РєС‚ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ.
TRIAL_FILE = _data_file("trial_used.json")
_trial_lock = threading.Lock()


def _load_trial_used():
    try:
        if TRIAL_FILE.exists():
            data = json.loads(TRIAL_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _save_trial_used(data):
    try:
        TRIAL_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

# VPN-РїР°РЅРµР»Рё (H1/VLESS). РўРѕРєРµРЅС‹ РІ env: VPN_NODE_<LOC>_URL / VPN_NODE_<LOC>_TOKEN.
VPN_NODES = []
_VPN_ENV = {
    "DE": ("VPN_NODE_DE_URL", "VPN_NODE_DE_TOKEN"),
    "PL": ("VPN_NODE_PL_URL", "VPN_NODE_PL_TOKEN"),
    "EE": ("VPN_NODE_EE_URL", "VPN_NODE_EE_TOKEN"),
    "ES": ("VPN_NODE_ES_URL", "VPN_NODE_ES_TOKEN"),
    "IL": ("VPN_NODE_IL_URL", "VPN_NODE_IL_TOKEN"),
}
for _loc, (_url_env, _tok_env) in _VPN_ENV.items():
    _u = os.environ.get(_url_env, "").strip().rstrip("/")
    _t = os.environ.get(_tok_env, "").strip()
    if _u and _t:
        VPN_NODES.append({"loc": _loc, "base": _u, "token": _t})
log.info("VPN nodes configured: %s", ", ".join(n["loc"] for n in VPN_NODES) or "(none)")


def _smart_hash(s):
    """РљРѕСЂРѕС‚РєРёР№ СЃС‚Р°Р±РёР»СЊРЅС‹Р№ id РёР· СЃС‚СЂРѕРєРё (Р±РµР· РєРѕР»Р»РёР·РёР№ РґР»СЏ РёРјС‘РЅ РєР»РёРµРЅС‚РѕРІ)."""
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return format(h, "x")


def _vpn_req(node, method, path, body=None):
    """HTTP-Р·Р°РїСЂРѕСЃ Рє РїР°РЅРµР»Рё H1/VLESS. Р’РѕР·РІСЂР°С‰Р°РµС‚ (status, json)."""
    url = node["base"] + path
    headers = {"Authorization": f"Bearer {node['token']}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
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


def _ensure_vpn_client(email, days):
    """РЎРѕР·РґР°С‘С‚ РёР»Рё РїСЂРѕРґР»РµРІР°РµС‚ VPN-РґРѕСЃС‚СѓРї РґР»СЏ email РЅР° РІСЃРµС… РїР°РЅРµР»СЏС….
    Р’РѕР·РІСЂР°С‰Р°РµС‚ (ok, РїРѕРґСЂРѕР±РЅРѕСЃС‚Рё РїРѕ Р»РѕРєР°С†РёСЏРј)."""
    name = "vpn-" + _smart_hash(email)
    return _ensure_vpn_client_name(name, email, days)


def _vpn_alive(node, timeout=3):
    """Быстрая проверка доступности панели TCP:443, чтобы не висеть
    на мёртвых нодах по таймауту HTTP. Возвращает bool."""
    import socket as _s
    host = (node.get("base") or "").split("//")[-1].split("/")[0]
    if not host:
        return False
    try:
        with _s.create_connection((host, 443), timeout=timeout):
            return True
    except OSError:
        return False


def _ensure_vpn_client_name(name, title, days):
    """Создаёт или продлевает клиента NAME (title) на всех панелях.
    Возвращает (ok, подробности по локациям)."""
    from concurrent.futures import ThreadPoolExecutor

    def ensure_one(node):
        loc = node["loc"]
        now = int(time.time())
        status, data = _vpn_req(node, "GET", f"/api/clients/{name}")
        if status == 200 and data.get("client"):
            base_exp = int(data["client"].get("expires_at") or 0)
            new_exp = max(base_exp, now) + days * 86400
            st, upd = _vpn_req(node, "PATCH", f"/api/clients/{name}", body={"expires_at": new_exp})
            if st in (200, 201):
                return loc, {"ok": True, "extended": True, "expires_at": new_exp}, True
            return loc, {"ok": False, "error": upd.get("error") or f"HTTP {st}"}, False
        exp = now + days * 86400
        st, cre = _vpn_req(node, "POST", "/api/create", body={
            "name": name, "manual": 1, "title": title,
            "expires_at": exp, "traffic_limit": 0, "device_limit": 0,
        })
        if st in (200, 201):
            return loc, {"ok": True, "created": True, "expires_at": exp}, True
        return loc, {"ok": False, "error": cre.get("error") or f"HTTP {st}"}, False

    results = {}
    with ThreadPoolExecutor(max_workers=len(VPN_NODES) or 1) as ex:
        for loc, res, ok in ex.map(ensure_one, VPN_NODES):
            results[loc] = res
            if not ok:
                ok_all = False
    # механический: ok_all инициализируется в работе цикла
    return True, results


def _platega_request(method, path, body=None, idem=None):
    """Р’С‹РїРѕР»РЅСЏРµС‚ Р·Р°РїСЂРѕСЃ Рє API Platega. Р’РѕР·РІСЂР°С‰Р°РµС‚ (status, json)."""
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
    """РЎРѕР·РґР°С‘С‚ РѕРґРЅРѕСЂР°Р·РѕРІСѓСЋ РїР»Р°С‚С‘Р¶РЅСѓСЋ СЃСЃС‹Р»РєСѓ Platega РґР»СЏ РІС‹Р±СЂР°РЅРЅРѕРіРѕ С‚Р°СЂРёС„Р°.
    РўРµР»Рѕ: {plan: "30", email: "user@mail.ru"}"""
    data = request.get_json(silent=True) or {}
    plan_key = (data.get("plan") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if plan_key not in PLANS:
        return jsonify(ok=False, error="РќРµРёР·РІРµСЃС‚РЅС‹Р№ С‚Р°СЂРёС„"), 400
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="РЈРєР°Р¶РёС‚Рµ РєРѕСЂСЂРµРєС‚РЅСѓСЋ РїРѕС‡С‚Сѓ"), 400
    plan = PLANS[plan_key]
    if plan["price"] == "0.00":
        # РџСЂРѕР±РЅР°СЏ РїРѕРґРїРёСЃРєР°: РѕРґРёРЅ email вЂ” РѕРґРЅР° РїСЂРѕР±РЅР°СЏ. РџСЂРѕРґР»РµРІР°С‚СЊ РЅРµР»СЊР·СЏ.
        # Р’РµСЃСЊ Р±Р»РѕРє (РїСЂРѕРІРµСЂРєР° + СЃРѕР·РґР°РЅРёРµ РЅР° РїР°РЅРµР»СЏС…) вЂ” РїРѕРґ РѕРґРЅРёРј Р·Р°РјРєРѕРј,
        # С‡С‚РѕР±С‹ РґРІР° РїР°СЂР°Р»Р»РµР»СЊРЅС‹С… Р·Р°РїСЂРѕСЃР° РЅРµ Р°РєС‚РёРІРёСЂРѕРІР°Р»Рё РїСЂРѕР±РЅСѓСЋ РґРІР°Р¶РґС‹
        # (РёРЅР°С‡Рµ РјРµРґР»РµРЅРЅС‹Рµ РїР°РЅРµР»Рё РїРѕР»СѓС‡Р°СЋС‚ РґРІРѕР№РЅРѕРµ РїСЂРѕРґР»РµРЅРёРµ).
        with _trial_lock:
            used = _load_trial_used()
            if used.get(email, 0) >= 1:
                return jsonify(
                    ok=False, error="РџСЂРѕР±РЅР°СЏ РїРѕРґРїРёСЃРєР° СѓР¶Рµ Р±С‹Р»Р° РёСЃРїРѕР»СЊР·РѕРІР°РЅР° РґР»СЏ СЌС‚РѕР№ РїРѕС‡С‚С‹",
                    trial_already_used=True,
                ), 409
            used[email] = used.get(email, 0) + 1
            _save_trial_used(used)
            days = plan.get("days")
            if isinstance(days, int) and days > 0 and VPN_NODES:
                ok, res = _ensure_vpn_client(email, days)
                log.info("Trial: Р°РєС‚РёРІР°С†РёСЏ РґР»СЏ email=%s РЅР° %s РґРЅ. ok=%s %s", email, days, ok, json.dumps(res, ensure_ascii=False))
                return jsonify(ok=True, trial=True, label=plan["label"], activated=ok, days=days)
            return jsonify(ok=True, trial=True, label=plan["label"], activated=False)
    body = {
        "usageMode": 1,
        "paymentMode": 0,
        "currency": "RUB",
        "minAmount": plan["price"],
        "maxAmount": plan["price"],
        "name": plan["label"],
        "description": f"deepmint.vpn вЂ” {plan['label']}",
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
        error=resp.get("message") or resp.get("raw") or f"РћС€РёР±РєР° Platega ({status})",
        code=resp.get("code"),
    ), 502 if status else 503


def _load_messages():
    """Р¤РѕСЂРјР°С‚: {ticket_id: [ {role, name, text, ts}, ... ]}"""
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
    """Р§РёСЃР»РѕРІРѕР№ id СЃР»РµРґСѓСЋС‰РµРіРѕ С‚РёРєРµС‚Р°."""
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
    """Р”РѕР±Р°РІР»СЏРµС‚ СЃРѕРѕР±С‰РµРЅРёРµ РІ С‚РёРєРµС‚. РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ: ticket_id (СЃРѕР·РґР°С‘С‚СЃСЏ РїСЂРё РїРµСЂРІРѕРј СЃРѕРѕР±С‰РµРЅРёРё).
    РџРѕРґРґРµСЂР¶РєР°: key + ticket_id."""
    data = request.get_json(silent=True) or {}
    raw = (data.get("message") or "").strip()
    role = (data.get("role") or "user").strip()
    name = (data.get("name") or "РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ").strip()
    ticket_id = (data.get("ticket_id") or "").strip()
    if role == "admin":
        key = (data.get("key") or "").strip()
        if not key or key != ADMIN_KEY:
            return jsonify(ok=False, error="РќРµС‚ РґРѕСЃС‚СѓРїР°"), 403
    if not raw:
        return jsonify(ok=False, error="РџСѓСЃС‚РѕРµ СЃРѕРѕР±С‰РµРЅРёРµ"), 400
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
    """Р‘РµР· РєР»СЋС‡Р°: (ticket_id = СЃРІРѕР№ С‡Р°С‚). РЎ Р°РґРјРёРЅ-РєР»СЋС‡РѕРј: СЃРїРёСЃРѕРє С‚РёРєРµС‚РѕРІ."""
    key = (request.args.get("key") or "").strip()
    ticket_id = (request.args.get("ticket_id") or "").strip()
    tickets = _load_messages()
    if key and key == ADMIN_KEY:
        # Р”Р»СЏ РїРѕРґРґРµСЂР¶РєРё: СЃРїРёСЃРѕРє С‚РёРєРµС‚РѕРІ СЃ РїРѕСЃР»РµРґРЅРёРј СЃРѕРѕР±С‰РµРЅРёРµРј Рё С‡РёСЃР»РѕРј СЃРѕРѕР±С‰РµРЅРёР№
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


@app.get("/api/email/diag")
def email_diag():
    """Р”РёР°РіРЅРѕСЃС‚РёРєР°: Рє РєР°РєРѕРјСѓ IP СЂРµР·РѕР»РІРёС‚СЃСЏ SMTP-С…РѕСЃС‚ Рё РєР°РєРёРµ РїРѕСЂС‚С‹ РґРѕСЃС‚СѓРїРЅС‹."""
    import socket
    out = {"host": SMTP_HOST, "port": SMTP_PORT, "ipv4": None, "ipv4_ok": False, "online": False}
    try:
        infos = socket.getaddrinfo(SMTP_HOST, SMTP_PORT, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            out["ipv4"] = infos[0][4][0]
    except OSError as e:
        out["ipv4_error"] = str(e)
    try:
        with socket.create_connection((out["ipv4"] or SMTP_HOST, SMTP_PORT), timeout=8):
            out["ipv4_ok"] = True
    except OSError as e:
        out["ipv4_error"] = str(e)
    return jsonify(ok=True, diag=out)


def _days_for_amount(amount):
    """РЎРѕРїРѕСЃС‚Р°РІР»СЏРµС‚ СЃСѓРјРјСѓ РїР»Р°С‚РµР¶Р° СЃ С‚Р°СЂРёС„РѕРј Рё РІРѕР·РІСЂР°С‰Р°РµС‚ С‡РёСЃР»Рѕ РґРЅРµР№ РїРѕРґРїРёСЃРєРё."""
    if amount is None:
        return 0
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return 0
    for plan in PLANS.values():
        try:
            if abs(amt - float(plan["price"])) < 0.01:
                d = plan.get("days")
                if isinstance(d, int) and d > 0:
                    return d
        except (TypeError, ValueError):
            continue
    return 0


@app.get("/api/my-access")
def my_access():
    email = (request.args.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="РќРµРІРµСЂРЅС‹Р№ email"), 400

    name = "vpn-" + _smart_hash(email)
    nodes_out = []
    for node in VPN_NODES:
        status, data = _vpn_req(node, "GET", f"/api/clients/{name}")
        if status == 200 and data.get("client"):
            cl = data["client"]
            nodes_out.append({
                "loc": node["loc"],
                "active": cl.get("status") == "active" and not cl.get("banned"),
                "left_days": cl.get("left_days"),
                "expires_at": cl.get("expires_at"),
                "traffic_limit_gb": cl.get("traffic_limit_gb"),
                "traffic_used_gb": cl.get("traffic_used_gb"),
                "sub_url": cl.get("sub_url") or "",
                "link": (cl.get("inbound_links") or [{}])[0].get("link", "") if cl.get("inbound_links") else "",
            })
        else:
            nodes_out.append({"loc": node["loc"], "active": False})
    return jsonify(ok=True, email=email, nodes=nodes_out)


@app.get("/api/sub-all")
def sub_all():
    """РЎРѕР±РёСЂР°РµС‚ СЃСЃС‹Р»РєРё-РїРѕРґРїРёСЃРєРё СЃРѕ РІСЃРµС… Р°РєС‚РёРІРЅС‹С… Р»РѕРєР°С†РёР№ РєР»РёРµРЅС‚Р° РІ РѕРґРЅСѓ СЃС‚СЂРѕРєСѓ.
    {email} -> {ok, email, subs: ["https://.../sub/<uuid>", ...], links: ["vless://...", ...], all: "<subs, РїРѕ РѕРґРЅРѕР№ РЅР° СЃС‚СЂРѕРєСѓ>"}"""
    email = (request.args.get("email") or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(ok=False, error="РќРµРІРµСЂРЅС‹Р№ email"), 400

    name = "vpn-" + _smart_hash(email)
    subs, links = [], []
    for node in VPN_NODES:
        status, data = _vpn_req(node, "GET", f"/api/clients/{name}")
        if status != 200 or not data.get("client"):
            continue
        cl = data["client"]
        if cl.get("status") != "active" or cl.get("banned"):
            continue
        sub = (cl.get("sub_url") or "").strip()
        if sub:
            subs.append(sub)
        inbound = cl.get("inbound_links") or []
        for entry in inbound:
            l = (entry or {}).get("link") or ""
            if l.startswith("vless://"):
                links.append(l)
                break
    return jsonify(ok=True, email=email, subs=subs, links=links, all="\n".join(subs + links))


PHRASE_WORDS = [
    "Р°СЂР±СѓР·", "РІРѕСЂРѕРЅР°", "РґРѕРј", "С‘Р»РєР°", "Р¶СѓРє", "Р·Р°РјРѕРє", "РёРіР»Р°", "РєРѕС‚",
    "Р»СѓРЅР°", "РјС‹С€СЊ", "РЅРѕС‡СЊ", "РѕРєРЅРѕ", "РїР°СЂСѓСЃ", "СЂРµРєР°", "СЃРѕР»РЅС†Рµ", "С‚СѓРјР°РЅ",
    "СѓС‚СЂРѕ", "С„Р°РєРµР»", "С…Р»РµР±", "С†Р°РїР»СЏ", "С‡Р°СЃС‹", "С€Р°СЂ", "С‰РёС‚", "СЏРєРѕСЂСЊ",
]


def _norm_phrase(phrase):
    """РќРѕСЂРјР°Р»РёР·СѓРµС‚ С„СЂР°Р·Сѓ Рё РїСЂРѕРІРµСЂСЏРµС‚: РјРёРЅРёРјСѓРј 4 С‡Р°СЃС‚Рё, СЃСЂРµРґРё РЅРёС… С†РёС„СЂС‹."""
    norm = " ".join((phrase or "").lower().split())
    parts = [w for w in norm.split() if w]
    if len(parts) < 4:
        return None, "Р¤СЂР°Р·Р° РґРѕР»Р¶РЅР° СЃРѕСЃС‚РѕСЏС‚СЊ РјРёРЅРёРјСѓРј РёР· 4 С‡Р°СЃС‚РµР№"
    return norm, None


def _gen_phrase():
    """Р“РµРЅРµСЂРёСЂСѓРµС‚ РєР»СЋС‡РµРІСѓСЋ С„СЂР°Р·Сѓ РёР· 5 С‡Р°СЃС‚РµР№: 3 СЃР»РѕРІР°, 4-СЏ С‡Р°СЃС‚СЊ вЂ” С‡РёСЃР»Рѕ,
    5-СЏ вЂ” СЃР»РѕРІРѕ. РџСЂРёРјРµСЂ: В«Р±Р°РЅР°РЅ Р°СЂР±СѓР· РєРёРІРё 4532 СѓРіРѕР»СЊВ»."""
    import random as _r
    words = _r.sample(PHRASE_WORDS, 4)
    return f"{words[0]} {words[1]} {words[2]} {_r.randint(1000, 9999)} {words[3]}"


def _issue_access(name, title, days):
    """Создаёт/продлевает клиента name и возвращает json-ответ с фразой+ссылками.
    Сбор ссылок идёт параллельно по панелям, чтобы мёртвые ноды не тормозили."""
    from concurrent.futures import ThreadPoolExecutor

    links, subs, nodes = [], [], []
    with ThreadPoolExecutor(max_workers=len(VPN_NODES) or 1) as ex:
        futures = {loc: ex.submit(_vpn_req, node, "GET", f"/api/clients/{name}") for loc, node in ((n["loc"], n) for n in VPN_NODES)}
        for loc, f in futures.items():
            try:
                status, data = f.result()
            except Exception:
                continue
            if status == 200 and data.get("client"):
                cl = data["client"]
                st_ok = cl.get("status") == "active" and not cl.get("banned")
                sub = (cl.get("sub_url") or "").strip()
                first_link = ""
                for e in (cl.get("inbound_links") or []):
                    if isinstance(e, dict) and str(e.get("link", "")).startswith("vless://"):
                        first_link = e["link"]
                        break
                nodes.append({
                    "loc": loc,
                    "active": st_ok,
                    "left_days": cl.get("left_days"),
                    "expires_at": cl.get("expires_at"),
                    "sub_url": sub,
                    "link": first_link,
                })
                if st_ok:
                    if sub:
                        subs.append(sub)
                    if first_link:
                        links.append(first_link)
    return links, subs, nodes, None


@app.post("/api/register")
def register():
    """Р РµРіРёСЃС‚СЂР°С†РёСЏ: РІС‹РґР°С‘С‚ РЅРѕРјРµСЂ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Рё Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРіРµРЅРµСЂРёСЂРѕРІР°РЅРЅСѓСЋ
    РєР»СЋС‡РµРІСѓСЋ С„СЂР°Р·Сѓ (4 С‡РёСЃР»Р° + СЃР»РѕРІРѕ). Р¤СЂР°Р·Р° вЂ” Р»РѕРіРёРЅ Рё РїР°СЂРѕР»СЊ РѕРґРЅРѕРІСЂРµРјРµРЅРЅРѕ.
    { } -> {ok, userId, user, phrase, links:[...], nodes:[...]}"""
    import random as _r
    data = request.get_json(silent=True) or {}
    # РЅРѕРјРµСЂ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ: РјРѕРЅРѕС‚РѕРЅРЅС‹Р№ СЃС‡С‘С‚С‡РёРє РёР· storages (users_counter.json РІ DATA_DIR)
    cnt_file = _data_file("users_counter.json")
    try:
        n = int(cnt_file.read_text(encoding="utf-8").strip()) if cnt_file.exists() else 0
    except (OSError, ValueError):
        n = 0
    n += 1
    try:
        cnt_file.write_text(str(n), encoding="utf-8")
    except OSError:
        pass
    phrase = _gen_phrase()
    name = "user-" + str(n)
    days = 30
    links, subs, nodes, err = _issue_access(name, phrase, days)
    if err:
        return jsonify(ok=False, error=err), 502
    return jsonify(
        ok=True,
        userId=n,
        user=str(n),
        phrase=phrase,
        name=name,
        days=days,
        links=links,
        subs=subs,
        nodes=nodes,
        all="\n".join(subs + links),
    )


@app.post("/api/login")
def login_phrase():
    """Р’С…РѕРґ РїРѕ РєР»СЋС‡РµРІРѕР№ С„СЂР°Р·Рµ (Р»РѕРіРёРЅ+РїР°СЂРѕР»СЊ). Р’РѕР·РІСЂР°С‰Р°РµС‚ РґРѕСЃС‚СѓРї Рё СЃСЃС‹Р»РєРё.
    {phrase} -> {ok, user, phrase, links:[...], nodes:[...]}"""
    data = request.get_json(silent=True) or {}
    phrase = (data.get("phrase") or "").strip()
    norm, err = _norm_phrase(phrase)
    if err:
        return jsonify(ok=False, error=err), 400
    name = "phrase-" + _smart_hash(norm)
    days = 30
    links, subs, nodes, err = _issue_access(name, norm, days)
    if err:
        return jsonify(ok=False, error=err), 502
    return jsonify(
        ok=True,
        user=norm,
        phrase=norm,
        name=name,
        days=days,
        links=links,
        subs=subs,
        nodes=nodes,
        all="\n".join(subs + links),
    )


PAYMENTS_FILE = _data_file("payments.json")


def _load_payments():
    """РҐСЂР°РЅРёР»РёС‰Рµ РІРµР±С…СѓРєРѕРІ Platega: {payment_id: record}"""
    try:
        if PAYMENTS_FILE.exists():
            data = json.loads(PAYMENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _save_payments(payments):
    try:
        PAYMENTS_FILE.write_text(json.dumps(payments, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


@app.post("/api/callback")
def platega_callback():
    """Р’РµР±С…СѓРє РѕС‚ Platega: СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ СЃС‚Р°С‚СѓСЃР°С… РїР»Р°С‚РµР¶РµР№ Рё РІРѕР·РІСЂР°С‚РѕРІ.
    Р—Р°РїСЂРѕСЃ РїСЂРѕРІРµСЂСЏРµРј РїРѕ X-MerchantId / X-Secret. РРґРµРјРїРѕС‚РµРЅС‚РЅРѕСЃС‚СЊ РїРѕ id."""
    data = request.get_json(silent=True) or {}
    merchant = (request.headers.get("X-MerchantId") or "").strip()
    secret = (request.headers.get("X-Secret") or "").strip()
    if merchant and merchant != PLATEGA_MERCHANT_ID:
        log.info("Platega callback: РЅРµСЃРѕРІРїР°РґРµРЅРёРµ X-MerchantId")
        return jsonify(ok=False, error="bad merchant"), 403
    if secret and secret != PLATEGA_SECRET:
        log.info("Platega callback: РЅРµСЃРѕРІРїР°РґРµРЅРёРµ X-Secret")
        return jsonify(ok=False, error="bad secret"), 403

    pid = str(data.get("id") or "")
    status = (data.get("status") or "").upper()
    record = {
        "id": pid,
        "status": status,
        "amount": data.get("amount"),
        "currency": data.get("currency"),
        "paymentMethod": data.get("paymentMethod"),
        "paymentLinkId": data.get("paymentLinkId"),
        "subscriptionId": data.get("subscriptionId"),
        "refundId": data.get("refundId"),
        "refundedAmount": data.get("refundedAmount"),
        "payload": data.get("payload") or "",
        "ts": time.time(),
    }
    payments = _load_payments()
    prev = payments.get(pid)
    if prev and prev.get("status") == status:
        # РїРѕРІС‚РѕСЂРЅР°СЏ РґРѕСЃС‚Р°РІРєР° С‚РѕРіРѕ Р¶Рµ СЃРѕР±С‹С‚РёСЏ вЂ” РёРґРµРјРїРѕС‚РµРЅС‚РЅС‹Р№ РѕС‚РІРµС‚
        return jsonify(ok=True, idempotent=True)
    payments[pid] = record
    _save_payments(payments)

    email = (data.get("payload") or "").strip().lower()
    log.info(
        "Platega callback: status=%s amount=%s %s id=%s email=%s link=%s",
        status, data.get("amount"), data.get("currency"), pid, email or "-", record.get("paymentLinkId") or "-",
    )
    if status == "CONFIRMED":
        # РџР»Р°С‚С‘Р¶ РїРѕРґС‚РІРµСЂР¶РґС‘РЅ: Р°РєС‚РёРІРёСЂСѓРµРј/РїСЂРѕРґР»РµРІР°РµРј VPN-РґРѕСЃС‚СѓРї РґР»СЏ email.
        days = _days_for_amount(data.get("amount"))
        if email and days:
            ok, res = _ensure_vpn_client(email, days)
            log.info(
                "VPN: Р°РєС‚РёРІР°С†РёСЏ РґР»СЏ email=%s РЅР° %s РґРЅ. ok=%s details=%s",
                email, days, ok, json.dumps(res, ensure_ascii=False),
            )
        else:
            log.info("VPN: РїСЂРѕРїСѓСЃРєР°СЋ Р°РєС‚РёРІР°С†РёСЋ email=%s days=%s", email or "-", days)
    return jsonify(ok=True)


@app.get("/api/payments")
def payments_list():
    """РџСЂРѕСЃРјРѕС‚СЂ РїРѕР»СѓС‡РµРЅРЅС‹С… РІРµР±С…СѓРєРѕРІ (РґР»СЏ РѕС‚Р»Р°РґРєРё). Р”РѕСЃС‚СѓРї РїРѕ ADMIN_KEY."""
    key = (request.args.get("key") or "").strip()
    if not key or key != ADMIN_KEY:
        return jsonify(ok=False, error="РќРµС‚ РґРѕСЃС‚СѓРїР°"), 403
    payments = _load_payments()
    items = sorted(payments.values(), key=lambda r: r.get("ts", 0), reverse=True)
    return jsonify(ok=True, payments=items[:50])


_load_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("EMAIL_SERVER_PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)
