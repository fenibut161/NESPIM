import os
import telebot
import requests
import time
import uuid
import re
import base64
import urllib3
import json
import logging
from flask import Flask
from threading import Thread
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Отключаем предупреждения SSL для тестов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (Render) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")   # для генерации через Сбер

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ================== 1. GIGACHAT (KANDINSKY) ДЛЯ ГЕНЕРАЦИИ ПО /image ==================
def get_gigachat_token():
    if not GIGACHAT_AUTH_KEY:
        return None
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {GIGACHAT_AUTH_KEY}"
    }
    data = {"scope": "GIGACHAT_API_PERS"}
    try:
        response = requests.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers=headers, data=data, verify=False, timeout=30
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            return None
    except Exception:
        return None

def download_gigachat_file(token, file_id):
    url = f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content"
    headers = {"Authorization": f"Bearer {token}", "Accept": "image/jpeg"}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            return response.content
        return None
    except Exception:
        return None

def generate_gigachat_image(prompt):
    token = get_gigachat_token()
    if not token:
        return None
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": "Ты — художник, создающий изображения."},
            {"role": "user", "content": prompt}
        ],
        "function_call": "auto"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=60)
        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content']
            match = re.search(r'src="([a-f0-9\-]+)"', content)
            if match:
                file_id = match.group(1)
                return download_gigachat_file(token, file_id)
        return None
    except Exception:
        return None

