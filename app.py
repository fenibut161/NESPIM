import os
import telebot
from flask import Flask
from threading import Thread
from google import genai

# --- КОНФИГУРАЦИЯ (Чтение из переменных окружения) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

# Настройка Gemini с новой библиотекой google-genai
genai_client = genai.Client(api_key=GEMINI_API_KEY)

# --- ФУНКЦИЯ ЗАПРОСА К GEMINI (Новый синтаксис) ---
def ask_gemini(prompt):
    try:
        # Новый способ вызова модели
        response = genai_client.models.generate_content(
            model="gemini-2.0-flash",  # Используем модель 2.0 Flash
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Ошибка Gemini: {e}")
        return "Извините, произошла ошибка при обращении к ИИ."

# --- ОБРАБОТЧИК СООБЩЕНИЙ ТЕЛЕГРАМ ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_input = message.text
    reply = ask_gemini(user_input)
    bot.reply_to(message, reply)

# --- ЗАПУСК БОТА И ВЕБ-СЕРВЕРА ДЛЯ RENDER ---
def run_bot():
    print("Бот запущен и готов к работе...")
    bot.infinity_polling()

@app.route('/')
def index():
    return "Telegram bot is running!"

if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    thread = Thread(target=run_bot)
    thread.start()
    # Запускаем Flask-сервер, который нужен Render
    app.run(host='0.0.0.0', port=8080)
