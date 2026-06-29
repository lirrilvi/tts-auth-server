"""
TTS Auth Bot v2 — с подписками, сменами, админкой
"""
import os, time, requests, telebot
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
BOT_SECRET = os.getenv("BOT_SECRET", "change_me")
_port      = int(os.getenv("PORT", 5055))
SERVER_URL = f"http://localhost:{_port}"

if not BOT_TOKEN:
    raise RuntimeError("Укажи BOT_TOKEN в .env")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Киевское время UTC+3 (летнее)
TZ = timezone(timedelta(hours=3))

# ─── Админы ───────────────────────────────────────────────────────────────────
ADMIN_IDS = {613401025, 8442411439, 8398128007, 680248573}
ADMIN_USERNAMES = {"bakitakii", "zxcsuzzumi666", "lirrilvi", "OnlyGrowth_1"}

def is_admin(msg_or_id) -> bool:
    if isinstance(msg_or_id, int):
        return msg_or_id in ADMIN_IDS
    uid = msg_or_id.from_user.id
    uname = (msg_or_id.from_user.username or "").lower()
    return uid in ADMIN_IDS or uname in {a.lower() for a in ADMIN_USERNAMES}

# ─── Вспомогалки ──────────────────────────────────────────────────────────────
def api(endpoint, **kwargs):
    try:
        r = requests.post(f"{SERVER_URL}/api/{endpoint}",
                          json={"bot_secret": BOT_SECRET, **kwargs}, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def now_kyiv():
    return datetime.now(TZ)

def shift_expires_at(shift: str) -> int:
    """Возвращает unix timestamp конца смены (UTC)."""
    now = now_kyiv()
    h = now.hour

    if shift == "night":
        # Ночная: 23:00 – 11:00
        if h >= 23:
            end = now.replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
        elif h < 11:
            end = now.replace(hour=11, minute=0, second=0, microsecond=0)
        else:
            # Сейчас день — ночная начнётся в 23:00, закончится в 11:00 след. дня
            end = now.replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        # Дневная: 11:00 – 23:00
        if 11 <= h < 23:
            end = now.replace(hour=23, minute=0, second=0, microsecond=0)
        elif h >= 23:
            end = now.replace(hour=23, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            # Сейчас ночь — дневная начнётся в 11:00
            end = now.replace(hour=23, minute=0, second=0, microsecond=0)

    return int(end.timestamp())

def admin_monthly_expires() -> int:
    """Токен для админа — до конца текущего месяца."""
    now = now_kyiv()
    if now.month == 12:
        end = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0)
    else:
        end = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0)
    return int(end.timestamp())

def notify_admins(text: str, markup=None):
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text, reply_markup=markup)
        except Exception:
            pass

# ─── /start ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg: Message):
    if is_admin(msg):
        bot.send_message(msg.chat.id,
            f"👑 Привет, администратор <b>{msg.from_user.first_name}</b>!\n\n"
            "/token — получить свой месячный токен\n"
            "/admin — панель управления\n"
            "/help — помощь"
        )
    else:
        bot.send_message(msg.chat.id,
            f"👋 Привет, <b>{msg.from_user.first_name}</b>!\n\n"
            "Это бот для доступа к TTS расширению на alpha.date.\n\n"
            "📌 <b>Команды:</b>\n"
            "/getext — запросить расширение для Chrome\n"
            "/subscribe — запросить подписку (1 месяц)\n"
            "/token — получить токен на смену\n"
            "/help — помощь"
        )

# ─── /help ────────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["help"])
def cmd_help(msg: Message):
    if is_admin(msg):
        bot.send_message(msg.chat.id,
            "👑 <b>Команды администратора:</b>\n\n"
            "/token — месячный токен (обновляется каждый месяц)\n"
            "/admin — панель: активные токены, заявки, блок\n\n"
            "🔧 <b>Управление в /admin:</b>\n"
            "• Просмотр всех активных токенов\n"
            "• Отзыв токена у пользователя\n"
            "• Блок / разблок пользователя\n"
            "• Одобрение подписок и запросов на расширение"
        )
    else:
        bot.send_message(msg.chat.id,
            "❓ <b>Как пользоваться:</b>\n\n"
            "1. /getext — запроси расширение для Chrome\n"
            "2. /subscribe — запроси подписку (ждёт одобрения)\n"
            "3. /token — выбери смену и получи токен\n"
            "4. Введи токен в расширении на alpha.date\n\n"
            "🕐 <b>Смены:</b>\n"
            "• Ночная: 23:00 – 11:00\n"
            "• Дневная: 11:00 – 23:00\n\n"
            "Токен действует до конца выбранной смены."
        )

