import os
import telebot
import requests
import time
import uuid
from flask import Flask
from threading import Thread

# --- Конфигурация ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Функция для получения токена доступа GigaChat ---
def get_gigachat_token():
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4())
    }
    data = {
        "client_id": "gigachat",
        "client_secret": GIGACHAT_CLIENT_SECRET,
        "scope": "GIGACHAT_API_PERS"
    }
    try:
        response = requests.post(url, headers=headers, data=data, verify=False)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            return None
    except Exception as e:
        return None

# --- Функция для генерации изображения через GigaChat (Kandinsky) ---
def generate_gigachat_image(prompt):
    token = get_gigachat_token()
    if not token:
        return None
    url = "https://gigachat.devices.sberbank.ru/api/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "model": "Kandinsky",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, verify=False)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [{}])[0].get("url")
        else:
            return None
    except Exception as e:
        return None

# --- Функция для текстовых запросов (OpenRouter) ---
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

# --- Обработчик команды /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я бот, который умеет общаться и создавать картинки.\n"
        "Просто напиши текст, чтобы поговорить со мной.\n"
        "Или используй команду /image описание, чтобы создать изображение.\n"
        "Пример: /image кот в космосе"
    )

# --- Обработчик команды /image (генерация картинки) ---
@bot.message_handler(commands=['image'])
def handle_image_command(message):
    prompt = message.text.replace('/image', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "✏️ Напиши описание после команды, например: /image закат на Бали")
        return
    waiting = bot.reply_to(message, "🎨 Генерирую картинку через Kandinsky, подожди...")
    image_url = generate_gigachat_image(prompt)
    bot.delete_message(message.chat.id, waiting.message_id)
    if image_url:
        bot.send_photo(message.chat.id, image_url)
    else:
        bot.send_message(message.chat.id, "❌ Не удалось сгенерировать изображение. Проверь API-ключ GigaChat.")

# --- Обработчик обычных текстовых сообщений (не команды) ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    # Игнорируем команды
    if message.text.startswith('/'):
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# --- Запуск бота с автоперезапуском ---
def run_bot():
    print("✅ Бот запущен и слушает сообщения...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"❌ Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

# --- Заглушка для Render ---
@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
