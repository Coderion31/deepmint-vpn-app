import json
import logging
import os
from pathlib import Path

import socket

# Фикс доступности api.telegram.org из сетей, где DNS отдаёт недоступный
# адрес (или IPv6). Пинуем известные рабочие IPv4 Telegram и подменяем
# getaddrinfo, чтобы requests подключался к живому IP с сохранением
# SNI/проверки TLS по имени api.telegram.org.
TELEGRAM_API_HOST = "api.telegram.org"
TELEGRAM_API_IPS = ["149.154.167.220", "149.154.166.110", "149.154.167.200", "149.154.166.220"]


def _pick_api_ip():
    import socket as _s

    for ip in TELEGRAM_API_IPS:
        try:
            with _s.create_connection((ip, 443), timeout=4):
                return ip
        except OSError:
            continue
    return TELEGRAM_API_IPS[0]


_ORIG_GETADDRINFO = socket.getaddrinfo
_PINNED_API_IP = _pick_api_ip()


def _pinned_getaddrinfo(host, *args, **kwargs):
    if isinstance(host, str) and host == TELEGRAM_API_HOST:
        host = _PINNED_API_IP
    return _ORIG_GETADDRINFO(host, *args, **kwargs)


socket.getaddrinfo = _pinned_getaddrinfo


def _refresh_api_ip():
    """Перепин рабочего IP: вызывается при сбое соединения."""
    global _PINNED_API_IP
    new_ip = _pick_api_ip()
    if new_ip != _PINNED_API_IP:
        _PINNED_API_IP = new_ip
        socket.getaddrinfo = _pinned_getaddrinfo  # подхватывает новое значение через замыкание
        log.info("Telegram API IP refreshed: %s", new_ip)


import requests

TOKEN = os.environ.get("DEEPMINT_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"

BANK_CODE = "плаtega"  # служебный код для согласования кассы

CHANNEL_USERNAME = "@deepmintvpn"
CHANNEL_LINK = "https://t.me/deepmintvpn"
CHANNELS = [CHANNEL_USERNAME]

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("deepmint-bot")

SUB_YES = {"creator", "administrator", "member"}


def load_users():
    try:
        if USERS_FILE.exists():
            data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): v for k, v in data.items()}
            if isinstance(data, list):
                # старый формат: список id тех, кто уже заходил
                return {str(u): {"accepted": True, "welcome_sent": True} for u in data}
    except (OSError, ValueError):
        pass
    return {}


def save_users(users):
    try:
        USERS_FILE.write_text(
            json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


USERS = load_users()


def call(method, **kwargs):
    for attempt in range(3):
        try:
            # Отдельная сессия на каждый запрос: исключает "параллельные"
            # long-polling от одного процесса (Telegram это режет конфликтом 409)
            # из-за переиспользования соединения в пуле urllib3.
            s = requests.Session()
            try:
                r = s.post(f"{API}/{method}", json=kwargs, timeout=30)
                data = r.json()
                if not data.get("ok"):
                    log.warning("API %s error: %s", method, data.get("description"))
                return data.get("result")
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        except requests.RequestException as e:
            log.error("API %s request failed (attempt %d): %s", method, attempt + 1, e)
            try:
                _refresh_api_ip()
            except Exception:
                pass
    return None


def send_chat_action(chat_id, action="typing"):
    call("sendChatAction", chat_id=chat_id, action=action)


def send_text(chat_id, text, **extra):
    return call("sendMessage", chat_id=chat_id, text=text, **extra)


def delete_message(chat_id, message_id):
    if not message_id:
        return True
    return bool(call("deleteMessage", chat_id=chat_id, message_id=message_id))


def send_step(state, chat_id, text, **extra):
    """Удаляет все предыдущие сообщения бота и отправляет новое."""
    for mid in list(state.get("msg_ids", [])):
        delete_message(chat_id, mid)
    state["msg_ids"] = []
    result = send_text(chat_id, text, **extra)
    if result:
        state["msg_ids"] = [result.get("message_id")]
    save_users(USERS)
    return result


def is_subscribed(user_id):
    for chat in CHANNELS:
        member = call("getChatMember", chat_id=chat, user_id=user_id)
        if member is None:
            # API недоступен или канал закрыт для бота: пропускаем проверку,
            # чтобы не блокировать пользователя из-за технической ошибки.
            return True
        if member.get("status") not in SUB_YES:
            return False
    return True


def user_state(user_id):
    return USERS.setdefault(
        str(user_id),
        {"accepted": False, "welcome_sent": False, "msg_ids": []},
    )


def save_user_name(user_id, from_info):
    if not from_info:
        return
    name = " ".join(
        filter(None, [from_info.get("first_name"), from_info.get("last_name")])
    ) or from_info.get("username") or ""
    if name:
        state = user_state(user_id)
        state["name"] = name
        save_users(USERS)


DOC_LINKS = {
    "doc_privacy": "https://coderion31.github.io/deepmint-vpn-app/privacy.html",
    "doc_terms": "https://coderion31.github.io/deepmint-vpn-app/terms.html",
    "doc_refund": "https://telegra.ph/Usloviya-vozvrata--deepmint-vpn-10-27",
    "doc_bot_policy": "https://telegra.ph/Politika-bota--deepmint-vpn-10-27",
}


def terms_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "Политика конфиденциальности",
                    "url": DOC_LINKS["doc_privacy"],
                }
            ],
            [{"text": "Условия использования", "url": DOC_LINKS["doc_terms"]}],
            [{"text": "Условия возврата", "url": DOC_LINKS["doc_refund"]}],
            [{"text": "Политика бота", "url": DOC_LINKS["doc_bot_policy"]}],
            [{"text": "Я принимаю условия", "callback_data": "accept_terms"}],
        ]
    }


