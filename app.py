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
from flask import Flask, send_from_directory
from threading import Thread
from telebot.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton,
                           LabeledPrice)
from PIL import Image
import io
from collections import defaultdict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"
OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images/generations"

ADMIN_ID = 534008787
DEMO_VIDEO_URL = "https://your-server.com/static/demo.mp4"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

os.makedirs("static", exist_ok=True)

# --- СЛОВАРИ СОСТОЯНИЙ И ДАННЫХ ---
user_state = {}
user_edit_model = {}      # 'seedream' или 'grok'
user_face_mode = {}
user_generate_model = {}  # 'gigachat', 'seedream' или 'grok'
user_pending_photo = {}
user_video_mode = {}
user_video_frames = {}
user_video_params = {}
user_video_model = {}
user_credits = {}
user_history = defaultdict(list)          # история видео (file_id)
user_credit_history = defaultdict(list)   # история кредитов: (timestamp, delta, reason)

# Счётчик сообщений для DeepSeek
user_message_count = defaultdict(int)

VIDEO_MODEL_FEATURES = {
    'bytedance/seedance-2.0': {'audio': True, 'resolution': True},
    'kwaivgi/kling-video-o1': {'audio': True, 'resolution': True},
    'kwaivgi/kling-v3-pro': {'audio': True, 'resolution': True},
}

PACKAGES = {
    'start': {'name': 'Старт', 'credits': 50, 'price': 250,
              'desc': '50 кредитов на любые операции'},
    'optima': {'name': 'Оптима', 'credits': 150, 'price': 625,
               'desc': '150 кредитов (выгоднее)'},
    'maxi': {'name': 'Макси', 'credits': 400, 'price': 1500,
             'desc': '400 кредитов (максимальная выгода)'},
}

CREDIT_COSTS = {
    'image_pro': 2,
    'edit_pro': 3,
    'video': {5: 25, 10: 50, 15: 100},
    'deepseek_session': 1,   # за 50 сообщений
}

# ================== 1. GIGACHAT ==================
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
        r = requests.post("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                          headers=headers, data=data, verify=False, timeout=30)
        if r.status_code == 200:
            return r.json().get("access_token")
    except:
        pass
    return None

def download_gigachat_file(token, file_id):
    url = f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content"
    headers = {"Authorization": f"Bearer {token}", "Accept": "image/jpeg"}
    try:
        r = requests.get(url, headers=headers, verify=False, timeout=30)
        if r.status_code == 200:
            return r.content
    except:
        pass
    return None

def generate_gigachat_image(prompt):
    token = get_gigachat_token()
    if not token:
        return None
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": "Ты — художник, создающий изображения."},
            {"role": "user", "content": prompt}
        ],
        "function_call": "auto"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code == 200:
            data = r.json()
            content = data['choices'][0]['message']['content']
            match = re.search(r'src="([a-f0-9\-]+)"', content)
            if match:
                return download_gigachat_file(token, match.group(1))
    except:
        pass
    return None

# ================== 2. DEEPSEEK V4 PRO ==================
def ask_deepseek(prompt):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek/deepseek-v4-pro",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except:
        return "⚠️ Ошибка соединения"
    return "❌ Ошибка API"

# ================== 3. ГЕНЕРАЦИЯ / РЕДАКТИРОВАНИЕ (Images API) ==================
def generate_image_pro(prompt, model_id):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_id,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }
    try:
        r = requests.post(OPENROUTER_IMAGE_URL, json=payload, headers=headers, timeout=120)
        if r.status_code == 200:
            data = r.json()
            if "data" in data and len(data["data"]) > 0:
                item = data["data"][0]
                if "b64_json" in item:
                    return base64.b64decode(item["b64_json"]), None
                elif "url" in item:
                    return requests.get(item["url"]).content, None
        else:
            logging.error(f"Image generation error {r.status_code}: {r.text}")
            return None, f"Ошибка API: {r.status_code} – {r.text[:200]}"
    except Exception as e:
        logging.error(f"Image generation exception: {e}")
        return None, str(e)
    return None, "Пустой ответ"

def edit_image_pro(prompt, image_base64, model_id):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_id,
        "prompt": prompt,
        "image": f"data:image/jpeg;base64,{image_base64}",
        "n": 1,
        "size": "1024x1024"
    }
    try:
        r = requests.post(OPENROUTER_IMAGE_URL, json=payload, headers=headers, timeout=120)
        if r.status_code == 200:
            data = r.json()
            if "data" in data and len(data["data"]) > 0:
                item = data["data"][0]
                if "b64_json" in item:
                    return base64.b64decode(item["b64_json"]), None
                elif "url" in item:
                    return requests.get(item["url"]).content, None
        else:
            logging.error(f"Image edit error {r.status_code}: {r.text}")
            return None, f"Ошибка API: {r.status_code} – {r.text[:200]}"
    except Exception as e:
        logging.error(f"Image edit exception: {e}")
        return None, str(e)
    return None, "Пустой ответ"