# ─── /subscribe ───────────────────────────────────────────────────────────────
@bot.message_handler(commands=["subscribe"])
def cmd_subscribe(msg: Message):
    if is_admin(msg):
        bot.send_message(msg.chat.id, "👑 Администраторам подписка не нужна.")
        return

    uid   = str(msg.from_user.id)
    uname = msg.from_user.username or ""
    fname = msg.from_user.first_name or ""

    data = api("sub_request", user_id=uid, username=uname, first_name=fname)

    if data.get("ok"):
        bot.send_message(msg.chat.id,
            "✅ Заявка отправлена! Ожидай одобрения от администратора.\n"
            "Тебе придёт уведомление."
        )
        # Уведомляем всех админов
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{uid}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"deny_{uid}")
        )
        markup2 = InlineKeyboardMarkup()
        markup2.row(
            InlineKeyboardButton("✅ Смена", callback_data=f"approve_{uid}"),
            InlineKeyboardButton("🗓 Месяц", callback_data=f"approve_monthly_{uid}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"deny_{uid}")
        )
        notify_admins(
            f"📩 <b>Новая заявка на подписку</b>\n\n"
            f"👤 {fname} (@{uname})\n"
            f"🆔 ID: <code>{uid}</code>",
            markup2
        )
    elif data.get("error") == "already_subscribed":
        d = data.get("days_left", 0)
        bot.send_message(msg.chat.id, f"✅ У тебя уже есть активная подписка.\nОсталось: {d} дней.")
    elif data.get("error") == "pending":
        bot.send_message(msg.chat.id, "⏳ Твоя заявка уже ожидает рассмотрения.")
    else:
        bot.send_message(msg.chat.id, f"❌ Ошибка: {data.get('error')}")

# ─── /token ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["token"])
def cmd_token(msg: Message):
    uid   = str(msg.from_user.id)
    uname = msg.from_user.username or ""
    fname = msg.from_user.first_name or ""

    if is_admin(msg):
        # Администратор — месячный токен
        expires_at = admin_monthly_expires()
        data = api("generate", user_id=uid, expires_at=expires_at,
                   shift="admin", username=uname, first_name=fname)
        if data.get("ok"):
            token = data["token"]
            now = now_kyiv()
            if now.month == 12:
                end_str = f"1 января {now.year+1}"
            else:
                import calendar
                end_str = f"1 {['','янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'][now.month+1]} {now.year}"
            bot.send_message(msg.chat.id,
                f"👑 Твой месячный токен:\n\n"
                f"<code>{token}</code>\n\n"
                f"📅 Действует до: <b>{end_str}</b>\n"
                f"📋 Нажми на код чтобы скопировать"
            )
        else:
            bot.send_message(msg.chat.id, f"❌ Ошибка: {data.get('error')}")
        return

    # Обычный пользователь — проверяем подписку через список активных
    # (упрощённо: сервер сам хранит subscription_end, проверим через generate)
    # Показываем выбор смены
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🌙 Ночная (23:00–11:00)", callback_data=f"shift_night_{uid}"),
    )
    markup.row(
        InlineKeyboardButton("☀️ Дневная (11:00–23:00)", callback_data=f"shift_day_{uid}")
    )
    bot.send_message(msg.chat.id, "⏰ Выбери свою смену:", reply_markup=markup)

