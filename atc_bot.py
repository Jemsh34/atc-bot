import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ========================
# НАСТРОЙКИ
# ========================
BOT_TOKEN = "8442363087:AAFGqS2UtqfF_H9sFVUFMy6lMv28rJ739Gc"
ADMIN_GROUP_ID = -5228416685

# ========================
# ДАННЫЕ КЛИНИКИ
# ========================
CITIES = ["Москва", "Ялта", "Севастополь"]

CLINICS = {
    "Москва": ["Ейиид клиника", "АТС клиника", "Ильинская больница"],
    "Ялта": ["Ейиид клиника", "АТС клиника", "Ильинская больница"],
    "Севастополь": ["Ейиид клиника", "АТС клиника", "Ильинская больница"],
}

DIRECTIONS = [
    "Анестезиология и реаниматология",
    "Неврология и нейрохирургия",
    "Педиатрия",
    "Реабилитация и восстановление",
    "Терапия",
]

DOCTORS = {
    "Анестезиология и реаниматология": [
        {"name": "Матвиенко Ярослава Дмитриевна", "emoji": "👨‍⚕️"},
    ],
    "Неврология и нейрохирургия": [
        {"name": "Гусейнов Эльдар Рамазанович", "emoji": "👨‍⚕️"},
        {"name": "Журкина Мария Викторовна", "emoji": "👩‍⚕️"},
        {"name": "Торпанов Бронислав Русланович", "emoji": "👨‍⚕️"},
        {"name": "Носиков Артём Сергеевич", "emoji": "👨‍⚕️"},
        {"name": "Муравьёв Ярослав Эдуардович", "emoji": "👨‍⚕️"},
        {"name": "Цибулюля Андрей Александрович", "emoji": "👨‍⚕️"},
    ],
    "Педиатрия": [
        {"name": "Матвиенко Ярослава Дмитриевна", "emoji": "👩‍⚕️"},
    ],
    "Реабилитация и восстановление": [
        {"name": "Муравьёв Ярослав Эдуардович", "emoji": "👨‍⚕️"},
    ],
    "Терапия": [
        {"name": "Носиков Артём Сергеевич", "emoji": "👨‍⚕️"},
    ],
}

# ========================
# СОСТОЯНИЯ
# ========================
(
    MAIN_MENU,
    CHOOSE_CITY,
    CHOOSE_CLINIC,
    CHOOSE_DIRECTION,
    CHOOSE_DOCTOR,
    COLLECT_NAME,
    COLLECT_PHONE,
    COLLECT_BIRTH,
    COLLECT_CONTACT_METHOD,
    COLLECT_DATETIME,
    CONFIRM,
    ASK_QUESTION,
) = range(12)

logging.basicConfig(level=logging.INFO)

# ========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [["🖥 Онлайн консультация"], ["🏥 В клинике"], ["💬 Задать вопрос онлайн"]],
        resize_keyboard=True
    )

def back_keyboard():
    return ReplyKeyboardMarkup(
        [["◀️ Назад", "🏠 Главное меню"]],
        resize_keyboard=True
    )

