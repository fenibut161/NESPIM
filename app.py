import os
import telebot
import requests
import time
import uuid
import base64
import urllib3
from flask import Flask
from threading import Thread

# Отключаем предупреждения о небезопасных запросах (для тестов)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Конфигурация из переменных окружения Render ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# ========== ФУНКЦИЯ ПОЛУЧЕНИЯ ТОКЕНА GIGACHAT ==========
def get_gigachat_token():
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    credentials = f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {encoded_credentials}"
    }
    data = {"scope": "GIGACHAT_API_PERS"}
    try:
        response = requests.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers=headers,
            data=data,
            verify=False,
            timeout=30
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            return None
    except Exception:
        return None

# ========== ФУНКЦИЯ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЯ ЧЕРЕЗ GIGACHAT ==========
def generate_gigachat_image(prompt: str) -> str | None:
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
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=60)
        if response.status_code == 200:
            data = response.json()
            images = data.get("data", [])
            if images:
                return images[0].get("url")
        return None
    except Exception:
        return None

# ========== ТЕКСТОВЫЙ ОТВЕТ ЧЕРЕЗ OPENROUTER (DeepSeek и др.) ==========
def ask_openrouter_text(prompt: str) -> str:
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

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я бот, который умеет общаться и создавать картинки.\n"
        "Просто напиши текст, чтобы поговорить со мной.\n"
        "Или используй команду /image описание, чтобы создать изображение.\n"
        "Пример: /image кот в космосе"
    )

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
        bot.send_message(message.chat.id, "❌ Не удалось сгенерировать изображение. Проверь переменные GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET в Render.")

# ========== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ (НЕ КОМАНД) ==========
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/'):
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# ========== ЗАПУСК БОТА С АВТОПЕРЕЗАПУСКОМ ==========
def run_bot():
    print("✅ Бот запущен и слушает сообщения...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"❌ Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
