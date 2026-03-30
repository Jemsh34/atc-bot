import logging
import os
import json
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

# ========================
# НАСТРОЙКИ ПОДКЛЮЧЕНИЯ
# ========================

# ID вашей Google Таблицы — берётся из ссылки:
# https://docs.google.com/spreadsheets/d/  ВОТ_ЭТОТ_ID  /edit
SPREADSHEET_ID = "1CxGkQAFbCnk3QO00zQr-HQyW95heLoVBDpmlccGXnJY"

# ========================
# ЗАГРУЗКА ДАННЫХ ИЗ GOOGLE SHEETS
# ========================

def get_sheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    # Сначала пробуем переменную окружения GOOGLE_CREDENTIALS (для Railway)
    # Если её нет — читаем локальный файл service_account.json (для локального запуска)
    google_creds_env = os.environ.get("GOOGLE_CREDENTIALS")
    if google_creds_env:
        google_creds_env = google_creds_env.replace("\n", "\\n")
        creds_info = json.loads(google_creds_env)
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(creds)


def parse_bool(val):
    """Конвертирует любое представление булева значения из таблицы."""
    return str(val).strip().lower() in ("true", "да", "1", "yes")


def parse_spec_ids(val):
    """
    Парсит поле specialty_id, которое может содержать одно или несколько
    направлений, разделённых точкой: '5.4' → [5, 4], '2' → [2].
    """
    if val is None or str(val).strip() == "":
        return []
    return [int(float(x)) for x in str(val).split(".") if x.strip()]


def load_data_from_sheets():
    """
    Загружает все данные из Google Таблицы.

    Листы и их структура:
      настройки   : Параметр | Значение | Описание
      города      : id | name | is_active
      клиники     : id | city_id | name | address | is_active
      направления : id | name | sort_order | is_active
      врачи       : id | full_name | specialty_id | price | is_online | is_offline |
                    is_question | is_callback | telegram_link | is_active | card_text
      врач-клиника: id | doctor_id | clinic_id | is_active | Примечание
    """
    client      = get_sheet_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # --- настройки ---
    rows     = spreadsheet.worksheet("настройки").get_all_records()
    settings = {r["Параметр"]: r["Значение"] for r in rows}

    # --- города ---
    rows   = spreadsheet.worksheet("города").get_all_records()
    cities = [
        {"id": int(r["id"]), "name": r["name"]}
        for r in rows if parse_bool(r.get("is_active"))
    ]

    # --- клиники ---
    rows    = spreadsheet.worksheet("клиники").get_all_records()
    clinics = [
        {
            "id":      int(r["id"]),
            "city_id": int(r["city_id"]),
            "name":    r["name"],
            "address": r["address"],
        }
        for r in rows if parse_bool(r.get("is_active"))
    ]

    # --- направления (специальности), сортируем по sort_order ---
    rows        = spreadsheet.worksheet("направления").get_all_records()
    specialties = sorted(
        [
            {
                "id":   int(r["id"]),
                "name": r["name"],
                "sort": int(r.get("sort_order") or 99),
            }
            for r in rows if parse_bool(r.get("is_active"))
        ],
        key=lambda x: x["sort"]
    )

    # --- врачи ---
    # specialty_id может быть '5.4' — врач относится сразу к направлениям 5 и 4
    rows    = spreadsheet.worksheet("врачи").get_all_records()
    doctors = [
        {
            "id":       int(r["id"]),
            "name":     r["full_name"],
            "spec_ids": parse_spec_ids(r.get("specialty_id")),
            "price":    int(r["price"]),
            "online":   parse_bool(r.get("is_online")),
            "offline":  parse_bool(r.get("is_offline")),
            "question": parse_bool(r.get("is_question")),
            "callback": parse_bool(r.get("is_callback")),
            "link":     r.get("telegram_link") or None,
            "card":     r.get("card_text", ""),
            "clinics":  [],  # заполняется ниже из листа врач-клиника
        }
        for r in rows
        if r.get("id") and parse_bool(r.get("is_active"))
    ]

    # --- врач-клиника (many-to-many) ---
    rows         = spreadsheet.worksheet("врач-клиника").get_all_records()
    doctor_by_id = {d["id"]: d for d in doctors}
    for r in rows:
        if not parse_bool(r.get("is_active")):
            continue
        doc_id    = int(r["doctor_id"])
        clinic_id = int(r["clinic_id"])
        if doc_id in doctor_by_id:
            doctor_by_id[doc_id]["clinics"].append(clinic_id)

    return {
        "settings":    settings,
        "cities":      cities,
        "clinics":     clinics,
        "specialties": specialties,
        "doctors":     doctors,
    }