def sub_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Подписаться на канал", "url": CHANNEL_LINK}],
            [{"text": "Я подписался", "callback_data": "check_sub"}],
        ]
    }


APP_LINK = "https://coderion31.github.io/deepmint-vpn-app/"
SUPPORT_EMAIL = "bunseriy@gmail.com"
SUPPORT_LINK = "mailto:bunseriy@gmail.com"


def menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Купить подписку", "callback_data": "menu_buy"}],
            [{"text": "Открыть приложение", "web_app": {"url": APP_LINK}}],
            [{"text": "Баланс", "callback_data": "menu_balance"}],
            [{"text": "Пригласить друзей", "callback_data": "menu_invite"}],
            [{"text": "Поддержка", "url": SUPPORT_LINK}],
            [{"text": "Документы", "callback_data": "menu_docs"}],
        ]
    }


def docs_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Политика конфиденциальности", "url": DOC_LINKS["doc_privacy"]}],
            [{"text": "Условия использования", "url": DOC_LINKS["doc_terms"]}],
            [{"text": "Условия возврата", "url": DOC_LINKS["doc_refund"]}],
            [{"text": "Политика бота", "url": DOC_LINKS["doc_bot_policy"]}],
            [{"text": "Назад", "callback_data": "menu_back"}],
        ]
    }


PLANS = {
    "trial": {"label": "Пробная — 72 часа", "price": "0 ₽"},
    "30": {"label": "30 дней", "price": "199 ₽"},
    "90": {"label": "90 дней", "price": "549 ₽"},
    "180": {"label": "180 дней", "price": "999 ₽"},
    "360": {"label": "360 дней", "price": "1799 ₽"},
}

EXTRA_DEVICE_PRICE = "1.39 ₽/день за доп. устройство"


def buy_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Пробная — 72 часа (0 ₽)", "callback_data": "buy_trial"}],
            [{"text": "30 дней — 199 ₽", "callback_data": "buy_30"}],
            [{"text": "90 дней — 549 ₽", "callback_data": "buy_90"}],
            [{"text": "180 дней — 999 ₽", "callback_data": "buy_180"}],
            [{"text": "360 дней — 1799 ₽", "callback_data": "buy_360"}],
            [{"text": "Назад в меню", "callback_data": "menu_back"}],
        ]
    }


def send_planinteractive(state, chat_id):
    send_chat_action(chat_id, "typing")
    send_step(
        state,
        chat_id,
        (
            "Купить подписку\n\n"
            "Пробная подписка — 72 часа, бесплатно\n\n"
            "30 дней — 199 ₽\n"
            "90 дней — 549 ₽\n"
            "180 дней — 999 ₽\n"
            "360 дней — 1799 ₽\n\n"
            "Стандарт: 2 устройства на подписку.\n"
            "Доп. устройство — 1.39 ₽ в день.\n\n"
            "Безлимитный трафик и все локации включены."
        ),
        reply_markup=buy_keyboard(),
    )


def balance_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Пополнить баланс", "callback_data": "balance_topup"}],
            [{"text": "Назад", "callback_data": "menu_back"}],
        ]
    }


def invite_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Назад в меню", "callback_data": "menu_back"}],
        ]
    }


def send_menu(state, chat_id):
    send_chat_action(chat_id, "typing")
    send_step(
        state,
        chat_id,
        (
            "Главное меню deepmint vpn\n\n"
            "Выберите раздел: открыть приложение, проверить баланс, "
            "пригласить друзей или обратиться в поддержку."
        ),
        reply_markup=menu_keyboard(),
    )


def send_docs(state, chat_id):
    send_chat_action(chat_id, "typing")
    send_step(
        state,
        chat_id,
        "Документы deepmint vpn\n\nВыберите документ:",
        reply_markup=docs_keyboard(),
    )