# ================== 4. ВИДЕО ==================
def compress_image_if_needed(b64_str, max_size=(640, 640), quality=80):
    try:
        img_data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_data))
        img.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except:
        return b64_str

def _is_valid_mp4(data):
    return data and len(data) > 500 and b'ftyp' in data[:100]

def _send_video_safe(chat_id, data, caption="✅ Ваше видео готово!"):
    try:
        video_file = io.BytesIO(data)
        video_file.name = "video.mp4"
        msg = bot.send_video(chat_id, video_file, caption=caption, supports_streaming=True, timeout=120)
        user_history[chat_id].append(msg.video.file_id)
        if len(user_history[chat_id]) > 3:
            user_history[chat_id].pop(0)
        return True
    except Exception as e:
        logging.error(f"send_video error: {e}")
        try:
            doc_file = io.BytesIO(data)
            doc_file.name = "video.mp4"
            bot.send_document(chat_id, doc_file, caption="✅ Видео (как файл)")
            return True
        except:
            return False

def poll_video_task(polling_url, headers, chat_id, status_message_id, model_display=""):
    start_time = time.time()
    for attempt in range(1, 91):
        time.sleep(10)
        try:
            resp = requests.get(polling_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                continue
            data = resp.json()
            status = data.get("status")
            progress = data.get("progress")
            elapsed = int((time.time() - start_time) / 60)
            text = f"🎬 Генерация видео ({model_display}): {int(progress)}% (прошло {elapsed} мин)" if progress else f"🎬 Генерация видео ({model_display}): этап {attempt} (прошло {elapsed} мин)"
            try:
                bot.edit_message_text(text, chat_id, status_message_id)
            except:
                pass
            if status == "completed":
                bot.edit_message_text("✅ Видео готово! Скачиваю...", chat_id, status_message_id)
                job_id = polling_url.split('/')[-1]
                unsigned_urls = data.get("unsigned_urls", [])
                if unsigned_urls:
                    vr = requests.get(unsigned_urls[0], timeout=60, allow_redirects=True)
                    if vr.status_code == 200 and _is_valid_mp4(vr.content):
                        _send_video_safe(chat_id, vr.content)
                        return
                content_url = f"https://openrouter.ai/api/v1/videos/{job_id}/content"
                vr = requests.get(content_url, headers=headers, timeout=60)
                if vr.status_code == 200 and _is_valid_mp4(vr.content):
                    _send_video_safe(chat_id, vr.content)
                    return
                bot.edit_message_text("❌ Видео повреждено.", chat_id, status_message_id)
                return
            elif status in ("failed", "cancelled", "expired"):
                bot.edit_message_text(f"❌ Ошибка: {status}", chat_id, status_message_id)
                return
        except:
            pass
    bot.edit_message_text("❌ Истекло время ожидания (15 мин).", chat_id, status_message_id)

def generate_video_async(chat_id, prompt, first_frame_b64=None, last_frame_b64=None):
    duration = user_video_params.get(chat_id, {}).get('duration', 5)
    cost = CREDIT_COSTS['video'].get(duration, 25)

    if chat_id != ADMIN_ID:
        if user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, f"❌ Недостаточно кредитов. Нужно {cost}, у вас {user_credits.get(chat_id, 0)}. Пополните баланс в магазине 💰.")
            return False
        user_credits[chat_id] -= cost
        user_credit_history[chat_id].append((time.time(), -cost, f"Видео {duration}с"))
        bot.send_message(chat_id, f"✅ Списано {cost} кредит(ов). Осталось: {user_credits[chat_id]}")

    params = user_video_params.get(chat_id, {})
    resolution = params.get('resolution', '480p')
    audio = params.get('audio', True)
    aspect = params.get('aspect_ratio', '16:9')
    model_id = user_video_model.get(chat_id, 'bytedance/seedance-2.0')
    model_names = {
        'bytedance/seedance-2.0': 'Seedance 2.0',
        'kwaivgi/kling-video-o1': 'Kling O1',
        'kwaivgi/kling-v3-pro': 'Kling Pro'
    }
    model_display = model_names.get(model_id, model_id)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    payload = {
        "model": model_id,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect
    }
    features = VIDEO_MODEL_FEATURES.get(model_id, {})
    if features.get('resolution'):
        payload["resolution"] = resolution
    if features.get('audio'):
        payload["audio"] = audio
    frame_images = []
    if first_frame_b64:
        frame_images.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(first_frame_b64)}"}, "frame_type": "first_frame"})
    if last_frame_b64:
        frame_images.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(last_frame_b64)}"}, "frame_type": "last_frame"})
    if frame_images:
        payload["frame_images"] = frame_images
    logging.info(f"Video payload: {json.dumps({k: v for k, v in payload.items() if k != 'frame_images'})}")
    try:
        resp = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
        if resp.status_code not in (200, 202):
            if chat_id != ADMIN_ID:
                user_credits[chat_id] = user_credits.get(chat_id, 0) + cost
                user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео"))
            bot.send_message(chat_id, f"❌ Ошибка {resp.status_code}. Кредиты возвращены.")
            return False
        data = resp.json()
        if "polling_url" in data:
            msg = bot.send_message(chat_id, f"🎬 Генерация видео ({model_display}): 0%")
            Thread(target=poll_video_task, args=(data["polling_url"], headers, chat_id, msg.message_id, model_display)).start()
            return True
        # ... (остальная обработка как раньше, с возвратом кредитов при ошибке)
    except Exception as e:
        logging.error(f"Video exception: {e}")
        if chat_id != ADMIN_ID:
            user_credits[chat_id] += cost
            user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео (ошибка)"))
        bot.send_message(chat_id, "❌ Ошибка связи. Кредиты возвращены.")
    return False