# ================== 2. OPENROUTER ДЛЯ ТЕКСТА ==================
def ask_openrouter_text(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",   # замени на юзернейм бота или оставь пустым
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": "openrouter/free",          # авто-выбор бесплатной модели
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        logging.info(f"Sending request to OpenRouter with model {payload['model']}")
        response = requests.post(
            OPENROUTER_URL,
            json=payload,
            headers=headers,
            timeout=90                        # увеличенный таймаут для медленных моделей
        )
        logging.info(f"OpenRouter response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            logging.info(f"Response data: {json.dumps(data, ensure_ascii=False)[:200]}...")  # первые 200 символов
            # Иногда ответ может быть в другом поле (например, при reasoning)
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                return "⚠️ Модель вернула пустой ответ"
        else:
            logging.error(f"OpenRouter error: {response.status_code} - {response.text}")
            return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        logging.error(f"Exception in ask_openrouter_text: {e}")
        return f"⚠️ Ошибка соединения: {e}"

# ================== 3. OPENROUTER ДЛЯ РЕДАКТИРОВАНИЯ ИЗОБРАЖЕНИЙ ==================
def edit_image_img2img(prompt, image_base64):
    """
    Редактирование изображения (img2img) через Google Gemini Flash Image.
    Модель возвращает готовое изображение прямо в base64 или как временный URL.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",   # замени на свой
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": "x-ai/grok-imagine-image-quality",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ],
        "modalities": ["image", "text"]   # обязательно
    }

    try:
        logging.info("Отправляю img2img запрос с Gemini Flash Image...")
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        logging.info(f"Статус ответа: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            logging.info(f"Ответ (первые 500 символов): {json.dumps(data, ensure_ascii=False)[:500]}")
            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0].get("message", {})
                # Ищем изображение в поле images (как обычно)
                if "images" in msg and len(msg["images"]) > 0:
                    img_url = msg["images"][0]["image_url"]["url"]
                else:
                    # Иногда Gemini возвращает изображение прямо в content (base64) как строку
                    content = msg.get("content", "")
                    if content.startswith("data:image/png;base64,"):
                        img_url = content
                    else:
                        logging.error("Нет ни images, ни base64 в content")
                        return None

                # Обрабатываем img_url: если это data-URI – декодируем, иначе скачиваем
                if img_url.startswith("data:image/"):
                    # Формат: data:image/png;base64,xxxx
                    base64_part = img_url.split(",", 1)[1]
                    img_data = base64.b64decode(base64_part)
                    logging.info("Изображение получено из base64 (data URI).")
                    return img_data
                else:
                    # Это обычный URL – скачиваем
                    img_data = requests.get(img_url).content
                    logging.info("Изображение скачано по URL.")
                    return img_data
            else:
                logging.error("Пустой ответ API.")
        else:
            logging.error(f"Ошибка API: {resp.status_code} – {resp.text[:300]}")
        return None
    except Exception as e:
        logging.error(f"Исключение при img2img: {e}")
        return None
# ================== 4. ОБРАБОТЧИКИ КОМАНД ТЕЛЕГРАМ ==================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🎨 Сгенерировать изображение"))
    bot.reply_to(
        message,
        "Привет! Я умею:\n"
        "1️⃣ Общаться (просто напиши текст)\n"
        "2️⃣ Генерировать картинки по команде /image <описание>\n"
        "3️⃣ Редактировать твои фото: отправь фото и в подписи напиши, что изменить\n\n"
        "Примеры:\n"
        "/image закат на море\n"
        "Фото + подпись: «сделай фон ночным, добавь звёзды»",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == "🎨 Сгенерировать изображение")
def image_button_handler(message):
    bot.send_message(message.chat.id, "✏️ Напиши команду /image и описание, например:\n/image робот на велосипеде")

@bot.message_handler(commands=['image'])
def handle_image_command(message):
    prompt = message.text.replace('/image', '', 1).strip()
    if not prompt:
        bot.reply_to(message, "✏️ Напиши описание после команды, например: /image кот в космосе")
        return
    waiting = bot.reply_to(message, "🎨 Генерирую картинку через Kandinsky, подожди...")
    img_data = generate_gigachat_image(prompt)
    if img_data:
        bot.delete_message(message.chat.id, waiting.message_id)
        bot.send_photo(message.chat.id, img_data, caption="✅ Вот что получилось:")
    else:
        bot.edit_message_text(
            "❌ Не удалось сгенерировать изображение. Проверь GIGACHAT_AUTH_KEY или попробуй позже.",
            message.chat.id, waiting.message_id
        )

@bot.message_handler(content_types=['photo'])
@bot.message_handler(content_types=['photo'])
def handle_photo_edit(message):
    prompt = message.caption or "Отредактируй это изображение, улучши качество и стиль"
    waiting = bot.reply_to(message, "🎨 Редактирую изображение...")

    # Скачиваем фото
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    base64_image = base64.b64encode(downloaded_file).decode('utf-8')

    # Получаем отредактированное изображение
    result_image = edit_image_img2img(prompt, base64_image)

    try:
        bot.delete_message(message.chat.id, waiting.message_id)
    except:
        pass

    if result_image:
        logging.info(f"Размер result_image: {len(result_image)} байт")

        # Сжимаем до безопасного JPEG
        try:
            img = Image.open(io.BytesIO(result_image))
            # Принудительно уменьшаем до 800×800
            img.thumbnail((800, 800), Image.LANCZOS)
            img = img.convert("RGB")  # убираем прозрачность
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            compressed = buf.getvalue()
            logging.info(f"Размер после сжатия: {len(compressed)} байт")
        except Exception as e:
            logging.error(f"Ошибка сжатия: {e}")
            compressed = result_image  # fallback

        # Пытаемся отправить как фото
        try:
            bot.send_photo(message.chat.id, compressed, caption="✅ Отредактированное изображение:")
            logging.info("Фото отправлено успешно.")
        except Exception as e:
            logging.error(f"Ошибка отправки фото: {e}")
            # fallback: отправляем как документ (исходный файл)
            try:
                bot.send_document(message.chat.id, result_image, caption="✅ Результат (документ)")
                logging.info("Отправлено как документ.")
            except Exception as e2:
                logging.error(f"Не удалось отправить даже документ: {e2}")
                bot.send_message(message.chat.id, "❌ Не удалось отправить изображение.")
    else:
        bot.send_message(
            message.chat.id,
            "❌ Не удалось обработать изображение. Попробуй другой запрос или позже."
        )

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.text.startswith('/') or message.text == "🎨 Сгенерировать изображение":
        return
    reply = ask_openrouter_text(message.text)
    bot.reply_to(message, reply)

# ================== 5. ЗАПУСК БОТА С АВТОПЕРЕЗАПУСКОМ ==================
def run_bot():
    logging.info("✅ Бот запущен и слушает сообщения...")
    # Удаляем вебхук, чтобы избежать конфликта
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"❌ Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
