 --- Общий обработчик для текста (и для команд, и для промптов) ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    # Если это команда или нажатие на кнопку-триггер, пропускаем (они уже обработаны)
    if message.text.startswith('/') or message.text == "🎨 Сгенерировать изображение":
        return
    
    # Проверяем, является ли запрос промптом для генерации (недавний контекст)
    # Для простоты: генерируем картинку, если пользователь написал что-то похожее
    # Это базовый пример. При желании можно сделать умнее.
    prompt = message.text
    generate_and_send_image(message, prompt)

# --- Общая функция для генерации и отправки картинки ---
def generate_and_send_image(message, prompt):
    waiting_msg = bot.reply_to(message, "🎨 Генерирую картинку, подожди немного...")
    image_data = ask_openrouter_image(prompt)
    if image_data:
        bot.delete_message(message.chat.id, waiting_msg.message_id)
        try:
            # Пробуем отправить как фото
            if image_data.startswith('data:image'):
                # Это base64, отправляем как документ или фото
                import base64
                image_data = image_data.split(',')[1] if ',' in image_data else image_data
                bot.send_photo(message.chat.id, base64.b64decode(image_data))
            else:
                # Это ссылка
                bot.send_photo(message.chat.id, image_data)
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            bot.send_message(message.chat.id, f"⚠️ Ссылка на картинку: {image_data}")
    else:
        bot.edit_message_text(
            "❌ Не удалось сгенерировать изображение. Возможно, модель временно недоступна или не хватает кредитов. Попробуй позже.",
            message.chat.id, waiting_msg.message_id
        )

# --- Текстовый режим (обычный разговор) ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/') or message.text == "🎨 Сгенерировать изображение":
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# --- Главный цикл с автоперезапуском ---
def run_bot():
    logger.info("✅ Бот запущен и слушает сообщения...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

# --- Заглушка для Render ---
@app.route('/')
def index():
    return "Bot is running"

# --- Точка входа ---
if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080) хочеш
[2 ссылки]
1. Redirecting...
http://logger.info
2. app.run - Данный веб-сайт выставлен на продажу! - app Ресурсы и информация.
http://app.run

Дэник Добрынян, сегодня в 12:33
import os
import telebot
import requests
import time
import logging
from flask import Flask
from threading import Thread
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# --- Настройки ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# --- Инициализация ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Функция для текстовых запросов (твой старый код) ---
def ask_openrouter_text(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"⚠️ Ошибка соединения: {e}"

# --- Функция для генерации изображений ---
def ask_openrouter_image(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "google/gemini-2.5-flash-image-preview", # Модель для генерации
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"] # Указываем, что нужна картинка
    }
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
        if response.status_code == 200:
            data = response.json()
            # Пробуем найти картинку (по форматам из примера RohaCode)
            if 'choices' in data and data['choices']:
                message_data = data['choices'][0].get('message', {})
                # Ищем в 'images' или в 'content'
                images = message_data.get('images')
                if images and len(images) > 0:
                    # Если изображение в base64
                    image_url = images[0].get('image_url', {}).get('url')
                    if image_url:
                        return image_url
                # Если изображение в тексте как ссылка
                content = message_data.get('content', '')
                if content.startswith('http') and ('png' in content or 'jpg' in content):
                    return content
            return None
        else:
            logger.error(f"Ошибка API: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Ошибка соединения: {e}")
        return None

# --- Функция для отображения клавиатуры ---
def get_main_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(KeyboardButton("🎨 Сгенерировать изображение"))
    return markup

# --- Обработчик команды /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я бот, который умеет общаться и создавать картинки.\n"
        "Просто напиши текст, чтобы поговорить со мной.\n"
        "Или нажми на кнопку, чтобы перейти в режим генерации.",
        reply_markup=get_main_keyboard()
    )

# --- Обработчик команды /image для ручного ввода ---
@bot.message_handler(commands=['image'])
def handle_image_command(message):
    prompt = message.text.replace('/image', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "✏️ Напиши описание после команды, например: /image кот в космосе")
        return
    generate_and_send_image(message, prompt)

# --- Обработчик нажатия на кнопку "Сгенерировать изображение" ---
@bot.message_handler(func=lambda message: message.text == "🎨 Сгенерировать изображение")
def handle_image_button(message):
    bot.reply_to(message, "✏️ Напиши, что ты хочешь видеть на картинке.")

# --- Общий обработчик для текста (и для команд, и для промптов) ---
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    # Если это команда или нажатие на кнопку-триггер, пропускаем (они уже обработаны)
    if message.text.startswith('/') or message.text == "🎨 Сгенерировать изображение":
        return
    
    # Проверяем, является ли запрос промптом для генерации (недавний контекст)
    # Для простоты: генерируем картинку, если пользователь написал что-то похожее
    # Это базовый пример. При желании можно сделать умнее.
    prompt = message.text
    generate_and_send_image(message, prompt)

# --- Общая функция для генерации и отправки картинки ---
def generate_and_send_image(message, prompt):
    waiting_msg = bot.reply_to(message, "🎨 Генерирую картинку, подожди немного...")
    image_data = ask_openrouter_image(prompt)
    if image_data:
        bot.delete_message(message.chat.id, waiting_msg.message_id)
        try:
            # Пробуем отправить как фото
            if image_data.startswith('data:image'):
                # Это base64, отправляем как документ или фото
                import base64
                image_data = image_data.split(',')[1] if ',' in image_data else image_data
                bot.send_photo(message.chat.id, base64.b64decode(image_data))
            else:
                # Это ссылка
                bot.send_photo(message.chat.id, image_data)
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            bot.send_message(message.chat.id, f"⚠️ Ссылка на картинку: {image_data}")
    else:
        bot.edit_message_text(
            "❌ Не удалось сгенерировать изображение. Возможно, модель временно недоступна или не хватает кредитов. Попробуй позже.",
            message.chat.id, waiting_msg.message_id
        )

# --- Текстовый режим (обычный разговор) ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/') or message.text == "🎨 Сгенерировать изображение":
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# --- Главный цикл с автоперезапуском ---
def run_bot():
    logger.info("✅ Бот запущен и слушает сообщения...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

# --- Заглушка для Render ---
@app.route('/')
def index():
    return "Bot is running"

# --- Точка входа ---
if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080) 