# Глобальный кэш — загружается при старте, обновляется по /reload
_CACHE = {}

def reload_data():
    global _CACHE
    _CACHE = load_data_from_sheets()
    logging.info("✅ Данные из Google Sheets загружены")

def get(key):
    return _CACHE.get(key, [])

def get_settings():
    return _CACHE.get("settings", {})


# ========================
# СОСТОЯНИЯ
# ========================
(
    MAIN_MENU,
    CHOOSE_CITY,
    CHOOSE_CLINIC,
    CHOOSE_SPECIALTY,
    CHOOSE_DOCTOR,
    CHOOSE_ACTION,
    COLLECT_NAME,
    COLLECT_PHONE,
    COLLECT_BIRTH,
    COLLECT_DATETIME,
    CONFIRM,
    ASK_QUESTION_TEXT,
    CALLBACK_NAME,
    CALLBACK_PHONE,
) = range(14)

logging.basicConfig(level=logging.INFO)

# ========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================

async def delete_last(context, chat_id):
    msg_id = context.user_data.get("last_bot_msg")
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

async def send_and_save(update, context, text, keyboard, parse_mode=None):
    chat_id = update.effective_chat.id
    await delete_last(context, chat_id)
    try:
        await update.message.delete()
    except Exception:
        pass
    kwargs = {"chat_id": chat_id, "text": text, "reply_markup": keyboard}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    sent = await context.bot.send_message(**kwargs)
    context.user_data["last_bot_msg"] = sent.message_id
    return sent

def make_inline(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d)] for t, d in rows])

def make_inline_cols(items, cols=1):
    buttons = [InlineKeyboardButton(t, callback_data=d) for t, d in items]
    rows    = [buttons[i:i+cols] for i in range(0, len(buttons), cols)]
    rows.append([
        InlineKeyboardButton("◀️ Назад", callback_data="back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="home"),
    ])
    return InlineKeyboardMarkup(rows)

def nav_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Назад", callback_data="back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="home"),
    ]])

async def edit_or_send(update, context, text, keyboard, parse_mode=None):
    query = update.callback_query
    if query:
        await query.answer()
        try:
            kwargs = {"text": text, "reply_markup": keyboard}
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await query.edit_message_text(**kwargs)
            context.user_data["last_bot_msg"] = query.message.message_id
            return
        except Exception:
            pass
    chat_id = update.effective_chat.id
    await delete_last(context, chat_id)
    kwargs = {"chat_id": chat_id, "text": text, "reply_markup": keyboard}
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    sent = await context.bot.send_message(**kwargs)
    context.user_data["last_bot_msg"] = sent.message_id

# ========================
# ГЛАВНОЕ МЕНЮ
# ========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    try:
        await update.message.delete()
    except Exception:
        pass

    welcome  = get_settings().get("WELCOME_TEXT", "👋 Добро пожаловать!\n\nВыберите тип приёма:")
    keyboard = make_inline([
        ("🖥 Онлайн консультация", "type_online"),
        ("🏥 Запись в клинику",    "type_offline"),
        ("💬 Задать вопрос врачу", "type_question"),
        ("📞 Обратный звонок",     "type_callback"),
    ])
    sent = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=welcome, reply_markup=keyboard
    )
    context.user_data["last_bot_msg"] = sent.message_id
    return MAIN_MENU


