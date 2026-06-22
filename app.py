# ================== ОБРАБОТЧИКИ МЕНЮ (ДОЛЖНЫ БЫТЬ ВЫШЕ ЧЕМ ОБЩИЙ ТЕКСТОВЫЙ) ==================
@bot.message_handler(func=lambda m: m.text == "🖼 Создать изображение")
def menu_generate_image(message):
    user_state[message.chat.id] = "select_model_generate"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🆓 GigaChat (бесплатно)", callback_data="gen_gigachat"),
        InlineKeyboardButton("🌱 Seedream 4.5 (2 кр.)", callback_data="gen_seedream"),
        InlineKeyboardButton("🚀 Grok Imagine (2 кр.)", callback_data="gen_grok")
    )
    bot.send_message(message.chat.id, "Выбери модель для генерации:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎨 Редактировать фото")
def menu_edit_photo(message):
    user_state[message.chat.id] = "select_model_edit"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌱 Seedream 4.5 (3 кр.)", callback_data="edit_seedream"),
        InlineKeyboardButton("🚀 Grok Imagine (3 кр.)", callback_data="edit_grok")
    )
    bot.send_message(message.chat.id, "Выбери модель редактирования:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
def menu_video(message):
    user_state[message.chat.id] = "select_video_mode"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📝 Текст в видео", callback_data="vid_text"),
        InlineKeyboardButton("🖼 Картинка в видео", callback_data="vid_image")
    )
    bot.send_message(message.chat.id, "Выберите режим генерации видео:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💬 Спросить (чат)")
def menu_chat(message):
    user_state[message.chat.id] = None
    bot.send_message(message.chat.id, "Задай любой вопрос (DeepSeek V4 Pro). Каждые 50 сообщений списывается 1 кредит.", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def menu_profile(message):
    profile(message)   # вызов функции профиля

@bot.message_handler(func=lambda m: m.text == "💰 Магазин")
def menu_shop(message):
    shop(message)

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_to_main(message):
    user_state[message.chat.id] = None
    user_video_frames.pop(message.chat.id, None)
    user_video_params.pop(message.chat.id, None)
    user_video_mode.pop(message.chat.id, None)
    user_video_model.pop(message.chat.id, None)
    send_main_menu(message.chat.id)

# ================== ОБЩИЙ ТЕКСТОВЫЙ ОБРАБОТЧИК (DEEPSEEK) ==================
# Этот обработчик должен идти ПОСЛЕ всех специфичных, и он явно исключает кнопки меню
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text_chat(message):
    # Игнорируем служебные команды и кнопки меню
    if message.text.startswith('/'):
        return
    if message.text in [
        "🖼 Создать изображение", "🎨 Редактировать фото", "🎥 Создать видео",
        "💬 Спросить (чат)", "👤 Профиль", "💰 Магазин", "🔙 Главное меню"
    ]:
        # На всякий случай, если почему-то не сработал специфичный обработчик, направим в меню
        send_main_menu(message.chat.id, "Пожалуйста, используйте кнопки меню.")
        return

    state = user_state.get(message.chat.id)
    if state in ["awaiting_prompt", "awaiting_generate_prompt", "awaiting_photo", "awaiting_video_prompt", "awaiting_video_image_first", "awaiting_video_image_last", "select_video_model"]:
        return  # не обрабатываем, ожидаем ввода по состоянию

    chat_id = message.chat.id
    # Админ без списаний
    if chat_id == ADMIN_ID:
        reply = ask_deepseek(message.text)
        bot.send_message(chat_id, reply, reply_markup=back_keyboard())
        return

    # Тарификация чата
    user_message_count[chat_id] += 1
    if user_message_count[chat_id] % 50 == 0:
        cost = CREDIT_COSTS['deepseek_session']
        if user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, "❌ Недостаточно кредитов для продолжения чата. Пополните баланс в магазине 💰.")
            return
        user_credits[chat_id] -= cost
        user_credit_history[chat_id].append((time.time(), -cost, "Пакет из 50 сообщений DeepSeek"))
        save_data()
        bot.send_message(chat_id, f"💬 Использовано 50 сообщений. Списано {cost} кредит. Осталось: {user_credits[chat_id]} кредитов.")

    reply = ask_deepseek(message.text)
    bot.send_message(chat_id, reply, reply_markup=back_keyboard())

# ================== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ ==================
@bot.message_handler(func=lambda m: True)
def handle_other(message):
    bot.send_message(message.chat.id, "Пожалуйста, используй кнопки меню.")