# ─── Callback: выбор смены ────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("shift_"))
def cb_shift(call: CallbackQuery):
    parts   = call.data.split("_")
    shift   = parts[1]        # night / day
    req_uid = parts[2]        # user_id кто запросил

    # Проверяем что кнопку жмёт тот же пользователь
    if str(call.from_user.id) != req_uid:
        bot.answer_callback_query(call.id, "Это не твоя кнопка.")
        return

    uid   = str(call.from_user.id)
    uname = call.from_user.username or ""
    fname = call.from_user.first_name or ""

    expires_at  = shift_expires_at(shift)
    shift_label = "Ночная 🌙 (23:00–11:00)" if shift == "night" else "Дневная ☀️ (11:00–23:00)"

    bot.answer_callback_query(call.id, "Генерирую токен...")

    data = api("generate", user_id=uid, expires_at=expires_at,
               shift=shift, username=uname, first_name=fname)

    if data.get("ok"):
        token    = data["token"]
        end_dt   = datetime.fromtimestamp(expires_at, tz=TZ)
        end_str  = end_dt.strftime("%H:%M")
        bot.edit_message_text(
            f"✅ Твой токен ({shift_label}):\n\n"
            f"<code>{token}</code>\n\n"
            f"⏱ Действует до <b>{end_str}</b>\n"
            f"📋 Нажми на код чтобы скопировать",
            call.message.chat.id,
            call.message.message_id
        )
        notify_admins(
            f"🔑 <b>Новый токен</b>\n\n"
            f"👤 {fname} (@{uname})\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"⏰ Смена: {shift_label}\n"
            f"⏱ До: {end_str}"
        )
    elif data.get("error") == "blocked":
        bot.edit_message_text("🚫 Твой доступ заблокирован. Обратись к администратору.",
                              call.message.chat.id, call.message.message_id)
    else:
        # Скорее всего нет подписки
        bot.edit_message_text(
            "❌ У тебя нет активной подписки.\n\n"
            "Запроси её командой /subscribe",
            call.message.chat.id, call.message.message_id
        )

# ─── /admin ───────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["admin"])
def cmd_admin(msg: Message):
    if not is_admin(msg):
        bot.send_message(msg.chat.id, "⛔ Нет доступа.")
        return

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("👥 Активные токены", callback_data="admin_tokens"))
    markup.row(InlineKeyboardButton("📩 Заявки на подписку", callback_data="admin_subs"))
    markup.row(InlineKeyboardButton("📦 Статус загрузок", callback_data="admin_downloads"))
    markup.row(InlineKeyboardButton("🗓 Выдать месячный токен", callback_data="admin_grant_monthly"))
    markup.row(InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="admin_block_ask"))
    markup.row(InlineKeyboardButton("✅ Разблокировать", callback_data="admin_unblock_ask"))

    bot.send_message(msg.chat.id, "👑 <b>Панель администратора</b>", reply_markup=markup)

# ─── Callback: активные токены ────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_tokens")
def cb_admin_tokens(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    data = api("active_tokens")
    tokens = data.get("tokens", [])

    if not tokens:
        bot.edit_message_text("👥 Нет активных токенов.", call.message.chat.id, call.message.message_id)
        return

    markup = InlineKeyboardMarkup()
    lines  = ["👥 <b>Активные токены:</b>\n"]

    for t in tokens:
        uid   = t["user_id"]
        uname = t.get("username") or "—"
        fname = t.get("first_name") or "—"
        token = t["token"]
        shift = t.get("shift") or "—"
        end   = datetime.fromtimestamp(t["expires_at"], tz=TZ).strftime("%d.%m %H:%M")
        lines.append(f"• <b>{fname}</b> (@{uname}) | {shift} | до {end}\n  <code>{token}</code>")
        markup.row(InlineKeyboardButton(f"❌ Отозвать у {fname}", callback_data=f"revoke_{uid}"))

    markup.row(InlineKeyboardButton("🔄 Обновить", callback_data="admin_tokens"))
    markup.row(InlineKeyboardButton("◀️ Назад", callback_data="admin_back"))

    bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id,
                          reply_markup=markup)

# ─── Callback: заявки на подписку ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_subs")
def cb_admin_subs(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    data = api("pending_subs")
    reqs = data.get("requests", [])

    if not reqs:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("◀️ Назад", callback_data="admin_back"))
        bot.edit_message_text("📩 Нет новых заявок.", call.message.chat.id, call.message.message_id,
                              reply_markup=markup)
        return

    markup = InlineKeyboardMarkup()
    lines  = ["📩 <b>Заявки на подписку:</b>\n"]

    for r in reqs:
        uid   = r["user_id"]
        uname = r.get("username") or "—"
        fname = r.get("first_name") or "—"
        dt    = datetime.fromtimestamp(r["requested_at"], tz=TZ).strftime("%d.%m %H:%M")
        lines.append(f"• <b>{fname}</b> (@{uname}) — {dt}")
        markup.row(
            InlineKeyboardButton(f"✅ {fname}", callback_data=f"approve_{uid}"),
            InlineKeyboardButton(f"❌ Отклонить", callback_data=f"deny_{uid}")
        )

    markup.row(InlineKeyboardButton("◀️ Назад", callback_data="admin_back"))
    bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id,
                          reply_markup=markup)

