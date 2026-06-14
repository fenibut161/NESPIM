import os
import telebot
import requests
from flask import Flask
from threading import Thread

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

def ask_openrouter(prompt):
    """Отправляет запрос к OpenRouter API."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openrouter/free", # Укажите здесь название модели с суффиксом :free
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"Ошибка API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Ошибка соединения: {e}"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    reply = ask_openrouter(message.text)
    bot.reply_to(message, reply)

def run_bot():
    print("Бот запущен и слушает сообщения...")
    bot.infinity_polling()

@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