async def show_main_menu(update, context):
    keyboard = make_inline([
        ("🖥 Онлайн консультация", "type_online"),
        ("🏥 Запись в клинику",    "type_offline"),
        ("💬 Задать вопрос врачу", "type_question"),
        ("📞 Обратный звонок",     "type_callback"),
    ])
    await edit_or_send(update, context, "🏠 Главное меню\n\nВыберите тип приёма:", keyboard)
    return MAIN_MENU


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reload — перезагружает данные из таблицы."""
    try:
        reload_data()
        await update.message.reply_text("✅ Данные из Google Sheets успешно обновлены!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка загрузки данных:\n{e}")

# ========================
# ВЫБОР ТИПА ПРИЁМА
# ========================

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)

    if data == "type_online":
        context.user_data["visit_type"]  = "online"
        context.user_data["visit_label"] = "Онлайн консультация"
        return await show_specialties(update, context)
    elif data == "type_offline":
        context.user_data["visit_type"]  = "offline"
        context.user_data["visit_label"] = "Запись в клинику"
        return await show_cities(update, context)
    elif data == "type_question":
        context.user_data["visit_type"] = "question"
        return await show_specialties_for_question(update, context)
    elif data == "type_callback":
        context.user_data["visit_type"] = "callback"
        return await show_specialties_for_callback(update, context)

# ========================
# ГОРОДА / КЛИНИКИ (офлайн)
# ========================

async def show_cities(update, context):
    items    = [(c["name"], f"city_{c['id']}") for c in get("cities")]
    keyboard = make_inline_cols(items)
    await edit_or_send(update, context, "🌆 Выберите город:", keyboard)
    return CHOOSE_CITY


async def handle_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_main_menu(update, context)

    city_id = int(data.replace("city_", ""))
    city    = next((c for c in get("cities") if c["id"] == city_id), None)
    context.user_data["city_id"]   = city_id
    context.user_data["city_name"] = city["name"] if city else ""
    return await show_clinics(update, context)


async def show_clinics(update, context):
    city_id  = context.user_data.get("city_id")
    clinics  = [c for c in get("clinics") if c["city_id"] == city_id]
    items    = [(c["name"], f"clinic_{c['id']}") for c in clinics]
    keyboard = make_inline_cols(items)
    await edit_or_send(
        update, context,
        f"🏥 Город: {context.user_data.get('city_name', '')}\n\nВыберите клинику:",
        keyboard
    )
    return CHOOSE_CLINIC


async def handle_clinic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_cities(update, context)

    clinic_id = int(data.replace("clinic_", ""))
    clinic    = next((c for c in get("clinics") if c["id"] == clinic_id), None)
    if clinic:
        context.user_data["clinic_id"]   = clinic_id
        context.user_data["clinic_name"] = clinic["name"]
        context.user_data["clinic_addr"] = clinic["address"]
    return await show_specialties(update, context)

# ========================
# СПЕЦИАЛЬНОСТИ
# ========================

def _available_specialties(visit_type, clinic_id=None):
    """Возвращает направления, по которым есть подходящие врачи."""
    available_spec_ids = set()
    for d in get("doctors"):
        if visit_type == "online" and not d["online"]:
            continue
        if visit_type == "offline":
            if not d["offline"]:
                continue
            if clinic_id and clinic_id not in d["clinics"]:
                continue
        available_spec_ids.update(d["spec_ids"])
    return [s for s in get("specialties") if s["id"] in available_spec_ids]


async def show_specialties(update, context):
    visit_type = context.user_data.get("visit_type")
    clinic_id  = context.user_data.get("clinic_id")
    specs      = _available_specialties(visit_type, clinic_id)
    items      = [(s["name"], f"spec_{s['id']}") for s in specs]
    keyboard   = make_inline_cols(items)
    await edit_or_send(update, context, "🩺 Выберите специализацию:", keyboard)
    return CHOOSE_SPECIALTY


async def handle_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        if context.user_data.get("visit_type") == "offline":
            return await show_clinics(update, context)
        return await show_main_menu(update, context)

    spec_id  = int(data.replace("spec_", ""))
    spec     = next((s for s in get("specialties") if s["id"] == spec_id), None)
    context.user_data["spec_id"]   = spec_id
    context.user_data["spec_name"] = spec["name"] if spec else ""
    return await show_doctors(update, context)

# ========================
# ВРАЧИ
# ========================

async def show_doctors(update, context):
    visit_type = context.user_data.get("visit_type")
    spec_id    = context.user_data.get("spec_id")
    clinic_id  = context.user_data.get("clinic_id")

    filtered = []
    for d in get("doctors"):
        if spec_id not in d["spec_ids"]:
            continue
        if visit_type == "online" and not d["online"]:
            continue
        if visit_type == "offline":
            if not d["offline"]:
                continue
            if clinic_id and clinic_id not in d["clinics"]:
                continue
        filtered.append(d)

    if not filtered:
        await edit_or_send(
            update, context,
            "😔 В данной специализации нет доступных врачей.\n\nВыберите другую.",
            nav_keyboard()
        )
        return CHOOSE_SPECIALTY

    items    = [(f"👨‍⚕️ {d['name']}", f"doc_{d['id']}") for d in filtered]
    keyboard = make_inline_cols(items)
    await edit_or_send(
        update, context,
        f"🩺 {context.user_data.get('spec_name', '')}\n\nВыберите врача:",
        keyboard
    )
    return CHOOSE_DOCTOR


async def handle_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_specialties(update, context)

    doc_id = int(data.replace("doc_", ""))
    doctor = next((d for d in get("doctors") if d["id"] == doc_id), None)
    if not doctor:
        return CHOOSE_DOCTOR

    context.user_data["doctor"] = doctor
    visit_type = context.user_data.get("visit_type")

    card = doctor["card"] or doctor["name"]
    text = card + f"\n\n💰 <b>Стоимость консультации: {doctor['price']} ₽</b>\n\nВыберите действие:"

    actions = []
    if visit_type == "online"  and doctor["online"]:
        actions.append(("📅 Записаться на консультацию", "action_book"))
    if visit_type == "offline" and doctor["offline"]:
        actions.append(("📅 Записаться в клинику", "action_book"))
    if doctor["link"]:
        actions.append(("💬 Написать врачу", "action_write"))
    actions += [("◀️ Назад", "back"), ("🏠 Главное меню", "home")]

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d)] for t, d in actions]
    )
    await edit_or_send(update, context, text, keyboard, parse_mode="HTML")
    return CHOOSE_ACTION

# ========================
# ДЕЙСТВИЯ С ВРАЧОМ
# ========================

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_doctors(update, context)

    doctor = context.user_data.get("doctor", {})

    if data == "action_write":
        await edit_or_send(
            update, context,
            f"💬 Напишите врачу напрямую:\n{doctor.get('link')}",
            nav_keyboard()
        )
        return CHOOSE_ACTION

    if data == "action_book":
        await edit_or_send(update, context, "📝 Введите ваше ФИО:", nav_keyboard())
        return COLLECT_NAME

# ========================
# СБОР ДАННЫХ ДЛЯ ЗАПИСИ
# ========================

async def collect_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            return await handle_doctor(update, context)
        return COLLECT_NAME

    context.user_data["patient_name"] = update.message.text.strip()
    await send_and_save(update, context, "📱 Введите ваш номер телефона:", nav_keyboard())
    return COLLECT_PHONE


async def collect_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            await edit_or_send(update, context, "📝 Введите ваше ФИО:", nav_keyboard())
            return COLLECT_NAME
        return COLLECT_PHONE

    context.user_data["phone"] = update.message.text.strip()
    await send_and_save(update, context, "🎂 Введите дату рождения (например: 15.03.1990):", nav_keyboard())
    return COLLECT_BIRTH


async def collect_birth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            await edit_or_send(update, context, "📱 Введите номер телефона:", nav_keyboard())
            return COLLECT_PHONE
        return COLLECT_BIRTH

    context.user_data["birth"] = update.message.text.strip()
    await send_and_save(
        update, context,
        "📅 Укажите удобную дату и время (например: 10.04.2025 в 14:00):",
        nav_keyboard()
    )
    return COLLECT_DATETIME


async def collect_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            await edit_or_send(update, context, "🎂 Введите дату рождения:", nav_keyboard())
            return COLLECT_BIRTH
        return COLLECT_DATETIME

    context.user_data["appt_datetime"] = update.message.text.strip()
    return await show_confirm(update, context)


async def show_confirm(update, context):
    d      = context.user_data
    doctor = d.get("doctor", {})
    text   = (
        f"📋 <b>Проверьте данные записи:</b>\n\n"
        f"🏥 Тип: {d.get('visit_label', '—')}\n"
        f"🌆 Город: {d.get('city_name', 'Онлайн')}\n"
        f"🏨 Клиника: {d.get('clinic_name', 'Онлайн')}\n"
        f"🩺 Специализация: {d.get('spec_name', '—')}\n"
        f"👨‍⚕️ Врач: {doctor.get('name', '—')}\n"
        f"💰 Стоимость: {doctor.get('price', '—')} ₽\n\n"
        f"👤 ФИО: {d.get('patient_name', '—')}\n"
        f"📱 Телефон: {d.get('phone', '—')}\n"
        f"🎂 Дата рождения: {d.get('birth', '—')}\n"
        f"📅 Дата/время: {d.get('appt_datetime', '—')}\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back"),
         InlineKeyboardButton("🏠 Главное меню", callback_data="home")],
    ])
    await edit_or_send(update, context, text, keyboard, parse_mode="HTML")
    return CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        await edit_or_send(update, context, "📅 Введите дату и время приёма:", nav_keyboard())
        return COLLECT_DATETIME

    if data == "confirm_yes":
        user     = query.from_user
        d        = context.user_data
        doctor   = d.get("doctor", {})
        admin_id = int(get_settings().get("ADMIN_GROUP_ID", 0))

        msg = (
            f"🆕 <b>Новая запись на приём!</b>\n\n"
            f"🏥 Тип: {d.get('visit_label', '—')}\n"
            f"🌆 Город: {d.get('city_name', 'Онлайн')}\n"
            f"🏨 Клиника: {d.get('clinic_name', 'Онлайн')}\n"
            f"🩺 Специализация: {d.get('spec_name', '—')}\n"
            f"👨‍⚕️ Врач: {doctor.get('name', '—')}\n"
            f"💰 Стоимость: {doctor.get('price', '—')} ₽\n\n"
            f"👤 ФИО пациента: {d.get('patient_name', '—')}\n"
            f"📱 Телефон: {d.get('phone', '—')}\n"
            f"🎂 Дата рождения: {d.get('birth', '—')}\n"
            f"📅 Дата/время: {d.get('appt_datetime', '—')}\n\n"
            f"💬 Telegram: @{user.username or 'нет'} (ID: <code>{user.id}</code>)\n"
            f"✅ Статус: новая запись"
        )
        await context.bot.send_message(admin_id, msg, parse_mode="HTML")

        bot_name = get_settings().get("BOT_NAME", "нашу клинику")
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]]
        )
        await edit_or_send(
            update, context,
            f"✅ <b>Ваша запись принята!</b>\n\n"
            f"Администратор свяжется с вами для подтверждения.\n\n"
            f"Спасибо, что выбрали {bot_name}! 🏥",
            keyboard, parse_mode="HTML"
        )
        context.user_data.clear()
        return MAIN_MENU

# ========================
# ЗАДАТЬ ВОПРОС ВРАЧУ
# ========================

async def show_specialties_for_question(update, context):
    available = {sid for d in get("doctors") if d["question"] for sid in d["spec_ids"]}
    items     = [(s["name"], f"qspec_{s['id']}") for s in get("specialties") if s["id"] in available]
    keyboard  = make_inline_cols(items)
    await edit_or_send(update, context, "💬 Выберите специализацию врача:", keyboard)
    return CHOOSE_SPECIALTY


async def handle_question_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_main_menu(update, context)

    spec_id  = int(data.replace("qspec_", ""))
    spec     = next((s for s in get("specialties") if s["id"] == spec_id), None)
    context.user_data["spec_id"]   = spec_id
    context.user_data["spec_name"] = spec["name"] if spec else ""

    doctors  = [d for d in get("doctors") if spec_id in d["spec_ids"] and d["question"]]
    items    = [(f"👨‍⚕️ {d['name']}", f"qdoc_{d['id']}") for d in doctors]
    keyboard = make_inline_cols(items)
    await edit_or_send(update, context, "👨‍⚕️ Выберите врача:", keyboard)
    return CHOOSE_DOCTOR


async def handle_question_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_specialties_for_question(update, context)

    doc_id = int(data.replace("qdoc_", ""))
    doctor = next((d for d in get("doctors") if d["id"] == doc_id), None)
    context.user_data["doctor"] = doctor

    await edit_or_send(
        update, context,
        f"✍️ Напишите ваш вопрос для врача <b>{doctor['name']}</b>:",
        nav_keyboard(), parse_mode="HTML"
    )
    return ASK_QUESTION_TEXT


async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            return await show_specialties_for_question(update, context)
        return ASK_QUESTION_TEXT

    question = update.message.text.strip()
    user     = update.message.from_user
    doctor   = context.user_data.get("doctor", {})
    admin_id = int(get_settings().get("ADMIN_GROUP_ID", 0))

    msg = (
        f"❓ <b>Вопрос врачу</b>\n\n"
        f"👨‍⚕️ Врач: {doctor.get('name', '—')}\n\n"
        f"💬 Вопрос: {question}\n\n"
        f"👤 От: @{user.username or 'нет'} (ID: <code>{user.id}</code>)"
    )
    await context.bot.send_message(admin_id, msg, parse_mode="HTML")

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]]
    )
    await send_and_save(
        update, context,
        "✅ Ваш вопрос отправлен врачу!\n\nМы свяжемся с вами в ближайшее время.",
        keyboard
    )
    context.user_data.clear()
    return MAIN_MENU

# ========================
# ОБРАТНЫЙ ЗВОНОК
# ========================

async def show_specialties_for_callback(update, context):
    available = {sid for d in get("doctors") if d["callback"] for sid in d["spec_ids"]}
    items     = [(s["name"], f"cbspec_{s['id']}") for s in get("specialties") if s["id"] in available]
    keyboard  = make_inline_cols(items)
    await edit_or_send(update, context, "📞 Выберите специализацию:", keyboard)
    return CHOOSE_SPECIALTY


async def handle_callback_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_main_menu(update, context)

    spec_id  = int(data.replace("cbspec_", ""))
    spec     = next((s for s in get("specialties") if s["id"] == spec_id), None)
    context.user_data["spec_id"]   = spec_id
    context.user_data["spec_name"] = spec["name"] if spec else ""

    doctors  = [d for d in get("doctors") if spec_id in d["spec_ids"] and d["callback"]]
    items    = [(f"👨‍⚕️ {d['name']}", f"cbdoc_{d['id']}") for d in doctors]
    keyboard = make_inline_cols(items)
    await edit_or_send(update, context, "👨‍⚕️ Выберите врача:", keyboard)
    return CHOOSE_DOCTOR


async def handle_callback_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_specialties_for_callback(update, context)

    doc_id = int(data.replace("cbdoc_", ""))
    doctor = next((d for d in get("doctors") if d["id"] == doc_id), None)
    context.user_data["doctor"] = doctor

    await edit_or_send(update, context, "📝 Введите ваше ФИО для обратного звонка:", nav_keyboard())
    return CALLBACK_NAME


async def callback_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            return await show_specialties_for_callback(update, context)
        return CALLBACK_NAME

    context.user_data["cb_name"] = update.message.text.strip()
    await send_and_save(update, context, "📱 Введите ваш номер телефона:", nav_keyboard())
    return CALLBACK_PHONE


async def callback_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "home":
            context.user_data.clear()
            return await show_main_menu(update, context)
        if query.data == "back":
            await edit_or_send(update, context, "📝 Введите ваше ФИО:", nav_keyboard())
            return CALLBACK_NAME
        return CALLBACK_PHONE

    phone    = update.message.text.strip()
    user     = update.message.from_user
    doctor   = context.user_data.get("doctor", {})
    admin_id = int(get_settings().get("ADMIN_GROUP_ID", 0))

    msg = (
        f"📞 <b>Запрос обратного звонка</b>\n\n"
        f"👨‍⚕️ Врач: {doctor.get('name', '—')}\n\n"
        f"👤 ФИО: {context.user_data.get('cb_name', '—')}\n"
        f"📱 Телефон: {phone}\n\n"
        f"💬 Telegram: @{user.username or 'нет'} (ID: <code>{user.id}</code>)"
    )
    await context.bot.send_message(admin_id, msg, parse_mode="HTML")

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]]
    )
    await send_and_save(
        update, context,
        "✅ Заявка на обратный звонок отправлена!\n\nМы перезвоним вам в ближайшее время.",
        keyboard
    )
    context.user_data.clear()
    return MAIN_MENU

# ========================
# ЗАПУСК
# ========================

def main():
    # Загружаем данные из таблицы перед стартом
    reload_data()

    bot_token = get_settings().get("BOT_TOKEN", "")
    if not bot_token:
        raise ValueError("BOT_TOKEN не найден в листе 'настройки'!")

    app = Application.builder().token(bot_token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(handle_main_menu)],
            CHOOSE_CITY: [CallbackQueryHandler(handle_city)],
            CHOOSE_CLINIC: [CallbackQueryHandler(handle_clinic)],
            CHOOSE_SPECIALTY: [
                CallbackQueryHandler(handle_specialty,          pattern="^spec_"),
                CallbackQueryHandler(handle_question_specialty, pattern="^qspec_"),
                CallbackQueryHandler(handle_callback_specialty, pattern="^cbspec_"),
                CallbackQueryHandler(handle_specialty,          pattern="^(back|home)$"),
            ],
            CHOOSE_DOCTOR: [
                CallbackQueryHandler(handle_doctor,          pattern="^doc_"),
                CallbackQueryHandler(handle_question_doctor, pattern="^qdoc_"),
                CallbackQueryHandler(handle_callback_doctor, pattern="^cbdoc_"),
                CallbackQueryHandler(handle_doctor,          pattern="^(back|home)$"),
            ],
            CHOOSE_ACTION: [CallbackQueryHandler(handle_action)],
            COLLECT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_name),
                CallbackQueryHandler(collect_name),
            ],
            COLLECT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_phone),
                CallbackQueryHandler(collect_phone),
            ],
            COLLECT_BIRTH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_birth),
                CallbackQueryHandler(collect_birth),
            ],
            COLLECT_DATETIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_datetime),
                CallbackQueryHandler(collect_datetime),
            ],
            CONFIRM: [CallbackQueryHandler(handle_confirm)],
            ASK_QUESTION_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question),
                CallbackQueryHandler(receive_question),
            ],
            CALLBACK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, callback_name),
                CallbackQueryHandler(callback_name),
            ],
            CALLBACK_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, callback_phone),
                CallbackQueryHandler(callback_phone),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("reload", reload_command))

    print("✅ Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
