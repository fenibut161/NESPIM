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
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image
import io

# Отключаем предупреждения SSL для тестов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (Render) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Словари состояний
user_state = {}          # текущее состояние пользователя
user_edit_model = {}     # модель редактирования (только nanobanana, но оставим для совместимости)
user_generate_model = {} # модель генерации (gigachat / nanobanana)
user_pending_photo = {}  # временное хранение base64 фото для редактирования

# ================== 1. GIGACHAT (KANDINSKY) ==================
def get_gigachat_token():
    if not GIGACHAT_AUTH_KEY:
        logging.error("GigaChat: ключ авторизации не задан")
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
            token = response.json().get("access_token")
            logging.info("GigaChat: токен успешно получен")
            return token
        else:
            logging.error(f"GigaChat: ошибка получения токена {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"GigaChat: исключение при получении токена: {e}")
        return None

def download_gigachat_file(token, file_id):
    url = f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content"
    headers = {"Authorization": f"Bearer {token}", "Accept": "image/jpeg"}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            logging.info(f"GigaChat: файл {file_id} скачан, размер {len(response.content)} байт")
            return response.content
        else:
            logging.error(f"GigaChat: ошибка скачивания файла {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"GigaChat: исключение при скачивании файла: {e}")
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
        logging.info(f"GigaChat: запрос генерации (промт: {prompt[:100]}...)")
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=60)
        logging.info(f"GigaChat: статус ответа {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content']
            logging.info(f"GigaChat: контент ответа (первые 300 символов): {content[:300]}")
            match = re.search(r'src="([a-f0-9\-]+)"', content)
            if match:
                file_id = match.group(1)
                logging.info(f"GigaChat: найден file_id: {file_id}")
                file_data = download_gigachat_file(token, file_id)
                if file_data:
                    return file_data
                else:
                    logging.error("GigaChat: не удалось скачать файл по ID")
            else:
                logging.error("GigaChat: в ответе не найден src с file_id")
                logging.error(f"Полный ответ: {json.dumps(data, ensure_ascii=False)[:500]}")
        else:
            logging.error(f"GigaChat: ошибка API {response.status_code}: {response.text[:300]}")
    except Exception as e:
        logging.error(f"GigaChat: исключение: {e}")
    return None

# ================== 2. OPENROUTER ТЕКСТ ==================
def ask_openrouter_text(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
        if response.status_code == 200:
            data = response.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                return "⚠️ Модель вернула пустой ответ"
        else:
            return f"❌ Ошибка API: {response.status_code}"
    except Exception as e:
        return f"⚠️ Ошибка соединения: {e}"

# ================== 3. РЕДАКТИРОВАНИЕ ЧЕРЕЗ NANO BANANA PRO ==================
def edit_image_nanobanana(prompt, image_base64):
    """
    Редактирование через google/gemini-3-pro-image-preview (Nano Banana Pro).
    Возвращает кортеж (image_bytes, text_response). Одно из значений может быть None.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": "google/gemini-3-pro-image-preview",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты — ассистент по редактированию изображений. "
                    "Пользователь пришлёт изображение и описание правок. "
                    "Отредактируй изображение строго по описанию и верни только изображение, "
                    "без каких-либо текстовых пояснений."
                )
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ],
        "modalities": ["image", "text"]
    }
    try:
        logging.info("Nano Banana Pro: запрос редактирования...")
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            logging.info(f"Nano Banana Pro: ответ (первые 500 символов): {json.dumps(data, ensure_ascii=False)[:500]}")
            msg = data["choices"][0].get("message", {})
            # Ищем изображение
            if "images" in msg and len(msg["images"]) > 0:
                img_url = msg["images"][0]["image_url"]["url"]
            else:
                content = msg.get("content", "")
                if content and content.startswith("data:image/png;base64,"):
                    img_url = content
                else:
                    text_response = msg.get("content", None)
                    logging.error("Nano Banana Pro: изображение не получено, модель вернула текст.")
                    return None, text_response
            # Обрабатываем URL
            if img_url.startswith("data:image/"):
                base64_part = img_url.split(",", 1)[1]
                logging.info("Nano Banana Pro: изображение получено из base64")
                return base64.b64decode(base64_part), None
            else:
                img_data = requests.get(img_url).content
                logging.info("Nano Banana Pro: изображение скачано по URL")
                return img_data, None
        else:
            logging.error(f"Nano Banana Pro: ошибка API {resp.status_code}: {resp.text[:300]}")
            return None, None
    except Exception as e:
        logging.error(f"Nano Banana Pro: исключение: {e}")
        return None, None

# ================== 4. ГЛАВНОЕ МЕНЮ ==================
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🖼 Создать изображение"),
        KeyboardButton("🎨 Редактировать фото"),
        KeyboardButton("🎥 Создать видео"),
        KeyboardButton("💬 Спросить (чат)")
    )
    return markup

def send_main_menu(chat_id, text="Главное меню:"):
    bot.send_message(chat_id, text, reply_markup=main_menu_keyboard())

def back_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("🔙 Главное меню"))

def send_back_button(chat_id, text="Нажми кнопку для возврата"):
    bot.send_message(chat_id, text, reply_markup=back_keyboard())

# ================== 5. ОБРАБОТЧИКИ КОМАНД ==================
@bot.message_handler(commands=['start'])
def start(message):
    user_state[message.chat.id] = None
    send_main_menu(message.chat.id, "👋 Привет! Выбери действие:")

# ----------------- Обработка кнопок главного меню -----------------
@bot.message_handler(func=lambda m: m.text == "🖼 Создать изображение")
def menu_generate_image(message):
    user_state[message.chat.id] = "select_model_generate"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🆓 GigaChat (бесплатно)", callback_data="gen_gigachat"),
        InlineKeyboardButton("💎 Nano Banana Pro", callback_data="gen_nanobanana")
    )
    bot.send_message(message.chat.id, "Выбери модель для генерации:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎨 Редактировать фото")
def menu_edit_photo(message):
    user_state[message.chat.id] = "select_model_edit"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💎 Nano Banana Pro (платно)", callback_data="edit_nanobanana"),
        InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel")
    )
    bot.send_message(message.chat.id, "Редактирование фото доступно только через Nano Banana Pro (платно). Выберите действие:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
def menu_video(message):
    send_back_button(message.chat.id, "🎥 Функция создания видео пока в разработке.")

@bot.message_handler(func=lambda m: m.text == "💬 Спросить (чат)")
def menu_chat(message):
    user_state[message.chat.id] = None
    bot.send_message(message.chat.id, "Задай любой вопрос. Для возврата в меню нажми кнопку «🔙 Главное меню»",
                     reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_to_main(message):
    user_state[message.chat.id] = None
    user_edit_model.pop(message.chat.id, None)
    user_generate_model.pop(message.chat.id, None)
    send_main_menu(message.chat.id)

# ----------------- Обработка выбора модели (инлайн-колбэки) -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith('gen_'))
def select_generate_model(call):
    chat_id = call.message.chat.id
    if call.data == 'gen_gigachat':
        user_generate_model[chat_id] = 'gigachat'
        bot.answer_callback_query(call.id, "Выбрана GigaChat")
    else:
        user_generate_model[chat_id] = 'nanobanana'
        bot.answer_callback_query(call.id, "Выбрана Nano Banana Pro")
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = "awaiting_generate_prompt"
    bot.send_message(chat_id, "Введи описание изображения:", reply_markup=back_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_'))
def select_edit_model(call):
    chat_id = call.message.chat.id
    if call.data == 'edit_cancel':
        bot.answer_callback_query(call.id, "Отмена")
        bot.delete_message(chat_id, call.message.message_id)
        user_state[chat_id] = None
        send_main_menu(chat_id)
        return
    # Единственный вариант – nanobanana
    user_edit_model[chat_id] = 'nanobanana'
    bot.answer_callback_query(call.id, "Выбрана Nano Banana Pro")
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = "awaiting_photo"
    bot.send_message(chat_id, "📸 Загрузи фото, которое нужно отредактировать.", reply_markup=back_keyboard())

# ----------------- Обработка ввода описания для генерации -----------------
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_generate_prompt")
def handle_generate_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    model = user_generate_model.get(chat_id, 'gigachat')
    user_state[chat_id] = None
    user_generate_model.pop(chat_id, None)

    if model == 'gigachat':
        waiting = bot.send_message(chat_id, "🎨 Генерирую через GigaChat...")
        img_data = generate_gigachat_image(prompt)
    else:  # nanobanana text-to-image
        waiting = bot.send_message(chat_id, "💎 Генерирую через Nano Banana Pro (платно)...")
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/Jastick_bot",
            "X-Title": "TelegramBot"
        }
        payload = {
            "model": "google/gemini-3-pro-image-preview",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "modalities": ["image", "text"]
        }
        try:
            logging.info("Nano Banana Pro: запрос text-to-image...")
            resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0].get("message", {})
                if "images" in msg and len(msg["images"]) > 0:
                    img_url = msg["images"][0]["image_url"]["url"]
                else:
                    content = msg.get("content", "")
                    if content and content.startswith("data:image/png;base64,"):
                        img_url = content
                    else:
                        logging.error("Nano Banana Pro: нет изображения в ответе")
                        img_data = None
                if img_url:
                    if img_url.startswith("data:image/"):
                        base64_part = img_url.split(",", 1)[1]
                        img_data = base64.b64decode(base64_part)
                    else:
                        img_data = requests.get(img_url).content
            else:
                logging.error(f"Nano Banana Pro: ошибка {resp.status_code}: {resp.text[:300]}")
                img_data = None
        except Exception as e:
            logging.error(f"Nano Banana Pro: исключение: {e}")
            img_data = None

    if img_data:
        try:
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 800), Image.LANCZOS)
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            compressed = buf.getvalue()
        except:
            compressed = img_data
        try:
            bot.delete_message(chat_id, waiting.message_id)
        except:
            pass
        bot.send_photo(chat_id, compressed, caption="✅ Готово!")
    else:
        bot.edit_message_text("❌ Не удалось сгенерировать изображение.", chat_id, waiting.message_id)
    send_main_menu(chat_id)

# ----------------- Обработка загрузки фото (состояние awaiting_photo) -----------------
@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_photo")
def handle_awaiting_photo(message):
    chat_id = message.chat.id
    user_state[chat_id] = "awaiting_prompt"
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    user_pending_photo[chat_id] = base64.b64encode(downloaded_file).decode('utf-8')
    bot.send_message(chat_id, "✏️ Теперь напиши, что изменить (промт):", reply_markup=back_keyboard())

# ----------------- Обработка ввода промта после фото -----------------
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_prompt")
def handle_awaiting_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    photo_base64 = user_pending_photo.pop(chat_id, None)
    if not photo_base64:
        bot.send_message(chat_id, "⚠️ Сначала загрузи фото, а затем описание.")
        send_main_menu(chat_id)
        return

    user_state[chat_id] = None
    waiting = bot.send_message(chat_id, "💎 Редактирую через Nano Banana Pro (платно)...")
    img_data, text_response = edit_image_nanobanana(prompt, photo_base64)

    try:
        bot.delete_message(chat_id, waiting.message_id)
    except:
        pass

    if img_data:
        try:
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 800), Image.LANCZOS)
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            compressed = buf.getvalue()
            bot.send_photo(chat_id, compressed, caption="✅ Отредактированное изображение")
        except Exception as e:
            logging.error(f"Ошибка сжатия/отправки: {e}")
            bot.send_document(chat_id, img_data, caption="✅ Результат (документ)")
    elif text_response:
        bot.send_message(chat_id, f"⚠️ Модель не сгенерировала изображение, но прислала описание:\n\n{text_response[:4000]}")
    else:
        bot.send_message(chat_id, "❌ Не удалось отредактировать изображение.")
    send_main_menu(chat_id)

# ----------------- Обработка обычного текста (чат) -----------------
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text_chat(message):
    if message.text.startswith('/'):
        return
    state = user_state.get(message.chat.id)
    if state in ["awaiting_prompt", "awaiting_generate_prompt", "awaiting_photo"]:
        return
    reply = ask_openrouter_text(message.text)
    bot.send_message(message.chat.id, reply, reply_markup=back_keyboard())

# ----------------- Обработка всех остальных сообщений -----------------
@bot.message_handler(func=lambda m: True)
def handle_other(message):
    bot.send_message(message.chat.id, "Пожалуйста, используй кнопки меню.")

# ================== 6. ЗАПУСК ==================
def run_bot():
    logging.info("✅ Бот запущен и слушает сообщения...")
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