def send_terms(state, chat_id, **extra):
    send_step(
        state,
        chat_id,
        (
            "Добро пожаловать в deepmint vpn.\n\n"
            "Прежде чем начать работу, ознакомьтесь с документами "
            "и примите условия сервиса."
        ),
        reply_markup=terms_keyboard(),
        **extra,
    )


def send_enter_text(state, chat_id):
    send_chat_action(chat_id, "typing")
    send_step(
        state,
        chat_id,
        (
            f"Добро пожаловать в deepmint vpn.\n\n"
            "Для начала работы подпишитесь на наш канал "
            f"{CHANNEL_LINK} — там новости, тарифы и обновления.\n\n"
            "После подписки нажмите кнопку ниже."
        ),
        reply_markup=sub_keyboard(),
    )


CABINET_URL = "https://clck.ru/3WqZoF"
APP_LINK = "https://coderion31.github.io/deepmint-vpn-app/"


def vpnus_welcome_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Личный кабинет", "web_app": {"url": APP_LINK}}],
        ]
    }


def vpnus_cabinet_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Открыть личный кабинет", "web_app": {"url": APP_LINK}}],
        ]
    }


CABINET_MSG = (
    "Ваш вход в личный кабинет VPNUS.\n\n"
    "Откройте личный кабинет по кнопке ниже, чтобы подключиться или "
    "оформить подписку."
    "\n\nПодключение займёт 2 минуты."
)


def handle_start(chat_id, user_id, payload=None):
    if payload and payload.startswith("link_"):
        email = payload[len("link_"):].strip().lower()
        if email and "@" in email:
            state = user_state(user_id)
            state["linked_email"] = email
            state["accepted"] = True
            save_users(USERS)
            send_step(
                state,
                chat_id,
                (
                    f"Аккаунт привязан!\n\n"
                    f"Почта: {email}\n"
                    f"Telegram: {user_id}\n\n"
                    "Теперь вход по почте или Telegram открывает один аккаунт."
                ),
            )
            send_start(chat_id, user_id)
            return
    state = user_state(user_id)
    send_start(chat_id, user_id)


def send_start(chat_id, user_id):
    state = user_state(user_id)
    send_chat_action(chat_id, "typing")
    name = (USERS.get(str(user_id)) or {}).get("name") or "NOONEE"
    send_step(
        state,
        chat_id,
        (
            f"Привет, {name}!\n\n"
            "deepmint vpn — новейший vpn сервис.\n\n"
            "Для входа и настройки нажмите кнопку ниже — "
            "приложение откроется внутри Telegram, без пароля."
        ),
        reply_markup=vpnus_welcome_keyboard(),
    )


def handle_accept(chat_id, user_id, message_id):
    state = user_state(user_id)
    state["accepted"] = True
    save_users(USERS)
    delete_message(chat_id, message_id)
    send_step(state, chat_id, "Спасибо! Условия приняты. Добро пожаловать в deepmint vpn.")
    send_menu(state, chat_id)


def handle_check_sub(chat_id, user_id, message_id):
    send_chat_action(chat_id)
    state = user_state(user_id)
    subscribed = is_subscribed(user_id)
    if subscribed:
        delete_message(chat_id, message_id)
        for mid in list(state.get("msg_ids", [])):
            delete_message(chat_id, mid)
        state["msg_ids"] = []
        save_users(USERS)
        send_step(
            state,
            chat_id,
            "Подписка оформлена. Спасибо! Добро пожаловать в deepmint vpn.",
        )
        send_terms(state, chat_id)
    else:
        delete_message(chat_id, message_id)
        send_step(
            state,
            chat_id,
            (
                "Вы ещё не подписались на канал.\n\n"
                f"Перейдите по ссылке {CHANNEL_LINK}, подпишитесь "
                "и нажмите кнопку ещё раз."
            ),
            reply_markup=sub_keyboard(),
        )


def handle_help(chat_id):
    send_chat_action(chat_id)
    send_text(
        chat_id,
        (
            "Помощь по deepmint.vpn\n\n"
            "Команды:\n"
            "/start — приветствие\n"
            "/help — этот список\n\n"
            "Документы:\n"
            "• Политика конфиденциальности\n"
            "• Условия использования\n"
            "• Условия возврата\n"
            "• Политика бота"
        ),
    )


