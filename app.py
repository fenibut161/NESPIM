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
user_state = {}
user_edit_model = {}     # 'pro' или 'flash'
user_face_mode = {}      # 'keep_face' или 'full_edit'
user_generate_model = {} # 'gigachat' или 'nanobanana'
user_pending_photo = {}

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

# ================== 3. РЕДАКТИРОВАНИЕ ИЗОБРАЖЕНИЙ ==================
def edit_image_pro(prompt, image_base64):
    """Редактирование через Google Gemini 3 Pro Image Preview с авто‑сокращением промта."""
    short_prompt = prompt.split('.')[0].strip()
    if len(short_prompt) > 300:
        short_prompt = short_prompt[:300] + "..."
    logging.info(f"PRO: исходный промт длиной {len(prompt)} символов, используется: {short_prompt}")

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
                "content": "Ты — редактор изображений. Отредактируй прикреплённое изображение по описанию пользователя и верни только готовое изображение. Не добавляй текст."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": short_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ],
        "modalities": ["image", "text"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            msg = data["choices"][0]["message"]
            logging.info(f"PRO: полный ответ: {json.dumps(msg, ensure_ascii=False)[:500]}")
            if "images" in msg and msg["images"]:
                img_url = msg["images"][0]["image_url"]["url"]
            elif msg.get("content", "").startswith("data:image/"):
                img_url = msg["content"]
            else:
                logging.error("PRO: изображение отсутствует, возможно текст.")
                return None, msg.get("content")
            if img_url.startswith("data:image/"):
                return base64.b64decode(img_url.split(",", 1)[1]), None
            else:
                return requests.get(img_url).content, None
        else:
            logging.error(f"PRO: ошибка {resp.status_code} – {resp.text[:300]}")
            return None, None
    except Exception as e:
        logging.error(f"PRO: исключение {e}")
        return None, None

def edit_image_flash(prompt, image_base64):
    """
    Редактирование через Google Gemini 3.1 Flash Image.
    Подробное логирование для диагностики.
    """
    MODEL = "google/gemini-3.1-flash-image"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": MODEL,
        "messages": [
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
        logging.info(f"FLASH ({MODEL}): отправка запроса...")
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        logging.info(f"FLASH ({MODEL}): статус ответа {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            msg = data["choices"][0]["message"]
            logging.info(f"FLASH ({MODEL}): ответ получен. Первые 500 символов: {json.dumps(msg, ensure_ascii=False)[:500]}")
            if "images" in msg and msg["images"]:
                img_url = msg["images"][0]["image_url"]["url"]
            elif msg.get("content", "").startswith("data:image/"):
                img_url = msg["content"]
            else:
                logging.error(f"FLASH ({MODEL}): изображение отсутствует, возможно текст.")
                return None, msg.get("content")
            # Обрабатываем URL
            if img_url.startswith("data:image/"):
                return base64.b64decode(img_url.split(",", 1)[1]), None
            else:
                return requests.get(img_url).content, None
        else:
            logging.error(f"FLASH ({MODEL}): ошибка API {resp.status_code} – {resp.text[:300]}")
            return None, None
    except Exception as e:
        logging.error(f"FLASH ({MODEL}): исключение {e}")
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

# ================== 5. ОБРАБОТЧИКИ ==================
@bot.message_handler(commands=['start'])
def start(message):
    user_state[message.chat.id] = None
    send_main_menu(message.chat.id, "👋 Привет! Выбери действие:")

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
        InlineKeyboardButton("💎 Nano Banana Pro", callback_data="edit_pro"),
        InlineKeyboardButton("⚡ Gemini Flash 3.1 (баланс)", callback_data="edit_flash")
    )
    bot.send_message(message.chat.id, "Выбери модель редактирования:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
def menu_video(message):
    bot.send_message(message.chat.id, "🎥 Функция создания видео пока в разработке.", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "💬 Спросить (чат)")
def menu_chat(message):
    user_state[message.chat.id] = None
    bot.send_message(message.chat.id, "Задай любой вопрос. Для возврата нажми «🔙 Главное меню»", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_to_main(message):
    user_state[message.chat.id] = None
    send_main_menu(message.chat.id)

# Инлайн-колбэки
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
    if call.data == 'edit_pro':
        user_edit_model[chat_id] = 'pro'
        bot.answer_callback_query(call.id, "Выбрана Nano Banana Pro")
    else:
        user_edit_model[chat_id] = 'flash'
        bot.answer_callback_query(call.id, "Выбрана Gemini Flash 3.1")
    bot.delete_message(chat_id, call.message.message_id)
    # Спрашиваем про лицо
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔒 Сохранить лицо", callback_data="face_keep"),
        InlineKeyboardButton("🎨 Полное редактирование", callback_data="face_full")
    )
    bot.send_message(chat_id, "Как обрабатывать лицо на фото?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('face_'))
def select_face_mode(call):
    chat_id = call.message.chat.id
    if call.data == 'face_keep':
        user_face_mode[chat_id] = 'keep_face'
        bot.answer_callback_query(call.id, "Лицо будет сохранено")
    else:
        user_face_mode[chat_id] = 'full_edit'
        bot.answer_callback_query(call.id, "Полное редактирование")
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = "awaiting_photo"
    bot.send_message(chat_id, "📸 Загрузи фото, которое нужно отредактировать.", reply_markup=back_keyboard())

# Генерация промта
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_generate_prompt")
def handle_generate_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    model = user_generate_model.pop(chat_id, 'gigachat')
    user_state[chat_id] = None

    if model == 'gigachat':
        waiting = bot.send_message(chat_id, "🎨 Генерирую через GigaChat...")
        img_data = generate_gigachat_image(prompt)
    else:
        waiting = bot.send_message(chat_id, "💎 Генерирую через Nano Banana Pro (платно)...")
        short_prompt = prompt.split('.')[0].strip()
        if len(short_prompt) > 300:
            short_prompt = short_prompt[:300] + "..."
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/Jastick_bot",
            "X-Title": "TelegramBot"
        }
        payload = {
            "model": "google/gemini-3-pro-image-preview",
            "messages": [{"role": "user", "content": short_prompt}],
            "modalities": ["image", "text"]
        }
        try:
            resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                if "images" in msg and msg["images"]:
                    img_url = msg["images"][0]["image_url"]["url"]
                elif msg.get("content", "").startswith("data:image/"):
                    img_url = msg["content"]
                else:
                    img_data = None
                if img_url:
                    if img_url.startswith("data:image/"):
                        img_data = base64.b64decode(img_url.split(",", 1)[1])
                    else:
                        img_data = requests.get(img_url).content
            else:
                img_data = None
        except:
            img_data = None

    if img_data:
        try:
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 800), Image.LANCZOS)
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            bot.send_photo(chat_id, buf.getvalue(), caption="✅ Готово!")
        except:
            bot.send_document(chat_id, img_data, caption="✅ Готово (файл)")
    else:
        bot.send_message(chat_id, "❌ Не удалось сгенерировать изображение.")
    send_main_menu(chat_id)

# Загрузка фото для редактирования
@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_photo")
def handle_awaiting_photo(message):
    chat_id = message.chat.id
    user_state[chat_id] = "awaiting_prompt"
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    user_pending_photo[chat_id] = base64.b64encode(downloaded).decode('utf-8')
    bot.send_message(chat_id, "✏️ Теперь напиши, что изменить (промт):", reply_markup=back_keyboard())

# Промт для редактирования
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_prompt")
def handle_awaiting_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    photo_base64 = user_pending_photo.pop(chat_id, None)
    if not photo_base64:
        bot.send_message(chat_id, "⚠️ Сначала загрузи фото.")
        send_main_menu(chat_id)
        return

    model = user_edit_model.pop(chat_id, 'flash')
    face_mode = user_face_mode.pop(chat_id, 'full_edit')
    user_state[chat_id] = None

    # Инструкция сохранения лица
    if face_mode == 'keep_face':
        prompt = "Keep the face and facial features completely unchanged. Do not modify the face. Only apply the following changes: " + prompt

    waiting = bot.send_message(chat_id, "🎨 Редактирую...")

    # Основная модель
    if model == 'pro':
        img_data, text = edit_image_pro(prompt, photo_base64)
        model_used = "Nano Banana Pro"
    else:
        img_data, text = edit_image_flash(prompt, photo_base64)
        model_used = "Gemini Flash 3.1"

    # Fallback на старую Flash 2.5, если новая не дала изображения
    if not img_data and model == 'flash':
        logging.warning("FLASH 3.1 не дала изображения, пробую FLASH 2.5.")
        # Временно заменяем модель на 2.5
        old_model = "google/gemini-2.5-flash-image"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/Jastick_bot",
            "X-Title": "TelegramBot"
        }
        payload = {
            "model": old_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_base64}"}}
                    ]
                }
            ],
            "modalities": ["image", "text"]
        }
        try:
            resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                if "images" in msg and msg["images"]:
                    img_url = msg["images"][0]["image_url"]["url"]
                elif msg.get("content", "").startswith("data:image/"):
                    img_url = msg["content"]
                else:
                    img_url = None
                if img_url:
                    if img_url.startswith("data:image/"):
                        img_data = base64.b64decode(img_url.split(",", 1)[1])
                    else:
                        img_data = requests.get(img_url).content
            else:
                img_data = None
        except:
            img_data = None
        model_used = "Gemini Flash 2.5 (запасной)"

    # Fallback на Flash 2.5, если Pro не дала изображения (уже было ранее, но теперь ещё и для новой Flash)
    if not img_data and model == 'pro':
        logging.warning("PRO не дала изображения, пробую FLASH 2.5.")
        img_data, text = edit_image_flash(prompt, photo_base64)  # здесь edit_image_flash всё ещё 3.1, поэтому лучше явно вызвать 2.5
        # На самом деле edit_image_flash сейчас указывает на 3.1, что может опять не сработать.
        # Поэтому лучше внутри этого блока также использовать проверенную 2.5.
        # Для простоты, мы можем здесь вызвать отдельную функцию или напрямую запрос к 2.5.
        # Но так как edit_image_flash теперь 3.1, мы продублируем запрос к 2.5.
        old_model = "google/gemini-2.5-flash-image"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/Jastick_bot",
            "X-Title": "TelegramBot"
        }
        payload = {
            "model": old_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{photo_base64}"}}
                    ]
                }
            ],
            "modalities": ["image", "text"]
        }
        try:
            resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                if "images" in msg and msg["images"]:
                    img_url = msg["images"][0]["image_url"]["url"]
                elif msg.get("content", "").startswith("data:image/"):
                    img_url = msg["content"]
                else:
                    img_url = None
                if img_url:
                    if img_url.startswith("data:image/"):
                        img_data = base64.b64decode(img_url.split(",", 1)[1])
                    else:
                        img_data = requests.get(img_url).content
            else:
                img_data = None
        except:
            img_data = None
        model_used = "Gemini Flash 2.5 (запасной)"

    try:
        bot.delete_message(chat_id, waiting.message_id)
    except:
        pass

    if img_data:
        caption = f"✅ Отредактировано ({model_used})"
        if face_mode == 'keep_face':
            caption += " с сохранением лица"
        try:
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 800), Image.LANCZOS)
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            bot.send_photo(chat_id, buf.getvalue(), caption=caption)
        except:
            bot.send_document(chat_id, img_data, caption=caption)
    elif text:
        bot.send_message(chat_id, f"⚠️ Модель вернула текстовое описание:\n\n{text[:4000]}")
    else:
        bot.send_message(chat_id, "❌ Не удалось отредактировать изображение.")
    send_main_menu(chat_id)

# Чат
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text_chat(message):
    if message.text.startswith('/'):
        return
    state = user_state.get(message.chat.id)
    if state in ["awaiting_prompt", "awaiting_generate_prompt", "awaiting_photo"]:
        return
    reply = ask_openrouter_text(message.text)
    bot.send_message(message.chat.id, reply, reply_markup=back_keyboard())

# Прочие сообщения
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
