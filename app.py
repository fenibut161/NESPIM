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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Функция для текстовых запросов (DeepSeek через OpenRouter) ---
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
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"]
    }
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and data['choices']:
                msg = data['choices'][0].get('message', {})
                images = msg.get('images')
                if images and len(images) > 0:
                    image_url = images[0].get('image_url', {}).get('url')
                    if image_url:
                        return image_url
                content = msg.get('content', '')
                if content.startswith('http') and ('png' in content or 'jpg' in content):
                    return content
            return None
        else:
            logger.error(f"Ошибка API: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Ошибка соединения: {e}")
        return None

# --- Клавиатура ---
def get_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add(KeyboardButton("🎨 Сгенерировать изображение"))
    return markup

# --- Команда /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я текстовый ассистент, а ещё умею рисовать по команде /image.\n"
        "Просто напиши любое сообщение, и я отвечу.\n"
        "А чтобы сгенерировать картинку, используй кнопку ниже или команду /image описание.",
        reply_markup=get_keyboard()
    )

# --- Обработчик кнопки "Сгенерировать изображение" ---
@bot.message_handler(func=lambda message: message.text == "🎨 Сгенерировать изображение")
def image_button_handler(message):
    bot.send_message(message.chat.id, "✏️ Напиши описание после команды /image, например:\n/image закат на Бали")

# --- Команда /image (генерация картинки) ---
@bot.message_handler(commands=['image'])
def handle_image_command(message):
    # Извлекаем описание из текста команды
    prompt = message.text.replace('/image', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "✏️ Напиши описание после команды: /image кот в космосе")
        return

    waiting = bot.reply_to(message, "🎨 Генерирую картинку, подожди...")
    image_url = ask_openrouter_image(prompt)
    if image_url:
        bot.delete_message(message.chat.id, waiting.message_id)
        try:
            bot.send_photo(message.chat.id, image_url)
        except Exception:
            bot.send_message(message.chat.id, f"Ссылка на картинку: {image_url}")
    else:
        bot.edit_message_text(
            "❌ Не удалось сгенерировать изображение. Возможно, модель перегружена или нужен платёж.",
            message.chat.id, waiting.message_id
        )

# --- Обработчик обычных текстовых сообщений (не команды) ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    # Игнорируем команды и текст кнопки
    if message.text.startswith('/') or message.text == "🎨 Сгенерировать изображение":
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# --- Запуск бота с автоперезапуском ---
def run_bot():
    logger.info("✅ Бот запущен и слушает сообщения...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

# --- Flask для Render ---
@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)               