def make_keyboard(items, cols=2):
    rows = [items[i:i+cols] for i in range(0, len(items), cols)]
    rows.append(["◀️ Назад", "🏠 Главное меню"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

async def go_home(update, context):
    context.user_data.clear()
    await update.message.reply_text(
        "🏠 Главное меню. Выберите тип приёма:",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

# ========================
# ХЭНДЛЕРЫ
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Добро пожаловать в АТС Клинику!\n\n"
        "Я помогу вам записаться к врачу или ответить на вопросы.\n\n"
        "Выберите тип приёма:",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🖥 Онлайн консультация":
        context.user_data["type"] = "Онлайн"
        await update.message.reply_text(
            "Выберите направление:",
            reply_markup=make_keyboard(DIRECTIONS, cols=1)
        )
        return CHOOSE_DIRECTION

    elif text == "🏥 В клинике":
        context.user_data["type"] = "В клинике"
        await update.message.reply_text(
            "Выберите город:",
            reply_markup=make_keyboard(CITIES)
        )
        return CHOOSE_CITY

    elif text == "💬 Задать вопрос онлайн":
        await update.message.reply_text(
            "✍️ Напишите ваш вопрос, и мы передадим его врачу:",
            reply_markup=back_keyboard()
        )
        return ASK_QUESTION

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "◀️ Назад" or text == "🏠 Главное меню":
        return await go_home(update, context)

    user = update.message.from_user
    msg = (
        f"❓ <b>Новый вопрос от пациента</b>\n\n"
        f"👤 {user.full_name} (@{user.username or 'нет'})\n"
        f"📱 ID: <code>{user.id}</code>\n\n"
        f"💬 <b>Вопрос:</b> {text}"
    )
    await context.bot.send_message(ADMIN_GROUP_ID, msg, parse_mode="HTML")
    await update.message.reply_text(
        "✅ Ваш вопрос отправлен! Мы свяжемся с вами в ближайшее время.",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def choose_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("Выберите тип приёма:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    if text not in CITIES:
        await update.message.reply_text("Пожалуйста, выберите город из списка.")
        return CHOOSE_CITY

    context.user_data["city"] = text
    clinics = CLINICS.get(text, [])
    await update.message.reply_text(
        f"Город: {text}\nВыберите клинику:",
        reply_markup=make_keyboard(clinics, cols=1)
    )
    return CHOOSE_CLINIC

async def choose_clinic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("Выберите город:", reply_markup=make_keyboard(CITIES))
        return CHOOSE_CITY

    context.user_data["clinic"] = text
    await update.message.reply_text(
        f"Клиника: {text}\nВыберите направление:",
        reply_markup=make_keyboard(DIRECTIONS, cols=1)
    )
    return CHOOSE_DIRECTION

async def choose_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        if context.user_data.get("type") == "Онлайн":
            await update.message.reply_text("Выберите тип приёма:", reply_markup=main_menu_keyboard())
            return MAIN_MENU
        await update.message.reply_text(
            "Выберите клинику:",
            reply_markup=make_keyboard(CLINICS.get(context.user_data.get("city", "Москва"), []), cols=1)
        )
        return CHOOSE_CLINIC

    if text not in DIRECTIONS:
        await update.message.reply_text("Пожалуйста, выберите направление из списка.")
        return CHOOSE_DIRECTION

    context.user_data["direction"] = text
    doctors = DOCTORS.get(text, [])
    doctor_names = [f"{d['emoji']} {d['name']}" for d in doctors]
    await update.message.reply_text(
        f"Направление: {text}\nВыберите врача:",
        reply_markup=make_keyboard(doctor_names, cols=1)
    )
    return CHOOSE_DOCTOR

async def choose_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("Выберите направление:", reply_markup=make_keyboard(DIRECTIONS, cols=1))
        return CHOOSE_DIRECTION

    context.user_data["doctor"] = text
    await update.message.reply_text(
        f"Врач: {text}\n\n📝 Введите ваше ФИО:",
        reply_markup=back_keyboard()
    )
    return COLLECT_NAME

async def collect_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        direction = context.user_data.get("direction", "")
        doctors = DOCTORS.get(direction, [])
        doctor_names = [f"{d['emoji']} {d['name']}" for d in doctors]
        await update.message.reply_text("Выберите врача:", reply_markup=make_keyboard(doctor_names, cols=1))
        return CHOOSE_DOCTOR

    context.user_data["patient_name"] = text
    await update.message.reply_text("📱 Введите ваш номер телефона:", reply_markup=back_keyboard())
    return COLLECT_PHONE

async def collect_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("📝 Введите ваше ФИО:", reply_markup=back_keyboard())
        return COLLECT_NAME

    context.user_data["phone"] = text
    await update.message.reply_text("🎂 Введите дату рождения (например: 15.03.1990):", reply_markup=back_keyboard())
    return COLLECT_BIRTH

async def collect_birth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("📱 Введите номер телефона:", reply_markup=back_keyboard())
        return COLLECT_PHONE

    context.user_data["birth"] = text
    await update.message.reply_text(
        "📅 Укажите удобную дату и время приёма (например: 10.04.2025 в 14:00):",
        reply_markup=back_keyboard()
    )
    return COLLECT_DATETIME

async def collect_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("🎂 Введите дату рождения:", reply_markup=back_keyboard())
        return COLLECT_BIRTH

    context.user_data["datetime"] = text

    d = context.user_data
    summary = (
        f"📋 <b>Проверьте данные записи:</b>\n\n"
        f"🏥 Тип: {d.get('type', '—')}\n"
        f"🌆 Город: {d.get('city', 'Онлайн')}\n"
        f"🏨 Клиника: {d.get('clinic', 'Онлайн')}\n"
        f"🩺 Направление: {d.get('direction', '—')}\n"
        f"👨‍⚕️ Врач: {d.get('doctor', '—')}\n"
        f"👤 ФИО: {d.get('patient_name', '—')}\n"
        f"📱 Телефон: {d.get('phone', '—')}\n"
        f"🎂 Дата рождения: {d.get('birth', '—')}\n"
        f"📅 Дата и время: {d.get('datetime', '—')}\n"
    )
    await update.message.reply_text(
        summary,
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Подтвердить"], ["◀️ Назад", "🏠 Главное меню"]],
            resize_keyboard=True
        )
    )
    return CONFIRM

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Главное меню": return await go_home(update, context)
    if text == "◀️ Назад":
        await update.message.reply_text("📅 Введите дату и время приёма:", reply_markup=back_keyboard())
        return COLLECT_DATETIME

    if text == "✅ Подтвердить":
        user = update.message.from_user
        d = context.user_data
        msg = (
            f"🆕 <b>Новая запись на приём!</b>\n\n"
            f"🏥 Тип: {d.get('type', '—')}\n"
            f"🌆 Город: {d.get('city', 'Онлайн')}\n"
            f"🏨 Клиника: {d.get('clinic', 'Онлайн')}\n"
            f"🩺 Направление: {d.get('direction', '—')}\n"
            f"👨‍⚕️ Врач: {d.get('doctor', '—')}\n"
            f"👤 ФИО пациента: {d.get('patient_name', '—')}\n"
            f"📱 Телефон: {d.get('phone', '—')}\n"
            f"🎂 Дата рождения: {d.get('birth', '—')}\n"
            f"📅 Дата/время приёма: {d.get('datetime', '—')}\n\n"
            f"💬 Telegram: @{user.username or 'нет'} (ID: {user.id})\n"
            f"✅ Статус: новая запись"
        )
        await context.bot.send_message(ADMIN_GROUP_ID, msg, parse_mode="HTML")
        await update.message.reply_text(
            "✅ Ваша запись принята!\n\n"
            "Администратор свяжется с вами для подтверждения.\n\n"
            "Спасибо, что выбрали АТС Клинику! 🏥",
            reply_markup=main_menu_keyboard()
        )
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
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            CHOOSE_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_city)],
            CHOOSE_CLINIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_clinic)],
            CHOOSE_DIRECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_direction)],
            CHOOSE_DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_doctor)],
            COLLECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_name)],
            COLLECT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_phone)],
            COLLECT_BIRTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_birth)],
            COLLECT_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_datetime)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
            ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv)
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