def handle_update(update):
    message = update.get("message")
    callback = update.get("callback_query")

    if callback:
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        user_id = callback["from"]["id"]
        data = callback.get("data")
        call("answerCallbackQuery", callback_query_id=callback["id"])

        if data == "vpnus_action":
            state = user_state(user_id)
            send_step(state, chat_id, CABINET_MSG, reply_markup=vpnus_cabinet_keyboard())
        elif data == "accept_terms":
            handle_accept(chat_id, user_id, message_id)
        elif data == "check_sub":
            handle_check_sub(chat_id, user_id, message_id)
        elif data == "menu_buy":
            state = user_state(user_id)
            send_planinteractive(state, chat_id)
        elif data == "menu_balance":
            state = user_state(user_id)
            send_step(
                state,
                chat_id,
                "Баланс: 0 ₽\n\n"
                "Пополнение появится после подключения тарифа в приложении.",
                reply_markup=balance_keyboard(),
            )
        elif data == "balance_topup":
            state = user_state(user_id)
            send_step(
                state,
                chat_id,
                "Пополнение баланса пока не работает.\n\n"
                "Скоро здесь можно будет оплатить подписку картой или СБП.",
                reply_markup=balance_keyboard(),
            )
        elif data == "menu_invite":
            state = user_state(user_id)
            send_step(
                state,
                chat_id,
                (
                    "Заработать с deepmint.vpn\n\n"
                    "Приглашай друзей и получай 20% с их оплат.\n\n"
                    "Друзей приглашено: 0\n"
                    "Активировали пробный доступ: 0\n"
                    "Заработано с рефералов: 0₽\n\n"
                    "Ваша реферальная ссылка:\n"
                    f"https://t.me/deepmintvpn_bot?start={user_id}"
                ),
                reply_markup=invite_keyboard(),
            )
        elif data.startswith("buy_"):
            state = user_state(user_id)
            days = data.split("_")[1]
            plan = PLANS.get(days, {"label": days + " дней", "price": ""})
            state["pending_email"] = days
            save_users(USERS)
            send_step(
                state,
                chat_id,
                (
                    f"Вы выбрали тариф «{plan['label']}» — {plan['price']}.\n\n"
                    "Для создания транзакции укажите почту, на которую придёт "
                    "чек и доступ к подписке.\n\n"
                    "Просто напишите её в чат (например: you@mail.ru)."
                ),
                reply_markup=buy_keyboard(),
            )
        elif data == "menu_docs":
            state = user_state(user_id)
            send_docs(state, chat_id)
        elif data == "menu_back":
            state = user_state(user_id)
            send_menu(state, chat_id)
        return

    if not message:
        return
    chat_id = message["chat"]["id"]
    user_id = message.get("from", {}).get("id")
    text = (message.get("text") or "").strip()
    state = user_state(user_id)

    if text == "/start":
        save_user_name(user_id, message.get("from", {}))
        handle_start(chat_id, user_id)
    elif text.startswith("/start "):
        payload = text[len("/start "):].strip()
        save_user_name(user_id, message.get("from", {}))
        handle_start(chat_id, user_id, payload)
    elif text == "/help":
        handle_help(chat_id)
    elif state.get("pending_email") and "@" in text and "." in text:
        state["email"] = text.strip().lower()
        days = state.pop("pending_email")
        plan = PLANS.get(days, {"label": days + " дней", "price": ""})
        save_users(USERS)
        send_step(
            state,
            chat_id,
            (
                f"Почта принята: {state['email']}\n\n"
                f"Тариф «{plan['label']}» — {plan['price']}.\n\n"
                "Оплата пока не подключена. Чек и доступ к подписке "
                "придут на вашу почту, как только платёж будет возможен."
            ),
            reply_markup=buy_keyboard(),
        )


def main():
    if not TOKEN:
        log.error("DEEPMINT_BOT_TOKEN is not set")
        return
    me = call("getMe")
    if me:
        log.info("bot started: %s (@%s)", me.get("first_name"), me.get("username"))
        log.info("channel: %s", CHANNELS)

    # Режим one-shot (BOT_POLL_ONESHOT=1) — для GitHub Actions: один прогон
    # за минуту. По умолчанию (0/не задано) — бесконечный long-polling для
    # облачного хостинга (Render).
    if os.environ.get("BOT_POLL_ONESHOT", "0").strip() == "1":
        offset = USERS.get("_offset")
        params = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        updates = call("getUpdates", **params) or []
        for update in updates:
            uid = update.get("update_id", 0)
            if uid >= (offset or 0):
                offset = uid + 1
            try:
                handle_update(update)
            except Exception:
                log.exception("failed to handle update %s", uid)
        if offset is not None:
            USERS["_offset"] = offset
        save_users(USERS)
        log.info("done: processed %d update(s)", len(updates))
        return

    # Бесконечный long-polling (облачный хостинг)
    offset = None
    while True:
        params = {"timeout": 30}
        if offset is not None:
            params["offset"] = offset
        updates = call("getUpdates", **params)
        if not updates:
            continue
        for update in updates:
            if update.get("update_id", 0) >= (offset or 0):
                offset = update["update_id"] + 1
            try:
                handle_update(update)
            except Exception:
                log.exception("failed to handle update %s", update.get("update_id"))


if __name__ == "__main__":
    main()