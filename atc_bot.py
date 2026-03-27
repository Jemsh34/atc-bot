import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

# ========================
# НАСТРОЙКИ
# ========================
BOT_TOKEN = "8442363087:AAFGqS2UtqfF_H9sFVUFMy6lMv28rJ739Gc"
ADMIN_GROUP_ID = -5228416685

# ========================
# ДАННЫЕ ИЗ ТАБЛИЦ
# ========================

CITIES = ["Москва", "Ялта", "Севастополь"]

CLINICS = {
    "Ялта": [("1", "Еомед клиника", "Республика Крым, г. Ялта, ул. Прибрежная, д.17")],
    "Севастополь": [("2", "Еомед клиника", "Республика Крым г. Севастополь, пр-кт Октябрьской революции 48")],
    "Москва": [
        ("3", "АТС клиника", "МО, городской округ Красногорск, пос. Ильинское-Усово, ул. Заповедная, 21"),
        ("4", "Ильинская больница", "МО, городской округ Красногорск, дер. Глухово, ул. Рублёвское предместье, 2/2"),
    ],
}

SPECIALTIES = [
    (1, "Анестезиология и реаниматология"),
    (2, "Неврология и нейрохирургия"),
    (3, "Педиатрия"),
    (4, "Реабилитация и восстановление"),
    (5, "Терапия"),
]

# Врачи: id, имя, specialty_id, цена онлайн, онлайн, офлайн, вопрос, обратный звонок, ссылка
DOCTORS = [
    {"id": 1, "name": "Матвеева Ярослава Дмитриевна",   "spec_id": 3, "spec": "Педиатр",                        "price": 1900, "online": True,  "offline": False, "question": True,  "callback": True,  "link": "https://t.me/yaroslava_matveeva", "clinics": []},
    {"id": 2, "name": "Гусейнов Эльдар Ражидинович",    "spec_id": 5, "spec": "Терапевт, пульмонолог",          "price": 2000, "online": True,  "offline": True,  "question": True,  "callback": True,  "link": "https://t.me/guseynov_eldar",     "clinics": []},
    {"id": 3, "name": "Гуркина Мария Викторовна",        "spec_id": 4, "spec": "Реабилитолог, врач ЛФК",         "price": 2100, "online": True,  "offline": True,  "question": True,  "callback": True,  "link": "https://t.me/m_v_g_doc",         "clinics": ["4"]},
    {"id": 4, "name": "Торпанов Бронислав Русланович",   "spec_id": 2, "spec": "Нейрохирург",                    "price": 2200, "online": True,  "offline": False, "question": True,  "callback": True,  "link": "https://t.me/bronislauder",      "clinics": []},
    {"id": 5, "name": "Новиков Артём Сергеевич",         "spec_id": 1, "spec": "Анестезиолог-реаниматолог",      "price": 2300, "online": True,  "offline": False, "question": False, "callback": False, "link": None,                             "clinics": []},
    {"id": 6, "name": "Муравьев Ярослав Эдуардович",    "spec_id": 4, "spec": "Реабилитолог, терапевт",          "price": 2400, "online": True,  "offline": True,  "question": True,  "callback": True,  "link": "https://t.me/s_9779",            "clinics": ["3"]},
    {"id": 7, "name": "Цибулаев Андрей Александрович",  "spec_id": 2, "spec": "Нейрохирург",                    "price": 2500, "online": True,  "offline": True,  "question": True,  "callback": True,  "link": "https://t.me/andrey_tcibulaev",  "clinics": ["1", "2", "3"]},
]

SPEC_ID_TO_NAME = {s[0]: s[1] for s in SPECIALTIES}

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
    """Удаляет предыдущее сообщение бота"""
    msg_id = context.user_data.get("last_bot_msg")
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

