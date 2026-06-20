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

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
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
        return None
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {GIGACHAT_AUTH_KEY}"
    }
    data = {"scope": "GIGACHAT_API_PERS"}
    try:
        response = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                                 headers=headers, data=data, verify=False, timeout=30)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            logging.error(f"GigaChat token error: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"GigaChat token exception: {e}")
        return None

def download_gigachat_file(token, file_id):
    url = f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content"
    headers = {"Authorization": f"Bearer {token}", "Accept": "image/jpeg"}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            return response.content
        else:
            logging.error(f"GigaChat file download error: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"GigaChat file download exception: {e}")
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
    except:
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

# ================== 3. РЕДАКТИРОВАНИЕ ИЗОБРАЖЕНИЙ ==================
def edit_image_pro(prompt, image_base64):
    short = prompt.split('.')[0].strip()[:300]
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
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

# ================== 4. ГЕНЕРАЦИЯ ВИДЕО (ОСНОВНАЯ + FALLBACK) ==================
def generate_video_seedance(prompt, first_frame_b64=None, last_frame_b64=None):
    """Основная модель: ByteDance Seedance 2.0 (480p)."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    content = [{"type": "text", "text": prompt}]
    if first_frame_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{first_frame_b64}"}})
    if last_frame_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{last_frame_b64}"}})

    payload = {
        "model": "bytedance/seedance-2.0",
        "messages": [{"role": "user", "content": content}],
        "modalities": ["video", "text"],
        "resolution": "480p"   # можно изменить на 720p или 1080p, цена будет выше
    }

    logging.info("Seedance 2.0: отправка запроса...")
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            logging.info(f"Seedance 2.0: ответ {json.dumps(data, ensure_ascii=False)[:500]}")
            msg = data["choices"][0]["message"]
            if "videos" in msg and msg["videos"]:
                video_url = msg["videos"][0]["video_url"]["url"]
                return requests.get(video_url).content
            elif msg.get("content", "").startswith("http"):
                return requests.get(msg["content"]).content
            else:
                task_id = data.get("task_id") or msg.get("task_id")
                if task_id:
                    logging.info(f"Seedance: task_id {task_id}, polling...")
                    return poll_video_task(task_id, headers)
        else:
            logging.error(f"Seedance 2.0: ошибка {resp.status_code} – {resp.text[:300]}")
        return None
    except Exception as e:
        logging.error(f"Seedance 2.0: исключение {e}")
        return None

def generate_video_kling(prompt, first_frame_b64=None, last_frame_b64=None):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    content = [{"type": "text", "text": prompt}]
    if first_frame_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{first_frame_b64}"}})
    if last_frame_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{last_frame_b64}"}})

    payload = {
        "model": "kwaivgi/kling-v3-pro",
        "messages": [{"role": "user", "content": content}],
        "modalities": ["video", "text"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            msg = data["choices"][0]["message"]
            if "videos" in msg and msg["videos"]:
                return requests.get(msg["videos"][0]["video_url"]["url"]).content
            elif msg.get("content", "").startswith("http"):
                return requests.get(msg["content"]).content
            task_id = data.get("task_id") or msg.get("task_id")
            if task_id:
                return poll_video_task(task_id, headers)
        return None
    except:
        return None

def generate_video_svd(prompt, first_frame_b64=None):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    content = [{"type": "text", "text": prompt}]
    if first_frame_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{first_frame_b64}"}})

    payload = {
        "model": "stabilityai/stable-video-diffusion",
        "messages": [{"role": "user", "content": content}],
        "modalities": ["video", "text"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)
        if resp.status_code == 200:
            msg = resp.json()["choices"][0]["message"]
            if "videos" in msg and msg["videos"]:
                return requests.get(msg["videos"][0]["video_url"]["url"]).content
        return None
    except:
        return None

def poll_video_task(task_id, headers, max_attempts=15, interval=10):
    url = f"{OPENROUTER_TASK_URL}/{task_id}"
    for attempt in range(1, max_attempts+1):
        time.sleep(interval)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "completed":
                    video_url = data.get("result", {}).get("video_url")
                    if video_url:
                        return requests.get(video_url).content
                elif data.get("status") == "failed":
                    logging.error(f"Task {task_id} failed.")
                    return None
        except:
            pass
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

# Остальные обработчики (инлайн, загрузка фото, генерация, редактирование, видео) идентичны предыдущей версии.
# Для краткости я опущу их дублирование, но в полном коде они должны быть.
# [Здесь вставьте обработчики из предыдущего полного кода: select_generate_model, select_edit_model, select_face_mode,
#  handle_generate_prompt, handle_awaiting_photo, handle_awaiting_prompt,
#  select_video_mode, handle_video_first_frame, choose_last_frame, handle_video_last_frame, handle_video_prompt,
#  handle_text_chat, handle_other]

# Запуск (без изменений)
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
