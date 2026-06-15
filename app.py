import os
import telebot
import requests
import time
from flask import Flask
from threading import Thread

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

def ask_openrouter(prompt):
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
            return f"Ошибка API: {response.status_code}"
    except Exception as e:
        return f"Ошибка соединения: {e}"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    reply = ask_openrouter(message.text)
    bot.reply_to(message, reply)

# --- Главный цикл с автоперезапуском ---
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
    # Запускаем бота в фоновом потоке
    Thread(target=run_bot).start()
    # Запускаем веб-сервер для Render
    app.run(host='0.0.0.0', port=8080)
[Ссылка]
app.run - Данный веб-сайт выставлен на продажу! - app Ресурсы и информация.
http://app.run