async def send_and_save(update, context, text, keyboard, parse_mode=None):
    """Отправляет сообщение и сохраняет его ID, удаляя предыдущее"""
    chat_id = update.effective_chat.id
    await delete_last(context, chat_id)
    
    # Удаляем сообщение пользователя
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
    """Создаёт инлайн клавиатуру из списка [(text, callback_data)]"""
    keyboard = [[InlineKeyboardButton(t, callback_data=d)] for t, d in rows]
    return InlineKeyboardMarkup(keyboard)

def make_inline_cols(items, cols=2):
    """Создаёт инлайн клавиатуру в несколько колонок"""
    buttons = [InlineKeyboardButton(t, callback_data=d) for t, d in items]
    rows = [buttons[i:i+cols] for i in range(0, len(buttons), cols)]
    rows.append([
        InlineKeyboardButton("◀️ Назад", callback_data="back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="home"),
    ])
    return InlineKeyboardMarkup(rows)

def nav_keyboard(extra=None):
    """Навигационная клавиатура с кнопками назад/домой"""
    row = [
        InlineKeyboardButton("◀️ Назад", callback_data="back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="home"),
    ]
    buttons = []
    if extra:
        buttons.append([InlineKeyboardButton(t, callback_data=d) for t, d in extra])
    buttons.append(row)
    return InlineKeyboardMarkup(buttons)

async def edit_or_send(update, context, text, keyboard, parse_mode=None):
    """Редактирует текущее сообщение или отправляет новое"""
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
    # fallback — отправляем новое
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
    
    # Удаляем стартовую команду пользователя
    try:
        await update.message.delete()
    except Exception:
        pass

    text = (
        "👋 Добро пожаловать в АТС Клинику!\n\n"
        "Я помогу вам записаться к врачу или ответить на вопросы.\n\n"
        "Выберите тип приёма:"
    )
    keyboard = make_inline([
        ("🖥 Онлайн консультация", "type_online"),
        ("🏥 Запись в клинику", "type_offline"),
        ("💬 Задать вопрос врачу", "type_question"),
        ("📞 Обратный звонок", "type_callback"),
    ])
    chat_id = update.effective_chat.id
    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    context.user_data["last_bot_msg"] = sent.message_id
    return MAIN_MENU

async def show_main_menu(update, context):
    text = "🏠 Главное меню\n\nВыберите тип приёма:"
    keyboard = make_inline([
        ("🖥 Онлайн консультация", "type_online"),
        ("🏥 Запись в клинику", "type_offline"),
        ("💬 Задать вопрос врачу", "type_question"),
        ("📞 Обратный звонок", "type_callback"),
    ])
    await edit_or_send(update, context, text, keyboard)
    return MAIN_MENU

# ========================
# ВЫБОР ТИПА
# ========================

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)

    if data == "type_online":
        context.user_data["visit_type"] = "online"
        context.user_data["visit_label"] = "Онлайн консультация"
        return await show_specialties(update, context)

    elif data == "type_offline":
        context.user_data["visit_type"] = "offline"
        context.user_data["visit_label"] = "Запись в клинику"
        return await show_cities(update, context)

    elif data == "type_question":
        context.user_data["visit_type"] = "question"
        return await show_specialties_for_question(update, context)

    elif data == "type_callback":
        context.user_data["visit_type"] = "callback"
        return await show_specialties_for_callback(update, context)

# ========================
# ОНЛАЙН — СПЕЦИАЛЬНОСТИ
# ========================

async def show_specialties(update, context):
    visit_type = context.user_data.get("visit_type")
    
    # Фильтруем специальности по доступным врачам
    available_spec_ids = set()
    for d in DOCTORS:
        if visit_type == "online" and d["online"]:
            available_spec_ids.add(d["spec_id"])
        elif visit_type == "offline" and d["offline"]:
            available_spec_ids.add(d["spec_id"])

    items = [(name, f"spec_{sid}") for sid, name in SPECIALTIES if sid in available_spec_ids]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, "🩺 Выберите специализацию:", keyboard)
    return CHOOSE_SPECIALTY

