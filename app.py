import os
import telebot
import requests
import time
import re
import urllib3
from flask import Flask
from threading import Thread
from gigachat import GigaChat

# Отключаем предупреждения (только для разработки!)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ЗАГРУЗКА ПЕРЕМЕННЫХ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")  # Обратите внимание на новое имя!

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- 1. ИНИЦИАЛИЗАЦИЯ GIGACHAT ---
# Используем более простую авторизацию через параметр 'credentials'
giga = GigaChat(
    credentials=GIGACHAT_CREDENTIALS,  # Используем переменную GIGACHAT_CREDENTIALS
    verify_ssl_certs=False,  # Отключаем проверку SSL для демонстрации
    scope="GIGACHAT_API_PERS",
    model="GigaChat"
)

# --- 2. ФУНКЦИЯ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЯ ---
def generate_image_by_gigachat(prompt):
    try:
        # Отправляем запрос с параметром, который включает функцию генерации
        response = giga.chat(
            messages=[
                {"role": "user", "content": prompt}
            ],
            function_call="auto"  # Ключевой параметр для включения рисования!
        )
        # Получаем ответ модели
        assistant_content = response.choices[0].message.content
        
        # Ищем в ответе идентификатор файла
        # Формат обычно такой: [Image 0] или <img src="ID"/>
        match = re.search(r'\[Image \d+\]|(?:img src=)?["\']?([a-f0-9\-]+)["\']?', assistant_content)
        if match:
            file_id = match.group(1) if match.lastindex else match.group(0)
            # Скачиваем картинку по ID
            img_data = giga.download_file(file_id) # Метод .download_file возвращает бинарные данные
            return img_data
        else:
            return None
    except Exception as e:
        print(f"Ошибка генерации: {e}")
        return None

# --- 3. ФУНКЦИЯ ДЛЯ ОБЫЧНОГО ТЕКСТОВОГО ДИАЛОГА ---
def ask_openrouter_text(prompt):
    # ... (код остается прежним) ...
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "openrouter/free", "messages": [{"role": "user", "content": prompt}]}
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"⚠️ Ошибка соединения: {e}"

# --- 4. ОБРАБОТЧИКИ КОМАНД ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я умею общаться и создавать картинки. Просто напиши текст или используй команду /image для генерации.")

@bot.message_handler(commands=['image'])
def handle_image_command(message):
    prompt = message.text.replace('/image', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "✏️ Напиши описание после команды, например: /image закат на Бали")
        return
    waiting = bot.reply_to(message, "🎨 Генерирую картинку через Kandinsky, подожди...")
    img_data = generate_image_by_gigachat(prompt)
    if img_data:
        bot.send_photo(message.chat.id, img_data)
        bot.delete_message(message.chat.id, waiting.message_id)
    else:
        bot.edit_message_text("❌ Не удалось сгенерировать изображение. Проверьте API ключи и баланс в кабинете разработчика Сбера.",
                              message.chat.id, waiting.message_id)

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/'):
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# --- 5. ЗАПУСК БОТА ---
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
