import os
import telebot
import requests
from flask import Flask
from threading import Thread

# --- КОНФИГУРАЦИЯ (переменные окружения) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

def ask_gemini(prompt: str) -> str:
    """Отправляет запрос к Gemini API через прямые HTTP-запросы (без сторонних библиотек)."""
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    try:
        # Добавляем API-ключ как параметр запроса
        url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            # Извлекаем текст ответа
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"Ошибка Gemini API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Ошибка соединения: {e}"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    reply = ask_gemini(message.text)
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