async def handle_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        visit_type = context.user_data.get("visit_type")
        if visit_type == "offline":
            return await show_clinics(update, context)
        return await show_main_menu(update, context)

    spec_id = int(data.replace("spec_", ""))
    context.user_data["spec_id"] = spec_id
    context.user_data["spec_name"] = SPEC_ID_TO_NAME.get(spec_id, "")
    return await show_doctors(update, context)

# ========================
# ОФЛАЙН — ГОРОДА / КЛИНИКИ
# ========================

async def show_cities(update, context):
    items = [(c, f"city_{c}") for c in CITIES]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, "🌆 Выберите город:", keyboard)
    return CHOOSE_CITY

async def handle_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_main_menu(update, context)

    city = data.replace("city_", "")
    context.user_data["city"] = city
    return await show_clinics(update, context)

async def show_clinics(update, context):
    city = context.user_data.get("city", "")
    clinics = CLINICS.get(city, [])
    items = [(name, f"clinic_{cid}") for cid, name, _ in clinics]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, f"🏥 Город: {city}\n\nВыберите клинику:", keyboard)
    return CHOOSE_CLINIC

async def handle_clinic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_cities(update, context)

    clinic_id = data.replace("clinic_", "")
    city = context.user_data.get("city", "")
    for cid, name, addr in CLINICS.get(city, []):
        if cid == clinic_id:
            context.user_data["clinic_id"] = cid
            context.user_data["clinic_name"] = name
            context.user_data["clinic_addr"] = addr
            break
    return await show_specialties(update, context)

# ========================
# СПИСОК ВРАЧЕЙ
# ========================

async def show_doctors(update, context):
    visit_type = context.user_data.get("visit_type")
    spec_id = context.user_data.get("spec_id")
    clinic_id = context.user_data.get("clinic_id")

    filtered = []
    for d in DOCTORS:
        if d["spec_id"] != spec_id:
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
        keyboard = nav_keyboard()
        await edit_or_send(update, context, "😔 В данной специализации нет доступных врачей.\n\nВыберите другую специализацию.", keyboard)
        return CHOOSE_SPECIALTY

    items = [(f"👨‍⚕️ {d['name']}", f"doc_{d['id']}") for d in filtered]
    keyboard = make_inline_cols(items, cols=1)
    spec_name = context.user_data.get("spec_name", "")
    await edit_or_send(update, context, f"🩺 {spec_name}\n\nВыберите врача:", keyboard)
    return CHOOSE_DOCTOR

async def handle_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_specialties(update, context)

    doc_id = int(data.replace("doc_", ""))
    doctor = next((d for d in DOCTORS if d["id"] == doc_id), None)
    if not doctor:
        return CHOOSE_DOCTOR

    context.user_data["doctor"] = doctor

    # Показываем карточку врача с кнопками действий
    visit_type = context.user_data.get("visit_type")
    price = doctor["price"]

    text = (
        f"👨‍⚕️ <b>{doctor['name']}</b>\n"
        f"🩺 {doctor['spec']}\n"
        f"💰 Стоимость онлайн-консультации: <b>{price} ₽</b>\n\n"
        f"Выберите действие:"
    )

    actions = []
    if visit_type == "online" and doctor["online"]:
        actions.append(("📅 Записаться на консультацию", "action_book"))
    if visit_type == "offline" and doctor["offline"]:
        actions.append(("📅 Записаться в клинику", "action_book"))
    if doctor["link"]:
        actions.append((f"💬 Написать врачу", "action_write"))

    actions.append(("◀️ Назад", "back"))
    actions.append(("🏠 Главное меню", "home"))

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d)] for t, d in actions])
    await edit_or_send(update, context, text, keyboard, parse_mode="HTML")
    return CHOOSE_ACTION

