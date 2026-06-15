import os
import telebot
import requests
import time
import uuid
import re
import urllib3
from flask import Flask
from threading import Thread

# Отключаем предупреждения (для тестов, в проде лучше убрать)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ИЗ RENDER ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")   # <-- Это ваш Authorization key (Basic)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# ========== 1. ПОЛУЧАЕМ ACCESS TOKEN (действует 30 минут) ==========
def get_gigachat_token():
    """Возвращает access_token или None, если не удалось."""
    if not GIGACHAT_AUTH_KEY:
        print("GIGACHAT_AUTH_KEY не задан в переменных окружения")
        return None

    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),              # уникальный идентификатор запроса
        "Authorization": f"Basic {GIGACHAT_AUTH_KEY}"  # именно так!
    }
    data = {
        "scope": "GIGACHAT_API_PERS"
    }
    try:
        response = requests.post(url, headers=headers, data=data, verify=False, timeout=30)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            print(f"Ошибка получения токена: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Исключение при получении токена: {e}")
        return None

# ========== 2. ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЯ ЧЕРЕЗ GIGACHAT ==========
def generate_gigachat_image(prompt: str):
    # Шаг 1: получаем токен
    token = get_gigachat_token()
    if not token:
        return None

    # Шаг 2: отправляем запрос на генерацию
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    # Промпт с указанием, что нужно сгенерировать картинку
    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": "Ты — художник, который создаёт изображения по запросу. Генерируй картинки."},
            {"role": "user", "content": prompt}
        ],
        "function_call": "auto"          # Включает генерацию изображений
    }
    try:
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=60)
        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content']
            # Ищем в ответе ID файла (пример: <img src="123e4567-e89b-12d3-a456-426614174000"/>)
            match = re.search(r'src="([a-f0-9\-]+)"', content)
            if match:
                file_id = match.group(1)
                # Скачиваем картинку
                img_data = download_gigachat_file(token, file_id)
                return img_data
            else:
                print(f"ID файла не найден в ответе: {content}")
                return None
        else:
            print(f"Ошибка генерации: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Исключение при генерации: {e}")
        return None

# ========== 3. СКАЧИВАНИЕ ФАЙЛА ИЗ GIGACHAT ==========
def download_gigachat_file(token: str, file_id: str):
    url = f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "image/jpeg"   # или image/png
    }
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            return response.content
        else:
            print(f"Ошибка скачивания: {response.status_code}")
            return None
    except Exception as e:
        print(f"Исключение при скачивании: {e}")
        return None

# ========== 4. ТЕКСТОВЫЙ ДИАЛОГ ЧЕРЕЗ OPENROUTER (DeepSeek) ==========
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
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"⚠️ Ошибка соединения: {e}"

# ========== 5. ОБРАБОТЧИКИ КОМАНД ТЕЛЕГРАМ ==========
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message,
        "Привет! Я умею общаться и создавать картинки.\n"
        "Просто напиши текст, чтобы поговорить.\n"
        "Используй команду /image <описание>, чтобы сгенерировать изображение через Kandinsky.\n"
        "Пример: /image кот в космосе"
    )

@bot.message_handler(commands=['image'])
def handle_image_command(message):
    prompt = message.text.replace('/image', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "✏️ Напиши описание после команды, например: /image закат на Бали")
        return
    waiting = bot.reply_to(message, "🎨 Генерирую картинку через Kandinsky, подожди...")
    img_data = generate_gigachat_image(prompt)
    if img_data:
        bot.delete_message(message.chat.id, waiting.message_id)
        bot.send_photo(message.chat.id, img_data)
    else:
        bot.edit_message_text(
            "❌ Не удалось сгенерировать изображение. Проверь переменную GIGACHAT_AUTH_KEY в Render.",
            message.chat.id, waiting.message_id
        )

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/'):
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# ========== 6. ЗАПУСК БОТА С АВТОПЕРЕЗАПУСКОМ ==========
def run_bot():
    print("✅ Бот запущен и слушает сообщения...")
    # Очищаем вебхук, чтобы избежать конфликта
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass
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
