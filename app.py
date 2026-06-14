import telebot
import requests
from flask import Flask
from threading import Thread

# ----- Конфигурация -----
TOKEN = "8644376300:AAEk6h2HR_I8xc-VmUHyl1ndQpD5ViibY50" 
DEEPSEEK_KEY = "sk-5f31546ce5f745719da4d71f67f12e47"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ----- Функция запроса к DeepSeek -----
def ask_deepseek(prompt):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }
    try:
        resp = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        else:
            return f"Ошибка API: {resp.status_code}"
    except Exception as e:
        return f"Ошибка соединения: {e}"

# ----- Обработчик сообщений -----
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    reply = ask_deepseek(message.text)
    bot.reply_to(message, reply)

# ----- Запуск бота в отдельном потоке (чтобы не мешать Flask) -----
def run_bot():
    bot.infinity_polling()

# ----- Заглушка для Flask (нужна, чтобы Render не ругался) -----
@app.route('/')
def index():
    return "Bot is running"

# ----- Главная функция -----
if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    Thread(target=run_bot).start()
    # Запускаем Flask-сервер (Render требует открытый порт)
    app.run(host='0.0.0.0', port=8080)