# ================== 5. КЛАВИАТУРЫ ==================
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🖼 Создать изображение"),
        KeyboardButton("🎨 Редактировать фото"),
        KeyboardButton("🎥 Создать видео"),
        KeyboardButton("💬 Спросить (чат)"),
        KeyboardButton("👤 Профиль"),
        KeyboardButton("💰 Магазин")
    )
    return markup

def back_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("🔙 Главное меню"))

# ... (остальные клавиатуры без изменений)

# ================== 6. ПРОФИЛЬ С ИСТОРИЕЙ ==================
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(message):
    chat_id = message.chat.id
    credits = user_credits.get(chat_id, 0)
    history = user_credit_history.get(chat_id, [])
    text = f"👤 *Ваш профиль*\n\n💰 Баланс: {credits} кредитов\n\n"
    if history:
        text += "📋 *Последние операции:*\n"
        for ts, delta, reason in history[-5:]:
            sign = "+" if delta > 0 else ""
            text += f"{sign}{delta} кр. – {reason}\n"
    else:
        text += "📋 *Операций пока нет.*"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Пополнить баланс", callback_data="goto_shop"))
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "goto_shop")
def goto_shop(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    shop(call.message)

# ================== 7. МАГАЗИН (без изменений) ==================
# ... (shop, initiate_payment, checkout, process_payment как раньше)

# ================== 8. АДМИН-ПАНЕЛЬ (с записью в историю) ==================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    total_credits = sum(user_credits.values())
    text = f"👑 Админ-панель\nПользователей: {len(user_credits)}\nКредитов всего: {total_credits}"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['addcredits'])
