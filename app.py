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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")

# ИСПРАВЛЕННЫЙ URL ДЛЯ ГЕНЕРАЦИИ ВИДЕО
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/video"          # правильный эндпоинт
OPENROUTER_TASK_URL = "https://openrouter.ai/api/v1/task"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Словари состояний
user_state = {}
user_edit_model = {}
user_face_mode = {}
user_generate_model = {}
user_pending_photo = {}
user_video_mode = {}
user_video_frames = {}

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
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
        if resp.status_code == 200:
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                return "⚠️ Пустой ответ"
        else:
            return f"❌ Ошибка API: {resp.status_code}"
    except Exception as e:
        return f"⚠️ Ошибка соединения: {e}"

# ================== 3. РЕДАКТИРОВАНИЕ ИЗОБРАЖЕНИЙ (без изменений) ==================
def edit_image_pro(prompt, image_base64):
    short = prompt.split('.')[0].strip()[:300]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "google/gemini-3-pro-image-preview",
        "messages": [
            {"role": "system", "content": "Отредактируй изображение по описанию и верни только изображение."},
            {"role": "user", "content": [
                {"type": "text", "text": short},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]}
        ],
        "modalities": ["image", "text"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            msg = resp.json()["choices"][0]["message"]
            img_url = msg.get("images", [{}])[0].get("image_url", {}).get("url")
            if not img_url:
                content = msg.get("content", "")
                if content.startswith("data:image/"):
                    img_url = content
                else:
                    return None, msg.get("content")
            if img_url.startswith("data:image/"):
                return base64.b64decode(img_url.split(",", 1)[1]), None
            return requests.get(img_url).content, None
        return None, None
    except:
        return None, None

def edit_image_flash(prompt, image_base64):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "google/gemini-3.1-flash-image",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]}],
        "modalities": ["image", "text"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            msg = resp.json()["choices"][0]["message"]
            img_url = msg.get("images", [{}])[0].get("image_url", {}).get("url")
            if not img_url:
                content = msg.get("content", "")
                if content.startswith("data:image/"):
                    img_url = content
                else:
                    return None, msg.get("content")
            if img_url.startswith("data:image/"):
                return base64.b64decode(img_url.split(",", 1)[1]), None
            return requests.get(img_url).content, None
        return None, None
    except:
        return None, None

def edit_image_flash_25(prompt, image_base64):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "google/gemini-2.5-flash-image",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]}],
        "modalities": ["image", "text"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            msg = resp.json()["choices"][0]["message"]
            img_url = msg.get("images", [{}])[0].get("image_url", {}).get("url")
            if not img_url:
                content = msg.get("content", "")
                if content.startswith("data:image/"):
                    img_url = content
                else:
                    return None, msg.get("content")
            if img_url.startswith("data:image/"):
                return base64.b64decode(img_url.split(",", 1)[1]), None
            return requests.get(img_url).content, None
        return None, None
    except:
        return None, None

# ================== 4. ГЕНЕРАЦИЯ ВИДЕО (ИСПРАВЛЕННАЯ) ==================
def compress_image_if_needed(b64_str, max_size=(640, 640), quality=80):
    """
    Сжимает изображение, если оно слишком большое (опционально).
    Можно использовать для уменьшения размера base64.
    """
    try:
        img_data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_data))
        img.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logging.error(f"Ошибка сжатия изображения: {e}")
        return b64_str  # возвращаем как есть