# ========================
# ДЕЙСТВИЯ С ВРАЧОМ
# ========================

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_doctors(update, context)

    doctor = context.user_data.get("doctor", {})

    if data == "action_write":
        link = doctor.get("link")
        keyboard = nav_keyboard()
        await edit_or_send(update, context, f"💬 Напишите врачу напрямую:\n{link}", keyboard)
        return CHOOSE_ACTION

    if data == "action_book":
        keyboard = nav_keyboard()
        await edit_or_send(update, context, "📝 Введите ваше ФИО:", keyboard)
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

    name = update.message.text.strip()
    context.user_data["patient_name"] = name
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
    await send_and_save(update, context, "📅 Укажите удобную дату и время (например: 10.04.2025 в 14:00):", nav_keyboard())
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
    d = context.user_data
    doctor = d.get("doctor", {})
    visit_label = d.get("visit_label", "")
    city = d.get("city", "Онлайн")
    clinic = d.get("clinic_name", "Онлайн")

    text = (
        f"📋 <b>Проверьте данные записи:</b>\n\n"
        f"🏥 Тип: {visit_label}\n"
        f"🌆 Город: {city}\n"
        f"🏨 Клиника: {clinic}\n"
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
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        await edit_or_send(update, context, "📅 Введите дату и время приёма:", nav_keyboard())
        return COLLECT_DATETIME

    if data == "confirm_yes":
        user = query.from_user
        d = context.user_data
        doctor = d.get("doctor", {})

        msg = (
            f"🆕 <b>Новая запись на приём!</b>\n\n"
            f"🏥 Тип: {d.get('visit_label', '—')}\n"
            f"🌆 Город: {d.get('city', 'Онлайн')}\n"
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
        await context.bot.send_message(ADMIN_GROUP_ID, msg, parse_mode="HTML")

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]])
        await edit_or_send(update, context, 
            "✅ <b>Ваша запись принята!</b>\n\n"
            "Администратор свяжется с вами для подтверждения.\n\n"
            "Спасибо, что выбрали АТС Клинику! 🏥",
            keyboard, parse_mode="HTML")
        context.user_data.clear()
        return MAIN_MENU

# ========================
# ЗАДАТЬ ВОПРОС ВРАЧУ
# ========================

async def show_specialties_for_question(update, context):
    available_spec_ids = {d["spec_id"] for d in DOCTORS if d["question"]}
    items = [(name, f"qspec_{sid}") for sid, name in SPECIALTIES if sid in available_spec_ids]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, "💬 Выберите специализацию врача:", keyboard)
    return CHOOSE_SPECIALTY

async def handle_question_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_main_menu(update, context)

    spec_id = int(data.replace("qspec_", ""))
    context.user_data["spec_id"] = spec_id
    context.user_data["spec_name"] = SPEC_ID_TO_NAME.get(spec_id, "")

    doctors = [d for d in DOCTORS if d["spec_id"] == spec_id and d["question"]]
    items = [(f"👨‍⚕️ {d['name']}", f"qdoc_{d['id']}") for d in doctors]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, "👨‍⚕️ Выберите врача:", keyboard)
    return CHOOSE_DOCTOR

async def handle_question_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_specialties_for_question(update, context)

    doc_id = int(data.replace("qdoc_", ""))
    doctor = next((d for d in DOCTORS if d["id"] == doc_id), None)
    context.user_data["doctor"] = doctor

    await edit_or_send(update, context, 
        f"✍️ Напишите ваш вопрос для врача <b>{doctor['name']}</b>:",
        nav_keyboard(), parse_mode="HTML")
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
    user = update.message.from_user
    doctor = context.user_data.get("doctor", {})

    msg = (
        f"❓ <b>Вопрос врачу</b>\n\n"
        f"👨‍⚕️ Врач: {doctor.get('name', '—')}\n"
        f"🩺 Специализация: {doctor.get('spec', '—')}\n\n"
        f"💬 Вопрос: {question}\n\n"
        f"👤 От: @{user.username or 'нет'} (ID: <code>{user.id}</code>)"
    )
    await context.bot.send_message(ADMIN_GROUP_ID, msg, parse_mode="HTML")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]])
    await send_and_save(update, context,
        "✅ Ваш вопрос отправлен врачу!\n\nМы свяжемся с вами в ближайшее время.",
        keyboard)
    context.user_data.clear()
    return MAIN_MENU