def add_credits(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        _, uid, amt = message.text.split()
        uid, amt = int(uid), int(amt)
        user_credits[uid] = user_credits.get(uid, 0) + amt
        user_credit_history[uid].append((time.time(), amt, "Начисление админом"))
        bot.send_message(message.chat.id, f"✅ Начислено {amt} кредитов пользователю {uid}")
        bot.send_message(uid, f"🎉 Администратор начислил вам {amt} кредитов. Баланс: {user_credits[uid]}")
    except:
        bot.send_message(message.chat.id, "Формат: /addcredits <user_id> <amount>")

@bot.message_handler(commands=['removecredits'])
def remove_credits(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        _, uid, amt = message.text.split()
        uid, amt = int(uid), int(amt)
        if user_credits.get(uid, 0) >= amt:
            user_credits[uid] -= amt
            user_credit_history[uid].append((time.time(), -amt, "Списание админом"))
            bot.send_message(message.chat.id, f"✅ Списано {amt} кредитов у {uid}")
            bot.send_message(uid, f"ℹ️ Администратор списал {amt} кредитов. Баланс: {user_credits[uid]}")
        else:
            bot.send_message(message.chat.id, "Недостаточно кредитов")
    except:
        bot.send_message(message.chat.id, "Формат: /removecredits <user_id> <amount>")

# ================== 9. СТАРТ И ОСНОВНЫЕ ОБРАБОТЧИКИ ==================
# ... (start, меню, колбэки выбора модели, параметров видео и т.д. – без изменений)

# ================== ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ==================
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_generate_prompt")
def handle_generate_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    model = user_generate_model.pop(chat_id, 'gigachat')
    user_state[chat_id] = None

    if model == 'gigachat':
        waiting = bot.send_message(chat_id, "🎨 Генерирую через GigaChat...")
        img_data = generate_gigachat_image(prompt)
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
        return

    cost = CREDIT_COSTS['image_pro']
    if chat_id != ADMIN_ID:
        if user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, f"❌ Недостаточно кредитов. Нужно {cost} кредита.")
            send_main_menu(chat_id)
            return

    model_id = 'bytedance-seed/seedream-4.5' if model == 'seedream' else 'x-ai/grok-imagine-image-quality'
    waiting = bot.send_message(chat_id, f"💎 Генерирую через {model}...")
    img_data, error_msg = generate_image_pro(prompt, model_id)

    if img_data:
        if chat_id != ADMIN_ID:
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Генерация {model}"))
            bot.send_message(chat_id, f"✅ Списано {cost} кредита. Осталось: {user_credits[chat_id]}")
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
        bot.send_message(chat_id, f"❌ Не удалось сгенерировать изображение.\n{error_msg}")
    send_main_menu(chat_id)

# ================== РЕДАКТИРОВАНИЕ ФОТО ==================
@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_photo")
def handle_awaiting_photo(message):
    # ... аналогично, с записью в историю
    pass

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_prompt")
def handle_awaiting_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    photo_base64 = user_pending_photo.pop(chat_id, None)
    if not photo_base64:
        bot.send_message(chat_id, "⚠️ Сначала загрузи фото.")
        send_main_menu(chat_id)
        return

    model = user_edit_model.pop(chat_id, 'seedream')
    face_mode = user_face_mode.pop(chat_id, 'full_edit')
    user_state[chat_id] = None

    if face_mode == 'keep_face':
        prompt = "Keep the face and facial features completely unchanged. Do not modify the face. Only apply the following changes: " + prompt

    cost = CREDIT_COSTS['edit_pro']
    if chat_id != ADMIN_ID:
        if user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, f"❌ Недостаточно кредитов. Нужно {cost} кредита.")
            send_main_menu(chat_id)
            return

    model_id = 'bytedance-seed/seedream-4.5' if model == 'seedream' else 'x-ai/grok-imagine-image-quality'
    waiting = bot.send_message(chat_id, f"🎨 Редактирую через {model}...")
    img_data, error_msg = edit_image_pro(prompt, photo_base64, model_id)

    if img_data:
        if chat_id != ADMIN_ID:
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Редактирование {model}"))
            bot.send_message(chat_id, f"✅ Списано {cost} кредита. Осталось: {user_credits[chat_id]}")
        caption = f"✅ Отредактировано ({model})"
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
    elif error_msg:
        bot.send_message(chat_id, f"❌ Не удалось отредактировать изображение.\n{error_msg}")
    else:
        bot.send_message(chat_id, "❌ Не удалось отредактировать изображение. Кредиты не списаны.")
    send_main_menu(chat_id)

# Финальная генерация видео (без изменений, но с историей)
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_prompt")
def handle_video_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    user_state[chat_id] = None
    # ... вызов generate_video_async
    pass

# ================== ЧАТ С DEEPSEEK (исправлено) ==================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text_chat(message):
    if message.text.startswith('/'):
        return
    state = user_state.get(message.chat.id)
    if state in ["awaiting_prompt", "awaiting_generate_prompt", "awaiting_photo", "awaiting_video_prompt", "awaiting_video_image_first", "awaiting_video_image_last", "select_video_model"]:
        return

    chat_id = message.chat.id
    # Админ без списаний
    if chat_id == ADMIN_ID:
        reply = ask_deepseek(message.text)
        bot.send_message(chat_id, reply, reply_markup=back_keyboard())
        return

    user_message_count[chat_id] += 1
    if user_message_count[chat_id] % 50 == 0:
        cost = CREDIT_COSTS['deepseek_session']
        if user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, "❌ Недостаточно кредитов для продолжения чата. Пополните баланс в магазине 💰.")
            return
        user_credits[chat_id] -= cost
        user_credit_history[chat_id].append((time.time(), -cost, "Пакет из 50 сообщений DeepSeek"))
        bot.send_message(chat_id, f"💬 Использовано 50 сообщений. Списано {cost} кредит. Осталось: {user_credits[chat_id]} кредитов.")

    reply = ask_deepseek(message.text)
    bot.send_message(chat_id, reply, reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: True)
def handle_other(message):
    bot.send_message(message.chat.id, "Пожалуйста, используй кнопки меню.")

# ================== 10. ЗАПУСК ==================
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

def run_bot():
    logging.info("✅ Бот запущен")
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(10)

@app.route('/')
def index():
    return "Bot is running"

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