def generate_video_seedance(prompt, first_frame_b64=None, last_frame_b64=None):
    """
    Генерация видео через OpenRouter (Seedance 2.0) с исправленным URL и увеличенными таймаутами.
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": "bytedance/seedance-2.0",
        "prompt": prompt,
        "n": 1,
        "size": "480p",
        "output_format": "mp4"
    }
    # Если переданы кадры, сжимаем их для уменьшения размера (опционально)
    if first_frame_b64:
        compressed_first = compress_image_if_needed(first_frame_b64)
        payload["image"] = f"data:image/jpeg;base64,{compressed_first}"
    if last_frame_b64:
        compressed_last = compress_image_if_needed(last_frame_b64)
        payload["last_image"] = f"data:image/jpeg;base64,{compressed_last}"

    logging.info("=== ЗАПРОС К SEEDANCE 2.0 ===")
    logging.info(f"URL: {OPENROUTER_VIDEO_URL}")
    # Безопасное логирование (не выводим base64 целиком)
    safe_payload = {k: (f"<base64 len={len(v)}>" if 'base64' in str(v) else v) for k, v in payload.items()}
    logging.info(f"Payload: {json.dumps(safe_payload, ensure_ascii=False)}")

    try:
        resp = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=600)  # увеличенный таймаут
        logging.info(f"Seedance 2.0: HTTP {resp.status_code}")
        logging.info(f"Seedance 2.0: полный ответ: {resp.text}")  # полный лог для диагностики

        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                item = data["data"][0]
                if "b64_json" in item:
                    logging.info("Видео получено как base64")
                    return base64.b64decode(item["b64_json"])
                elif "url" in item:
                    logging.info(f"Видео получено как URL: {item['url']}")
                    return requests.get(item["url"]).content
            if "task_id" in data:
                logging.info(f"Получен task_id: {data['task_id']}, начинаю polling")
                return poll_video_task(data["task_id"], headers, max_attempts=40, interval=15)  # увеличенные параметры
            logging.error("Seedance: ответ не содержит data или task_id")
        else:
            logging.error(f"Seedance: ошибка {resp.status_code} – {resp.text[:500]}")
        return None
    except Exception as e:
        logging.error(f"Seedance: исключение {e}")
        return None

def poll_video_task(task_id, headers, max_attempts=40, interval=15):
    """Опрос статуса задачи генерации видео с увеличенным временем ожидания."""
    url = f"{OPENROUTER_TASK_URL}/{task_id}"
    logging.info(f"Начинаю опрос задачи {task_id}")
    for attempt in range(1, max_attempts + 1):
        time.sleep(interval)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                logging.info(f"Опрос {attempt}: статус {data.get('status')}")
                if data.get("status") == "completed":
                    video_url = data.get("result", {}).get("video_url")
                    if video_url:
                        logging.info(f"Видео готово: {video_url}")
                        return requests.get(video_url).content
                elif data.get("status") == "failed":
                    logging.error(f"Задача {task_id} провалилась: {data}")
                    return None
            else:
                logging.error(f"Опрос: статус {resp.status_code}, ответ {resp.text[:200]}")
        except Exception as e:
            logging.error(f"Ошибка опроса: {e}")
    logging.error(f"Истекло время ожидания для задачи {task_id}")
    return None

# ================== 5. ГЛАВНОЕ МЕНЮ ==================
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

# ================== 6. ОБРАБОТЧИКИ ==================
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
    user_state[message.chat.id] = "select_video_mode"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📝 Текст в видео", callback_data="vid_text"),
        InlineKeyboardButton("🖼 Картинка в видео", callback_data="vid_image")
    )
    bot.send_message(message.chat.id, "Выберите режим генерации видео:", reply_markup=markup)

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

# Генерация изображений
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

# Редактирование фото
@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_photo")
def handle_awaiting_photo(message):
    chat_id = message.chat.id
    user_state[chat_id] = "awaiting_prompt"
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    user_pending_photo[chat_id] = base64.b64encode(downloaded).decode('utf-8')
    bot.send_message(chat_id, "✏️ Теперь напиши, что изменить (промт):", reply_markup=back_keyboard())

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

    if face_mode == 'keep_face':
        prompt = "Keep the face and facial features completely unchanged. Do not modify the face. Only apply the following changes: " + prompt

    waiting = bot.send_message(chat_id, "🎨 Редактирую...")

    if model == 'pro':
        img_data, text = edit_image_pro(prompt, photo_base64)
        model_used = "Nano Banana Pro"
        if not img_data:
            img_data, text = edit_image_flash_25(prompt, photo_base64)
            model_used = "Gemini Flash 2.5 (запасной)"
    else:
        img_data, text = edit_image_flash(prompt, photo_base64)
        model_used = "Gemini Flash 3.1"
        if not img_data:
            img_data, text = edit_image_flash_25(prompt, photo_base64)
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

# ВИДЕО: выбор режима и загрузка кадров
@bot.callback_query_handler(func=lambda call: call.data.startswith('vid_'))
def select_video_mode(call):
    chat_id = call.message.chat.id
    if call.data == 'vid_text':
        user_video_mode[chat_id] = 'text'
        user_state[chat_id] = "awaiting_video_prompt"
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "Введи описание для видео:", reply_markup=back_keyboard())
    elif call.data == 'vid_image':
        user_video_mode[chat_id] = 'image_one'
        user_state[chat_id] = "awaiting_video_image_first"
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "📸 Загрузи ПЕРВЫЙ кадр (начальное изображение):", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_first")
def handle_video_first_frame(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode('utf-8')
    user_video_frames[chat_id] = {'first': b64, 'last': None}
    user_state[chat_id] = "awaiting_video_last_choice"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Да, загрузить второй кадр", callback_data="last_yes"),
        InlineKeyboardButton("Нет, только первый", callback_data="last_no")
    )
    bot.send_message(chat_id, "Хотите задать ПОСЛЕДНИЙ кадр (конечное изображение)?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('last_'))
def choose_last_frame(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, call.message.message_id)
    if call.data == 'last_yes':
        user_video_mode[chat_id] = 'image_two'
        user_state[chat_id] = "awaiting_video_image_last"
        bot.send_message(chat_id, "📸 Загрузи ПОСЛЕДНИЙ кадр:", reply_markup=back_keyboard())
    else:
        user_video_mode[chat_id] = 'image_one'
        user_state[chat_id] = "awaiting_video_prompt"
        bot.send_message(chat_id, "Введи описание для видео:", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_last")
def handle_video_last_frame(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode('utf-8')
    user_video_frames[chat_id]['last'] = b64
    user_state[chat_id] = "awaiting_video_prompt"
    bot.send_message(chat_id, "Введи описание для видео:", reply_markup=back_keyboard())

# ФИНАЛЬНАЯ ГЕНЕРАЦИЯ ВИДЕО
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_prompt")
def handle_video_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    user_state[chat_id] = None

    logging.info(f"=== НАЧАЛО ГЕНЕРАЦИИ ВИДЕО для {chat_id} ===")
    logging.info(f"Промт: {prompt}")
    first_frame = user_video_frames.get(chat_id, {}).get('first')
    last_frame = user_video_frames.get(chat_id, {}).get('last')
    user_video_frames.pop(chat_id, None)

    waiting = bot.send_message(chat_id, "🎬 Генерирую видео... Это может занять до 5 минут.")

    video_data = generate_video_seedance(prompt, first_frame, last_frame)

    try:
        bot.delete_message(chat_id, waiting.message_id)
    except:
        pass

    if video_data:
        try:
            bot.send_video(chat_id, video_data, caption="✅ Ваше видео готово!")
        except Exception as e:
            logging.error(f"Ошибка отправки видео: {e}")
            bot.send_document(chat_id, video_data, caption="✅ Видео (как файл)")
    else:
        logging.error("video_data == None, отправляю сообщение об ошибке")
        bot.send_message(chat_id, "❌ Не удалось создать видео. Попробуйте позже или измените описание.")
    send_main_menu(chat_id)

# Чат
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text_chat(message):
    if message.text.startswith('/'):
        return
    state = user_state.get(message.chat.id)
    if state in ["awaiting_prompt", "awaiting_generate_prompt", "awaiting_photo", "awaiting_video_prompt", "awaiting_video_image_first", "awaiting_video_image_last"]:
        return
    reply = ask_openrouter_text(message.text)
    bot.send_message(message.chat.id, reply, reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: True)
def handle_other(message):
    bot.send_message(message.chat.id, "Пожалуйста, используй кнопки меню.")

# ================== 7. ЗАПУСК ==================
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