# ========================
# ОБРАТНЫЙ ЗВОНОК
# ========================

async def show_specialties_for_callback(update, context):
    available_spec_ids = {d["spec_id"] for d in DOCTORS if d["callback"]}
    items = [(name, f"cbspec_{sid}") for sid, name in SPECIALTIES if sid in available_spec_ids]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, "📞 Выберите специализацию:", keyboard)
    return CHOOSE_SPECIALTY

async def handle_callback_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_main_menu(update, context)

    spec_id = int(data.replace("cbspec_", ""))
    context.user_data["spec_id"] = spec_id
    context.user_data["spec_name"] = SPEC_ID_TO_NAME.get(spec_id, "")

    doctors = [d for d in DOCTORS if d["spec_id"] == spec_id and d["callback"]]
    items = [(f"👨‍⚕️ {d['name']}", f"cbdoc_{d['id']}") for d in doctors]
    keyboard = make_inline_cols(items, cols=1)
    await edit_or_send(update, context, "👨‍⚕️ Выберите врача:", keyboard)
    return CHOOSE_DOCTOR

async def handle_callback_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        context.user_data.clear()
        return await show_main_menu(update, context)
    if data == "back":
        return await show_specialties_for_callback(update, context)

    doc_id = int(data.replace("cbdoc_", ""))
    doctor = next((d for d in DOCTORS if d["id"] == doc_id), None)
    context.user_data["doctor"] = doctor

    await edit_or_send(update, context,
        f"📝 Введите ваше ФИО для обратного звонка:",
        nav_keyboard())
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

    phone = update.message.text.strip()
    user = update.message.from_user
    doctor = context.user_data.get("doctor", {})

    msg = (
        f"📞 <b>Запрос обратного звонка</b>\n\n"
        f"👨‍⚕️ Врач: {doctor.get('name', '—')}\n"
        f"🩺 Специализация: {doctor.get('spec', '—')}\n\n"
        f"👤 ФИО: {context.user_data.get('cb_name', '—')}\n"
        f"📱 Телефон: {phone}\n\n"
        f"💬 Telegram: @{user.username or 'нет'} (ID: <code>{user.id}</code>)"
    )
    await context.bot.send_message(ADMIN_GROUP_ID, msg, parse_mode="HTML")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="home")]])
    await send_and_save(update, context,
        "✅ Заявка на обратный звонок отправлена!\n\nМы перезвоним вам в ближайшее время.",
        keyboard)
    context.user_data.clear()
    return MAIN_MENU

# ========================
# ЗАПУСК
# ========================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(handle_main_menu)],
            CHOOSE_CITY: [CallbackQueryHandler(handle_city)],
            CHOOSE_CLINIC: [CallbackQueryHandler(handle_clinic)],
            CHOOSE_SPECIALTY: [
                CallbackQueryHandler(handle_specialty, pattern="^spec_"),
                CallbackQueryHandler(handle_question_specialty, pattern="^qspec_"),
                CallbackQueryHandler(handle_callback_specialty, pattern="^cbspec_"),
                CallbackQueryHandler(handle_specialty, pattern="^(back|home)$"),
            ],
            CHOOSE_DOCTOR: [
                CallbackQueryHandler(handle_doctor, pattern="^doc_"),
                CallbackQueryHandler(handle_question_doctor, pattern="^qdoc_"),
                CallbackQueryHandler(handle_callback_doctor, pattern="^cbdoc_"),
                CallbackQueryHandler(handle_doctor, pattern="^(back|home)$"),
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
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