# ─── Callback: одобрить / отклонить подписку ──────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("approve_monthly_"))
def cb_approve_monthly(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    uid = call.data.split("approve_monthly_", 1)[1]
    _grant_monthly_token(call, uid)


def _grant_monthly_token(call: CallbackQuery, uid: str):
    """Выдаёт месячный токен пользователю и уведомляет его."""
    uname = ""
    fname = uid
    expires_at = admin_monthly_expires()
    data = api("generate", user_id=uid, expires_at=expires_at,
               shift="monthly", username=uname, first_name=fname)
    if data.get("ok"):
        token = data["token"]
        now = now_kyiv()
        if now.month == 12:
            end_str = f"1 января {now.year+1}"
        else:
            import calendar
            end_str = f"1 {['','янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'][now.month+1]} {now.year}"
        bot.answer_callback_query(call.id, "✅ Месячный токен выдан")
        try:
            bot.send_message(int(uid),
                f"✅ <b>Тебе выдан месячный токен!</b>\n\n"
                f"<code>{token}</code>\n\n"
                f"📅 Действует до: <b>{end_str}</b>\n"
                f"📋 Нажми на код чтобы скопировать"
            )
        except Exception:
            pass
        try:
            bot.edit_message_text(
                call.message.text + f"\n\n✅ Выдан месячный токен",
                call.message.chat.id, call.message.message_id
            )
        except Exception:
            pass
    else:
        bot.answer_callback_query(call.id, f"Ошибка: {data.get('error')}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("approve_") or c.data.startswith("deny_"))
def cb_sub_decision(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    approve = call.data.startswith("approve_")
    uid     = call.data.split("_", 1)[1]

    data = api("approve_sub", user_id=uid, approve=approve)
    if data.get("ok"):
        if approve:
            bot.answer_callback_query(call.id, "✅ Подписка одобрена")
            try:
                bot.send_message(int(uid),
                    "✅ Твоя подписка одобрена!\n"
                    "Теперь можешь получить токен: /token"
                )
            except Exception:
                pass
        else:
            bot.answer_callback_query(call.id, "❌ Отклонено")
            try:
                bot.send_message(int(uid), "❌ Твоя заявка на подписку отклонена.")
            except Exception:
                pass

        try:
            bot.edit_message_text(
                call.message.text + f"\n\n{'✅ Одобрено' if approve else '❌ Отклонено'}",
                call.message.chat.id, call.message.message_id
            )
        except Exception:
            pass
    else:
        bot.answer_callback_query(call.id, f"Ошибка: {data.get('error')}")

# ─── Callback: отозвать токен ─────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("revoke_"))
def cb_revoke(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    uid  = call.data.split("_", 1)[1]
    data = api("revoke", user_id=uid)

    if data.get("ok"):
        bot.answer_callback_query(call.id, "✅ Токен отозван")
        try:
            bot.send_message(int(uid), "🔒 Твой токен был отозван администратором.")
        except Exception:
            pass
        # Обновляем список
        cb_admin_tokens(call)
    else:
        bot.answer_callback_query(call.id, f"Ошибка: {data.get('error')}")

# ─── Callback: выдать месячный токен вручную ──────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_grant_monthly")
def cb_grant_monthly_ask(call: CallbackQuery):
    if not is_admin(call):
        return
    msg = bot.send_message(call.message.chat.id, "Введи ID пользователя для выдачи месячного токена:")
    bot.register_next_step_handler(msg, lambda m: do_grant_monthly(m, call))
    bot.answer_callback_query(call.id)

def do_grant_monthly(msg: Message, call: CallbackQuery):
    if not is_admin(msg):
        return
    uid = msg.text.strip()
    _grant_monthly_token(call, uid)

# ─── Callback: блок/анблок ────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data in ("admin_block_ask", "admin_unblock_ask"))
def cb_block_ask(call: CallbackQuery):
    if not is_admin(call):
        return
    action = "block" if call.data == "admin_block_ask" else "unblock"
    msg = bot.send_message(call.message.chat.id,
        f"Введи ID пользователя для {'блокировки' if action=='block' else 'разблокировки'}:")
    bot.register_next_step_handler(msg, lambda m: do_block(m, action))
    bot.answer_callback_query(call.id)

def do_block(msg: Message, action: str):
    if not is_admin(msg):
        return
    uid = msg.text.strip()
    blocked = 1 if action == "block" else 0
    data = api("block", user_id=uid, blocked=blocked)
    if data.get("ok"):
        label = "🚫 Заблокирован" if blocked else "✅ Разблокирован"
        bot.send_message(msg.chat.id, f"{label} пользователь <code>{uid}</code>")
        if blocked:
            try:
                bot.send_message(int(uid), "🚫 Твой доступ заблокирован администратором.")
            except Exception:
                pass
        else:
            try:
                bot.send_message(int(uid), "✅ Твой доступ восстановлен.")
            except Exception:
                pass
    else:
        bot.send_message(msg.chat.id, f"❌ Ошибка: {data.get('error')}")

# ─── Callback: назад в меню ───────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_back")
def cb_back(call: CallbackQuery):
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("👥 Активные токены", callback_data="admin_tokens"))
    markup.row(InlineKeyboardButton("📩 Заявки на подписку", callback_data="admin_subs"))
    markup.row(InlineKeyboardButton("📦 Статус загрузок", callback_data="admin_downloads"))
    markup.row(InlineKeyboardButton("🗓 Выдать месячный токен", callback_data="admin_grant_monthly"))
    markup.row(InlineKeyboardButton("🚫 Заблокировать пользователя", callback_data="admin_block_ask"))
    markup.row(InlineKeyboardButton("✅ Разблокировать", callback_data="admin_unblock_ask"))
    bot.edit_message_text("👑 <b>Панель администратора</b>",
                          call.message.chat.id, call.message.message_id, reply_markup=markup)

# ─── /getext — пользователь запрашивает расширение ───────────────────────────
@bot.message_handler(commands=["getext"])
def cmd_getext(msg: Message):

    uid   = str(msg.from_user.id)
    uname = msg.from_user.username or ""
    fname = msg.from_user.first_name or ""

    # Проверяем не скачал ли уже
    status_data = api("download_status")
    for item in status_data.get("downloads", []):
        if item["user_id"] == uid:
            if item["downloaded"]:
                return bot.send_message(msg.chat.id,
                    "✅ Ты уже скачал расширение.\n"
                    "Если нужна помощь с установкой — обратись к администратору.")
            else:
                return bot.send_message(msg.chat.id,
                    "⏳ Твой запрос уже отправлен — ожидай одобрения администратора.")

    # Уведомляем всех админов
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Выдать расширение", callback_data=f"giveext_{uid}"),
        InlineKeyboardButton("❌ Отказать",          callback_data=f"denyext_{uid}")
    )
    notify_admins(
        f"📦 <b>Запрос на расширение</b>\n\n"
        f"👤 {fname} (@{uname})\n"
        f"🆔 ID: <code>{uid}</code>",
        markup
    )
    bot.send_message(msg.chat.id,
        "📨 Запрос отправлен администратору!\n"
        "Как только одобрят — получишь ссылку для скачивания.")


@bot.callback_query_handler(func=lambda c: c.data.startswith("giveext_") or c.data.startswith("denyext_"))
def cb_ext_decision(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    approve = call.data.startswith("giveext_")
    uid     = call.data.split("_", 1)[1]

    if not approve:
        bot.answer_callback_query(call.id, "❌ Отказано")
        try:
            bot.send_message(int(uid), "❌ Администратор отклонил твой запрос на расширение.")
        except Exception:
            pass
        try:
            bot.edit_message_text(call.message.text + "\n\n❌ Отказано",
                                  call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return

    # Одобряем — отправляем ZIP файлом напрямую в Telegram
    zip_path = os.path.join(os.path.dirname(__file__), "extension.zip")
    if not os.path.exists(zip_path):
        return bot.answer_callback_query(call.id, "❌ Файл extension.zip не найден в папке бота")

    # Отмечаем в БД что выдали
    api("create_download", user_id=uid)

    try:
        bot.send_message(int(uid),
            "✅ <b>Твой запрос одобрен!</b>\n\n"
            "Сейчас пришлю файл расширения 👇"
        )
        with open(zip_path, "rb") as f:
            bot.send_document(int(uid), f,
                caption=(
                    "📦 <b>TTS расширение для Chrome</b>\n\n"
                    "<b>Как установить:</b>\n"
                    "1. Распакуй ZIP архив\n"
                    "2. Открой <code>chrome://extensions</code>\n"
                    "3. Включи <b>Режим разработчика</b> (справа вверху)\n"
                    "4. Нажми <b>Загрузить распакованное</b> → выбери папку <code>tts-ext</code>\n\n"
                    "Затем иди на alpha.date и нажми зелёную кнопку 🗣"
                ),
                visible_file_name="tts-extension.zip"
            )
        bot.send_message(int(uid),
            "✅ После установки расширения получи токен командой /token"
        )

        bot.answer_callback_query(call.id, "✅ Файл отправлен")
        try:
            bot.edit_message_text(call.message.text + "\n\n✅ Расширение выдано",
                                  call.message.chat.id, call.message.message_id)
        except Exception:
            pass
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка отправки: {e}")


# ─── /sendext — отправить ссылку на расширение пользователю ──────────────────
@bot.message_handler(commands=["sendext"])
def cmd_sendext(msg: Message):
    if not is_admin(msg):
        return bot.send_message(msg.chat.id, "⛔ Нет доступа.")

    parts = msg.text.strip().split()
    if len(parts) < 2:
        return bot.send_message(msg.chat.id,
            "Использование: /sendext <user_id>\nПример: /sendext 123456789")

    target_uid = parts[1].strip()
    data = api("create_download", user_id=target_uid)

    if data.get("ok"):
        link = data["link"]
        # Отправляем ссылку пользователю
        try:
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("📥 Скачать расширение", url=link))
            bot.send_message(int(target_uid),
                "📦 <b>Расширение TTS для alpha.date</b>\n\n"
                "Нажми кнопку ниже чтобы скачать.\n"
                "⚠️ Ссылка одноразовая — скачай сразу!\n\n"
                "После скачивания:\n"
                "1. Распакуй ZIP\n"
                "2. Открой chrome://extensions\n"
                "3. Включи 'Режим разработчика'\n"
                "4. Нажми 'Загрузить распакованное' → выбери папку",
                reply_markup=markup
            )
            bot.send_message(msg.chat.id, f"✅ Ссылка отправлена пользователю <code>{target_uid}</code>")
        except Exception as e:
            bot.send_message(msg.chat.id, f"❌ Не удалось отправить: {e}\n\nСсылка: {link}")
    else:
        bot.send_message(msg.chat.id, f"❌ Ошибка: {data.get('error')}")


# ─── Callback: пользователь подтвердил скачивание ────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("dl_confirm_"))
def cb_dl_confirm(call: CallbackQuery):
    parts = call.data.split("_")
    # dl_confirm_{uid}_{doc_msg_id}
    uid        = parts[2]
    doc_msg_id = int(parts[3]) if len(parts) > 3 else None

    if str(call.from_user.id) != uid:
        return bot.answer_callback_query(call.id, "Это не твоя кнопка.")

    api("create_download", user_id=uid)

    bot.answer_callback_query(call.id, "✅ Отмечено!")
    try:
        # Удаляем ZIP сообщение
        if doc_msg_id:
            bot.delete_message(call.message.chat.id, doc_msg_id)
        # Удаляем сообщение с кнопкой
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id,
            "✅ Готово! Теперь установи расширение и используй /token чтобы получить код.")
    except Exception:
        pass


# ─── Callback: статус загрузок ────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "admin_downloads")
def cb_admin_downloads(call: CallbackQuery):
    if not is_admin(call):
        return bot.answer_callback_query(call.id, "Нет доступа")

    data = api("download_status")
    items = data.get("downloads", [])

    if not items:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("◀️ Назад", callback_data="admin_back"))
        bot.edit_message_text("📦 Нет данных о загрузках.",
                              call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    lines = ["📦 <b>Статус загрузок расширения:</b>\n"]
    for item in items:
        uid   = item["user_id"]
        fname = item.get("first_name") or "—"
        uname = item.get("username") or "—"
        if item["downloaded"]:
            dt = datetime.fromtimestamp(item["downloaded_at"], tz=TZ).strftime("%d.%m %H:%M")
            status = f"✅ Скачал ({dt})"
        else:
            status = "⏳ Ещё не скачал"
        lines.append(f"• <b>{fname}</b> (@{uname}) — {status}")

    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🔄 Обновить", callback_data="admin_downloads"))
    markup.row(InlineKeyboardButton("◀️ Назад", callback_data="admin_back"))

    bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id,
                          reply_markup=markup)


# ─── Запуск ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 Бот запущен...")
    bot.infinity_polling()
