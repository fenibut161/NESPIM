import os
import telebot
import requests
import time
import base64
import urllib3
import json
import logging
from html import escape
from flask import Flask, request, send_from_directory
from threading import Thread, Lock
from telebot.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton,
                           LabeledPrice)
from PIL import Image
import io
from collections import defaultdict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- ENV ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GIST_ID = os.getenv("GIST_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"

ADMIN_ID = 534008787

DATA_FILE = "bot_data.json"
data_lock = Lock()

# --- DATA ---
user_credits = defaultdict(int)
user_credit_history = defaultdict(list)
user_message_count = defaultdict(int)
user_last_activity = defaultdict(float)

user_state = {}
user_edit_model = {}
user_face_mode = {}
user_generate_model = {}
user_pending_photo = {}
user_video_mode = {}
user_video_frames = {}
user_video_params = {}
user_video_model = {}
user_video_history = defaultdict(list)

# --- MODELS ---
FLUX_MODEL = "black-forest-labs/flux.2-pro"
SEEDREAM_MODEL = "bytedance-seed/seedream-4.5"

# --- GIST SYNC ---
def load_data():
    global user_credits, user_credit_history, user_message_count, user_last_activity
    data = None
    gist_loaded = False

    if GIST_ID and GITHUB_TOKEN:
        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                content = r.json()["files"]["bot_data.json"]["content"]
                data = json.loads(content)
                if data and any([data.get("credits"), data.get("history"), data.get("messages")]):
                    gist_loaded = True
                    print("Loaded data from Gist (non-empty)")
                else:
                    print("Gist data is empty, fallback to local")
                    data = None
            else:
                print(f"Gist load failed: {r.status_code}")
        except Exception as e:
            print(f"Gist load exception: {e}")

    if data is None:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            print("Loaded from local file")
        except FileNotFoundError:
            print("No local file, starting fresh")
            data = {}
        except Exception as e:
            print(f"Local file error: {e}")
            data = {}

    user_credits = defaultdict(int, {int(k): v for k, v in data.get("credits", {}).items()})
    user_credit_history = defaultdict(list, {int(k): v for k, v in data.get("history", {}).items()})
    user_message_count = defaultdict(int, {int(k): v for k, v in data.get("messages", {}).items()})
    user_last_activity = defaultdict(float, {int(k): v for k, v in data.get("last_activity", {}).items()})

def save_data():
    with data_lock:
        data = {
            "credits": dict(user_credits),
            "history": dict(user_credit_history),
            "messages": dict(user_message_count),
            "last_activity": dict(user_last_activity),
        }
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Local save error: {e}")
        if GIST_ID and GITHUB_TOKEN:
            try:
                url = f"https://api.github.com/gists/{GIST_ID}"
                headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
                payload = {"files": {"bot_data.json": {"content": json.dumps(data, ensure_ascii=False, indent=2)}}}
                r = requests.patch(url, json=payload, headers=headers, timeout=30)
                if r.status_code == 200:
                    print("Saved to Gist")
                else:
                    print(f"Gist save error {r.status_code}")
            except Exception as e:
                print(f"Gist save exception: {e}")

load_data()

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

os.makedirs("static", exist_ok=True)

VIDEO_MODEL_FEATURES = {
    "bytedance/seedance-2.0": {"audio": True, "resolution": True},
    "kwaivgi/kling-video-o1": {"audio": True, "resolution": True},
    "kwaivgi/kling-v3-pro": {"audio": True, "resolution": True},
}

PACKAGES = {
    "start": {"name": "Старт", "credits": 50, "price_stars": 250, "price_rub": 400, "desc": "50 ♦ на любые операции"},
    "optima": {"name": "Оптима", "credits": 150, "price_stars": 625, "price_rub": 1000, "desc": "150 ♦ (выгоднее)"},
    "maxi": {"name": "Макси", "credits": 400, "price_stars": 1500, "price_rub": 2400, "desc": "400 ♦ (максимальная выгода)"},
}

CREDIT_COSTS = {
    "image_pro": 2,
    "edit_pro": 3,
    "video": {5: 25, 10: 50, 15: 100},
    "deepseek_session": 1,
}

# ================== DEEPSEEK ==================
def ask_deepseek(prompt):
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek/deepseek-v4-pro", "messages": [{"role": "user", "content": prompt}]}
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        print(f"DeepSeek error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"DeepSeek exception: {e}")
    return "⚠️ Ошибка соединения"

# ================== IMAGE HELPERS ==================
def _safe_resample():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS

def _parse_image_response(resp):
    if resp.status_code != 200:
        return None, f"Ошибка API: {resp.status_code} {resp.text[:300]}"
    try:
        data = resp.json()
        msg = data["choices"][0]["message"]
        if "images" in msg and msg["images"]:
            img_url = msg["images"][0]["image_url"]["url"]
        elif msg.get("content", "").startswith("data:image/"):
            img_url = msg["content"]
        else:
            return None, msg.get("content", "Нет изображения в ответе")
        if img_url.startswith("data:image/"):
            return base64.b64decode(img_url.split(",", 1)[1]), None
        return requests.get(img_url, timeout=30).content, None
    except Exception as e:
        return None, str(e)

def _build_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot",
    }

# ================== FLUX ==================
def generate_image_flux(prompt):
    payload = {"model": FLUX_MODEL, "messages": [{"role": "user", "content": prompt}], "modalities": ["image"]}
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)[0]
    except Exception as e:
        print(f"Flux generation error: {e}")
    return None

def edit_image_flux(prompt, image_base64):
    payload = {
        "model": FLUX_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                ],
            }
        ],
        "modalities": ["image"],
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)
    except Exception as e:
        print(f"Flux edit error: {e}")
    return None, str(e)

# ================== SEEDREAM ==================
def generate_image_seedream(prompt):
    payload = {"model": SEEDREAM_MODEL, "messages": [{"role": "user", "content": prompt}], "modalities": ["image"]}
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)[0]
    except Exception as e:
        print(f"Seedream generation error: {e}")
    return None

def edit_image_seedream(prompt, image_base64):
    payload = {
        "model": SEEDREAM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                ],
            }
        ],
        "modalities": ["image"],
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)
    except Exception as e:
        print(f"Seedream edit error: {e}")
    return None, str(e)

# ================== VIDEO ==================
def compress_image_if_needed(b64_str, max_size=(640, 640), quality=80):
    try:
        img_data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_data))
        img.thumbnail(max_size, _safe_resample())
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"Compress error: {e}")
        return b64_str

def _is_valid_mp4(data):
    return data and len(data) > 500 and b"ftyp" in data[:100]

def _send_video_safe(chat_id, data, caption="✅ Ваше видео готово!"):
    try:
        video_file = io.BytesIO(data)
        video_file.name = "video.mp4"
        msg = bot.send_video(chat_id, video_file, caption=caption, supports_streaming=True, timeout=120)
        user_video_history[chat_id].append(msg.video.file_id)
        if len(user_video_history[chat_id]) > 3:
            user_video_history[chat_id].pop(0)
        return True
    except Exception as e:
        print(f"send_video error: {e}")
        try:
            doc_file = io.BytesIO(data)
            doc_file.name = "video.mp4"
            bot.send_document(chat_id, doc_file, caption="✅ Видео (как файл)")
            return True
        except Exception as e2:
            print(f"send_document error: {e2}")
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
            if progress:
                text = f"🎬 Генерация видео ({model_display}): {int(progress)}% (прошло {elapsed} мин)"
            else:
                text = f"🎬 Генерация видео ({model_display}): этап {attempt} (прошло {elapsed} мин)"
            try:
                bot.edit_message_text(text, chat_id, status_message_id)
            except Exception:
                pass
            if status == "completed":
                bot.edit_message_text("✅ Видео готово! Скачиваю...", chat_id, status_message_id)
                job_id = polling_url.split("/")[-1]
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
        except Exception:
            pass
    bot.edit_message_text("❌ Истекло время ожидания (15 мин).", chat_id, status_message_id)

def generate_video_async(chat_id, prompt, first_frame_b64=None, last_frame_b64=None):
    duration = user_video_params.get(chat_id, {}).get("duration", 5)
    cost = CREDIT_COSTS["video"].get(duration, 25)
    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Недостаточно ♦. Нужно {cost}, у вас {user_credits.get(chat_id, 0)}. Пополните баланс в магазине 💰.")
                return False
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Видео {duration}с"))
            save_data()
            bot.send_message(chat_id, f"✅ Списано {cost} ♦. Осталось: {user_credits[chat_id]}")
    params = user_video_params.get(chat_id, {})
    resolution = params.get("resolution", "480p")
    audio = params.get("audio", True)
    aspect = params.get("aspect_ratio", "16:9")
    model_id = user_video_model.get(chat_id, "bytedance/seedance-2.0")
    model_names = {
        "bytedance/seedance-2.0": "Seedance 2.0",
        "kwaivgi/kling-video-o1": "Kling O1",
        "kwaivgi/kling-v3-pro": "Kling Pro",
    }
    model_display = model_names.get(model_id, model_id)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot",
    }
    payload = {"model": model_id, "prompt": prompt, "duration": duration, "aspect_ratio": aspect}
    features = VIDEO_MODEL_FEATURES.get(model_id, {})
    if features.get("resolution"):
        payload["resolution"] = resolution
    if features.get("audio"):
        payload["audio"] = audio
    frame_images = []
    if first_frame_b64:
        frame_images.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(first_frame_b64)}"}, "frame_type": "first_frame"})
    if last_frame_b64:
        frame_images.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(last_frame_b64)}"}, "frame_type": "last_frame"})
    if frame_images:
        payload["frame_images"] = frame_images
    print(f"Video payload: {json.dumps({k: v for k, v in payload.items() if k != 'frame_images'})}")
    try:
        resp = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
        if resp.status_code not in (200, 202):
            with data_lock:
                if chat_id != ADMIN_ID:
                    user_credits[chat_id] = user_credits.get(chat_id, 0) + cost
                    user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео"))
                    save_data()
            bot.send_message(chat_id, f"❌ Ошибка {resp.status_code}. ♦ возвращены.")
            return False
        data = resp.json()
        if "polling_url" in data:
            msg = bot.send_message(chat_id, f"🎬 Генерация видео ({model_display}): 0%")
            Thread(target=poll_video_task, args=(data["polling_url"], headers, chat_id, msg.message_id, model_display)).start()
            return True
        if "unsigned_urls" in data and data["unsigned_urls"]:
            vr = requests.get(data["unsigned_urls"][0], timeout=60, allow_redirects=True)
            if vr.status_code == 200 and _is_valid_mp4(vr.content):
                _send_video_safe(chat_id, vr.content)
                return True
        if "b64_json" in data:
            raw = base64.b64decode(data["b64_json"])
            if _is_valid_mp4(raw):
                _send_video_safe(chat_id, raw)
                return True
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео"))
                save_data()
        bot.send_message(chat_id, "❌ Пустой ответ. ♦ возвращены.")
    except Exception as e:
        print(f"Video exception: {e}")
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео (ошибка)"))
                save_data()
        bot.send_message(chat_id, "❌ Ошибка связи. ♦ возвращены.")
    return False

# ================== KEYBOARDS ==================
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🖼 Создать изображение"),
        KeyboardButton("🎨 Редактировать фото"),
        KeyboardButton("🎥 Создать видео"),
        KeyboardButton("💬 Спросить (чат)"),
        KeyboardButton("👤 Профиль"),
        KeyboardButton("💰 Магазин"),
    )
    return markup

def back_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("🔙 Главное меню"))

def video_model_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌱 Seedance 2.0", callback_data="vmodel_seedance-2.0"),
        InlineKeyboardButton("🎬 Kling O1", callback_data="vmodel_kling-o1"),
        InlineKeyboardButton("🎥 Kling Pro", callback_data="vmodel_kling-pro"),
    )
    return markup

def video_params_keyboard(chat_id):
    params = user_video_params.get(chat_id, {})
    duration = params.get("duration", 5)
    resolution = params.get("resolution", "480p")
    audio = params.get("audio", True)
    aspect = params.get("aspect_ratio", "16:9")
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton(f"{'✅' if duration == 5 else '⬜'} 5 сек", callback_data="vid_dur_5"),
        InlineKeyboardButton(f"{'✅' if duration == 10 else '⬜'} 10 сек", callback_data="vid_dur_10"),
        InlineKeyboardButton(f"{'✅' if duration == 15 else '⬜'} 15 сек", callback_data="vid_dur_15"),
    )
    markup.add(
        InlineKeyboardButton(f"{'✅' if resolution == '480p' else '⬜'} 480p", callback_data="vid_res_480p"),
        InlineKeyboardButton(f"{'✅' if resolution == '720p' else '⬜'} 720p", callback_data="vid_res_720p"),
        InlineKeyboardButton(f"{'✅' if resolution == '1080p' else '⬜'} 1080p", callback_data="vid_res_1080p"),
    )
    markup.add(
        InlineKeyboardButton(f"{'✅' if aspect == '16:9' else '⬜'} 16:9", callback_data="vid_aspect_16_9"),
        InlineKeyboardButton(f"{'✅' if aspect == '9:16' else '⬜'} 9:16", callback_data="vid_aspect_9_16"),
        InlineKeyboardButton(f"{'✅' if aspect == '1:1' else '⬜'} 1:1", callback_data="vid_aspect_1_1"),
    )
    markup.add(
        InlineKeyboardButton(f"{'✅' if audio else '⬜'} Со звуком", callback_data="vid_audio_true"),
        InlineKeyboardButton(f"{'✅' if not audio else '⬜'} Без звука", callback_data="vid_audio_false"),
    )
    markup.add(InlineKeyboardButton("✅ Готово, продолжить", callback_data="vid_params_done"))
    return markup

def start_video_param_selection(chat_id):
    user_video_params[chat_id] = user_video_params.get(chat_id, {})
    bot.send_message(chat_id, "Настройте параметры видео, затем нажмите «Готово»:", reply_markup=video_params_keyboard(chat_id))

# ================== PROFILE ==================
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    credits = user_credits.get(chat_id, 0)
    history = user_credit_history.get(chat_id, [])
    text = f"👤 <b>Ваш профиль</b>\n\n💰 Баланс: {credits} ♦\n\n"
    if history:
        text += "📋 <b>Последние операции:</b>\n"
        for ts, delta, reason in history[-5:]:
            sign = "+" if delta > 0 else ""
            text += f"{sign}{delta} ♦ – {escape(reason)}\n"
    else:
        text += "📋 <b>Операций пока нет.</b>"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Пополнить баланс", callback_data="goto_shop"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "goto_shop")
def goto_shop(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    shop(call.message)

# ================== SHOP ==================
@bot.message_handler(func=lambda m: m.text == "💰 Магазин")
def shop(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    text = (
        "🛒 <b>Магазин ♦</b>\n"
        "1 ♦ позволяет:\n"
        "• Генерация (Flux/Seedream) — 2 ♦\n"
        "• Редактирование (Flux/Seedream) — 3 ♦\n"
        "• Видео 5 сек — 25 ♦, 10 сек — 50 ♦, 15 сек — 100 ♦\n"
        "• Чат с ИИ — 1 ♦ за 50 сообщений\n\n"
        "Выберите пакет:"
    )
    for key, pkg in PACKAGES.items():
        text += f"\n<b>{escape(pkg['name'])}</b>: {pkg['credits']} ♦ — {pkg['price_stars']} ⭐️ / {pkg['price_rub']} ₽"
    bot.send_message(chat_id, text, parse_mode="HTML")
    markup = InlineKeyboardMarkup(row_width=2)
    for key, pkg in PACKAGES.items():
        markup.add(
            InlineKeyboardButton(f"{pkg['name']} ⭐️ {pkg['price_stars']}", callback_data=f"buy_stars_{key}"),
            InlineKeyboardButton(f"{pkg['name']} 💳 {pkg['price_rub']}₽", callback_data=f"buy_card_{key}"),
        )
    bot.send_message(chat_id, "Оплата Stars (Telegram) или перевод на карту:", reply_markup=markup)

# --- STARS PAYMENT ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_stars_"))
def initiate_stars_payment(call):
    chat_id = call.message.chat.id
    pkg_key = call.data[10:]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        bot.answer_callback_query(call.id, "Ошибка пакета")
        return
    try:
        bot.send_invoice(
            chat_id=chat_id,
            title=f"Пакет «{pkg['name']}»",
            description=pkg["desc"],
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="XTR", amount=pkg["price_stars"])],
            start_parameter="shop",
            invoice_payload=f"package_{pkg_key}",
        )
        bot.answer_callback_query(call.id, "Счёт отправлен. Оплатите через Telegram Stars.")
    except Exception as e:
        print(f"Invoice error: {e}")
        bot.send_message(chat_id, f"❌ Ошибка при создании счёта: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(query):
    bot.answer_pre_checkout_query(query.id, ok=True)

@bot.message_handler(content_types=["successful_payment"])
def process_payment(message):
    chat_id = message.chat.id
    pkg_key = message.successful_payment.invoice_payload.split("_")[1]
    pkg = PACKAGES.get(pkg_key)
    if pkg:
        with data_lock:
            user_credits[chat_id] = user_credits.get(chat_id, 0) + pkg["credits"]
            user_credit_history[chat_id].append((time.time(), pkg["credits"], f"Покупка пакета {pkg['name']} (Stars)"))
            save_data()
        bot.send_message(chat_id, f"✅ Оплата прошла! Начислено {pkg['credits']} ♦.\nБаланс: {user_credits[chat_id]} ♦")

# --- CARD PAYMENT (manual) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_card_"))
def handle_card_payment(call):
    chat_id = call.message.chat.id
    pkg_key = call.data[9:]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        bot.answer_callback_query(call.id, "Ошибка пакета")
        return
    user = call.from_user
    username = f"@{user.username}" if user.username else "без username"
    bot.send_message(
        chat_id,
        f"💳 <b>Оплата картой — пакет «{pkg['name']}»</b>\n\n"
        f"Сумма: <b>{pkg['price_rub']} ₽</b>\n"
        f"Вы получите: <b>{pkg['credits']} ♦</b>\n\n"
        f"Переведите сумму на Т-Банк / СБЕР по номеру:\n"
        f"<code>+79192329005</code>\n\n"
        f"❗️ <b>Укажите в комментарии к переводу ваш Telegram ID:</b>\n"
        f"<code>{chat_id}</code>\n\n"
        f"После перевода ♦ начислятся вручную в течение 15 минут.",
        parse_mode="HTML",
    )
    bot.answer_callback_query(call.id, "Реквизиты отправлены")
    try:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"✅ Начислить {pkg['credits']}♦", callback_data=f"admin_grant_{chat_id}_{pkg_key}"))
        bot.send_message(
            ADMIN_ID,
            f"💳 <b>Запрос на оплату картой</b>\n\n"
            f"Пользователь: {username}\n"
            f"ID: <code>{chat_id}</code>\n"
            f"Пакет: <b>{pkg['name']}</b>\n"
            f"Сумма: {pkg['price_rub']} ₽\n"
            f"♦: {pkg['credits']}",
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception as e:
        print(f"Admin notify error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_grant_"))
def admin_grant_credits(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Нет доступа")
        return
    parts = call.data.split("_")
    if len(parts) < 4:
        bot.answer_callback_query(call.id, "Ошибка данных")
        return
    target_id = int(parts[2])
    pkg_key = parts[3]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        bot.answer_callback_query(call.id, "Ошибка пакета")
        return
    with data_lock:
        user_credits[target_id] = user_credits.get(target_id, 0) + pkg["credits"]
        user_credit_history[target_id].append((time.time(), pkg["credits"], f"Покупка пакета {pkg['name']} (карта)"))
        save_data()
    bot.answer_callback_query(call.id, f"Начислено {pkg['credits']} ♦")
    bot.edit_message_text(
        f"✅ <b>Начислено</b>\nПользователю {target_id}: +{pkg['credits']} ♦",
        call.message.chat.id,
        call.message.message_id,
    )
    try:
        bot.send_message(target_id, f"🎉 Администратор начислил вам {pkg['credits']} ♦ (пакет «{pkg['name']}»).\nВаш баланс: {user_credits[target_id]} ♦")
    except Exception as e:
        print(f"Не удалось уведомить {target_id}: {e}")

@bot.message_handler(commands=["paysupport"])
def pay_support(message):
    bot.send_message(message.chat.id, "Возврат средств осуществляется в течение 24 часов. Для запроса возврата свяжитесь с @Jastick_bot.")

# ================== ADMIN ==================
@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    with data_lock:
        total_credits = sum(user_credits.values())
    text = f"👑 Админ-панель\nПользователей: {len(user_credits)}\n♦ всего: {total_credits}\n\nКоманды:\n/addcredits <id> <amount>\n/removecredits <id> <amount>"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=["addcredits"])
def add_credits(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        _, uid, amt = message.text.split()
        uid, amt = int(uid), int(amt)
        with data_lock:
            user_credits[uid] = user_credits.get(uid, 0) + amt
            user_credit_history[uid].append((time.time(), amt, "Начисление админом"))
            save_data()
        bot.send_message(message.chat.id, f"🎉 Готово! {amt} ♦ зачислены пользователю {uid}. Текущий баланс: {user_credits[uid]}.")
        try:
            bot.send_message(uid, f"🎉 Администратор начислил вам {amt} ♦. Ваш баланс: {user_credits[uid]}")
        except Exception as e:
            print(f"Не удалось уведомить {uid}: {e}")
    except Exception:
        bot.send_message(message.chat.id, "Формат: /addcredits <user_id> <amount>")

@bot.message_handler(commands=["removecredits"])
def remove_credits(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        _, uid, amt = message.text.split()
        uid, amt = int(uid), int(amt)
        with data_lock:
            if user_credits.get(uid, 0) >= amt:
                user_credits[uid] -= amt
                user_credit_history[uid].append((time.time(), -amt, "Списание админом"))
                save_data()
                bot.send_message(message.chat.id, f"✅ Списано {amt} ♦ у {uid}")
                try:
                    bot.send_message(uid, f"ℹ️ Администратор списал {amt} ♦. Баланс: {user_credits[uid]}")
                except Exception as e:
                    print(f"Не удалось уведомить {uid}: {e}")
            else:
                bot.send_message(message.chat.id, "Недостаточно ♦")
    except Exception as e:
        print(f"Remove credits error: {e}")
        bot.send_message(message.chat.id, "Формат: /removecredits <user_id> <amount>")

# ================== START & MENU ==================
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    send_main_menu(chat_id, "👋 Привет! Я умею генерировать изображения (Flux/Seedream), редактировать фото и создавать видео. Выбери действие в меню ниже.")

def send_main_menu(chat_id, text="Главное меню:"):
    bot.send_message(chat_id, text, reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.text == "🖼 Создать изображение")
def menu_generate_image(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_model_generate"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌊 Flux (2♦)", callback_data="gen_flux"),
        InlineKeyboardButton("🎨 Seedream (2♦)", callback_data="gen_seedream"),
    )
    bot.send_message(message.chat.id, "Выбери модель для генерации:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎨 Редактировать фото")
def menu_edit_photo(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_model_edit"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌊 Flux (3♦)", callback_data="edit_flux"),
        InlineKeyboardButton("🎨 Seedream (3♦)", callback_data="edit_seedream"),
    )
    bot.send_message(message.chat.id, "Выбери модель редактирования:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
def menu_video(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_video_mode"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📝 Текст в видео", callback_data="vid_text"),
        InlineKeyboardButton("🖼 Картинка в видео", callback_data="vid_image"),
    )
    bot.send_message(message.chat.id, "Выберите режим генерации видео:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💬 Спросить (чат)")
def menu_chat(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    bot.send_message(message.chat.id, "Задай любой вопрос (DeepSeek V4 Pro). Каждые 50 сообщений списывается 1 ♦.", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def menu_profile(message):
    user_last_activity[message.chat.id] = time.time()
    profile(message)

@bot.message_handler(func=lambda m: m.text == "💰 Магазин")
def menu_shop(message):
    user_last_activity[message.chat.id] = time.time()
    shop(message)

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_to_main(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state.pop(chat_id, None)
    user_edit_model.pop(chat_id, None)
    user_face_mode.pop(chat_id, None)
    user_generate_model.pop(chat_id, None)
    user_pending_photo.pop(chat_id, None)
    user_video_frames.pop(chat_id, None)
    user_video_params.pop(chat_id, None)
    user_video_model.pop(chat_id, None)
    user_video_mode.pop(chat_id, None)
    send_main_menu(chat_id)

# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("vmodel_"))
def set_video_model(call):
    chat_id = call.message.chat.id
    model_key = call.data.split("_", 1)[1]
    model_map = {
        "seedance-2.0": "bytedance/seedance-2.0",
        "kling-o1": "kwaivgi/kling-video-o1",
        "kling-pro": "kwaivgi/kling-v3-pro",
    }
    if model_key in model_map:
        user_video_model[chat_id] = model_map[model_key]
        bot.answer_callback_query(call.id, f"Выбрана модель: {model_key}")
        bot.delete_message(chat_id, call.message.message_id)
        start_video_param_selection(chat_id)
    else:
        bot.answer_callback_query(call.id, "Ошибка выбора модели")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_dur_"))
def set_video_duration(call):
    chat_id = call.message.chat.id
    duration = int(call.data.split("_")[-1])
    user_video_params[chat_id]["duration"] = duration
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Длительность: {duration} сек")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_res_"))
def set_video_resolution(call):
    chat_id = call.message.chat.id
    resolution = call.data.split("_")[-1]
    user_video_params[chat_id]["resolution"] = resolution
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Разрешение: {resolution}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_aspect_"))
def set_video_aspect(call):
    chat_id = call.message.chat.id
    aspect = call.data.split("_", 2)[2].replace("_", ":")
    user_video_params[chat_id]["aspect_ratio"] = aspect
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Формат: {aspect}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_audio_"))
def set_video_audio(call):
    chat_id = call.message.chat.id
    audio = call.data.split("_")[-1] == "true"
    user_video_params[chat_id]["audio"] = audio
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Звук: {'включён' if audio else 'выключен'}")

@bot.callback_query_handler(func=lambda call: call.data == "vid_params_done")
def video_params_done(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, call.message.message_id)
    params = user_video_params.get(chat_id, {})
    params.setdefault("duration", 5)
    params.setdefault("resolution", "480p")
    params.setdefault("audio", True)
    params.setdefault("aspect_ratio", "16:9")
    user_video_params[chat_id] = params
    user_state[chat_id] = "awaiting_video_prompt"
    bot.send_message(chat_id, "✏️ Теперь введите описание (промпт) для видео:", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data in ("vid_text", "vid_image"))
def select_video_mode(call):
    chat_id = call.message.chat.id
    data = call.data
    if data == "vid_text":
        user_video_mode[chat_id] = "text"
        user_video_frames[chat_id] = {"first": None, "last": None}
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "🎥 Выберите видеомодель:", reply_markup=video_model_keyboard())
    elif data == "vid_image":
        user_video_mode[chat_id] = "image_one"
        user_video_frames[chat_id] = {"first": None, "last": None}
        user_state[chat_id] = "awaiting_video_image_first"
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "📸 Загрузи ПЕРВЫЙ кадр (начальное изображение):", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gen_"))
def select_generate_model(call):
    chat_id = call.message.chat.id
    data = call.data
    if data == "gen_flux":
        user_generate_model[chat_id] = "flux"
    elif data == "gen_seedream":
        user_generate_model[chat_id] = "seedream"
    bot.answer_callback_query(call.id, f"Выбрана модель: {data}")
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = "awaiting_generate_prompt"
    bot.send_message(chat_id, "Введи описание изображения:", reply_markup=back_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_"))
def select_edit_model(call):
    chat_id = call.message.chat.id
    data = call.data
    if data == "edit_flux":
        user_edit_model[chat_id] = "flux"
    elif data == "edit_seedream":
        user_edit_model[chat_id] = "seedream"
    bot.answer_callback_query(call.id, f"Выбрана модель: {data}")
    bot.delete_message(chat_id, call.message.message_id)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔒 Сохранить лицо", callback_data="face_keep"),
        InlineKeyboardButton("🎨 Полное редактирование", callback_data="face_full"),
    )
    bot.send_message(chat_id, "Как обрабатывать лицо на фото?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("face_"))
def select_face_mode(call):
    chat_id = call.message.chat.id
    if call.data == "face_keep":
        user_face_mode[chat_id] = "keep_face"
    else:
        user_face_mode[chat_id] = "full_edit"
    bot.answer_callback_query(call.id, "Режим сохранён")
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = "awaiting_photo"
    bot.send_message(chat_id, "📸 Загрузи фото, которое нужно отредактировать.", reply_markup=back_keyboard())

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_first")
def handle_video_first_frame(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode("utf-8")
    user_video_frames[chat_id]["first"] = b64
    user_state[chat_id] = "awaiting_video_last_choice"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Да, загрузить второй кадр", callback_data="last_yes"),
        InlineKeyboardButton("Нет, только первый", callback_data="last_no"),
    )
    bot.send_message(chat_id, "Хотите задать ПОСЛЕДНИЙ кадр (конечное изображение)?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("last_"))
def choose_last_frame(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, call.message.message_id)
    if call.data == "last_yes":
        user_state[chat_id] = "awaiting_video_image_last"
        bot.send_message(chat_id, "📸 Загрузи ПОСЛЕДНИЙ кадр:", reply_markup=back_keyboard())
    else:
        user_state[chat_id] = None
        bot.send_message(chat_id, "🎥 Выберите видеомодель:", reply_markup=video_model_keyboard())
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_last")
def handle_video_last_frame(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode("utf-8")
    user_video_frames[chat_id]["last"] = b64
    user_state[chat_id] = None
    bot.send_message(chat_id, "🎥 Выберите видеомодель:", reply_markup=video_model_keyboard())

# ================== IMAGE GENERATION ==================
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_generate_prompt")
def handle_generate_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    prompt = message.text
    model = user_generate_model.pop(chat_id, "flux")
    user_state[chat_id] = None
    cost = CREDIT_COSTS["image_pro"]
    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Недостаточно ♦. Нужно {cost} ♦.")
                send_main_menu(chat_id)
                return
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Генерация {model}"))
            save_data()
            bot.send_message(chat_id, f"✅ Списано {cost} ♦. Осталось: {user_credits[chat_id]}")
    bot.send_message(chat_id, f"🎨 Генерирую через {model}...")
    if model == "flux":
        img_data = generate_image_flux(prompt)
    else:
        img_data = generate_image_seedream(prompt)
    if img_data:
        try:
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 800), _safe_resample())
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            bot.send_photo(chat_id, buf.getvalue(), caption="✅ Готово!")
        except Exception as e:
            print(f"Image send error: {e}")
            bot.send_document(chat_id, img_data, caption="✅ Готово (файл)")
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, f"Возврат за генерацию {model}"))
                save_data()
                bot.send_message(chat_id, f"❌ Ошибка генерации. {cost} ♦ возвращены.")
        bot.send_message(chat_id, "❌ Не удалось сгенерировать изображение.")
    send_main_menu(chat_id)

# ================== IMAGE EDITING ==================
@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_photo")
def handle_awaiting_photo(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "awaiting_prompt"
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    user_pending_photo[chat_id] = base64.b64encode(downloaded).decode("utf-8")
    bot.send_message(chat_id, "✏️ Теперь напиши, что изменить (промт):", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_prompt")
def handle_awaiting_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    prompt = message.text
    photo_base64 = user_pending_photo.pop(chat_id, None)
    if not photo_base64:
        bot.send_message(chat_id, "⚠️ Сначала загрузи фото.")
        send_main_menu(chat_id)
        return
    model = user_edit_model.pop(chat_id, "flux")
    face_mode = user_face_mode.pop(chat_id, "full_edit")
    user_state[chat_id] = None
    if face_mode == "keep_face":
        prompt = "Keep the face and facial features completely unchanged. Do not modify the face. Only apply the following changes: " + prompt
    cost = CREDIT_COSTS["edit_pro"]
    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Недостаточно ♦. Нужно {cost} ♦.")
                send_main_menu(chat_id)
                return
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Редактирование {model}"))
            save_data()
            bot.send_message(chat_id, f"✅ Списано {cost} ♦. Осталось: {user_credits[chat_id]}")
    bot.send_message(chat_id, f"🎨 Редактирую через {model}...")
    if model == "flux":
        img_data, error_msg = edit_image_flux(prompt, photo_base64)
    else:
        img_data, error_msg = edit_image_seedream(prompt, photo_base64)
    if img_data:
        caption = f"✅ Отредактировано ({model})"
        if face_mode == "keep_face":
            caption += " с сохранением лица"
        try:
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((800, 800), _safe_resample())
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            bot.send_photo(chat_id, buf.getvalue(), caption=caption)
        except Exception as e:
            print(f"Edit image send error: {e}")
            bot.send_document(chat_id, img_data, caption=caption)
    elif error_msg:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, f"Возврат за редактирование {model}"))
                save_data()
                bot.send_message(chat_id, f"❌ Ошибка редактирования. {cost} ♦ возвращены.")
        bot.send_message(chat_id, f"❌ Не удалось отредактировать изображение.\n{error_msg}")
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, "Возврат за редактирование (пустой ответ)"))
                save_data()
                bot.send_message(chat_id, "❌ Не удалось отредактировать изображение. ♦ возвращены.")
    send_main_menu(chat_id)

# ================== VIDEO PROMPT ==================
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_prompt")
def handle_video_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    prompt = message.text
    user_state[chat_id] = None
    print(f"=== VIDEO START {chat_id} ===")
    print(f"Prompt: {prompt}")
    first_frame = user_video_frames.get(chat_id, {}).get("first")
    last_frame = user_video_frames.get(chat_id, {}).get("last")
    user_video_frames.pop(chat_id, None)
    Thread(target=generate_video_async, args=(chat_id, prompt, first_frame, last_frame), daemon=True).start()

# ================== CHAT ==================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text_chat(message):
    if message.text.startswith("/"):
        return
    if message.text in [
        "🖼 Создать изображение", "🎨 Редактировать фото", "🎥 Создать видео",
        "💬 Спросить (чат)", "👤 Профиль", "💰 Магазин", "🔙 Главное меню",
    ]:
        send_main_menu(message.chat.id, "Пожалуйста, используйте кнопки меню.")
        return
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    state = user_state.get(chat_id)
    if state in [
        "awaiting_prompt", "awaiting_generate_prompt", "awaiting_photo",
        "awaiting_video_prompt", "awaiting_video_image_first",
        "awaiting_video_image_last", "awaiting_video_last_choice",
    ]:
        return
    if chat_id == ADMIN_ID:
        reply = ask_deepseek(message.text)
        bot.send_message(chat_id, reply, reply_markup=back_keyboard())
        with data_lock:
            save_data()
        return
    with data_lock:
        current_count = user_message_count.get(chat_id, 0)
        next_count = current_count + 1
        pending_charge = False
        if next_count >= 50:
            if user_credits.get(chat_id, 0) < CREDIT_COSTS["deepseek_session"]:
                save_data()
                bot.send_message(chat_id, "❌ Недостаточно ♦ для продолжения чата. Пополните баланс в магазине 💰.")
                return
            pending_charge = True
        user_message_count[chat_id] = next_count
        save_data()
    reply = ask_deepseek(message.text)
    if pending_charge and reply and not reply.startswith("⚠️") and not reply.startswith("❌"):
        with data_lock:
            user_credits[chat_id] -= CREDIT_COSTS["deepseek_session"]
            user_credit_history[chat_id].append((time.time(), -CREDIT_COSTS["deepseek_session"], "Пакет из 50 сообщений DeepSeek"))
            user_message_count[chat_id] = 0
            save_data()
        bot.send_message(chat_id, f"💬 Использовано 50 сообщений. Списано {CREDIT_COSTS['deepseek_session']} ♦. Осталось: {user_credits[chat_id]} ♦.")
    elif pending_charge:
        with data_lock:
            user_message_count[chat_id] -= 1
            save_data()
        bot.send_message(chat_id, "⚠️ Ошибка получения ответа. ♦ не списаны.")
    bot.send_message(chat_id, reply, reply_markup=back_keyboard())
    with data_lock:
        save_data()

@bot.message_handler(func=lambda m: True)
def handle_other(message):
    bot.send_message(message.chat.id, "Пожалуйста, используй кнопки меню.")

# ================== WEBHOOK & RUN ==================
@app.route("/")
def index():
    return "Bot is running"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        try:
            json_data = json.loads(request.get_data().decode("utf-8"))
            update = telebot.types.Update.de_json(json_data)
            bot.process_new_updates([update])
            return "OK", 200
        except Exception as e:
            print(f"Webhook processing error: {e}")
            return "Bad Request", 400
    return "Forbidden", 403

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

def set_webhook():
    try:
        # Удаляем старый webhook + pending updates
        del_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true"
        r = requests.get(del_url, timeout=10)
        print(f"deleteWebhook: {r.status_code} | {r.text}")

        time.sleep(1)

        host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if not host:
            host = os.getenv("WEBHOOK_HOST")

        if not host:
            print("ERROR: RENDER_EXTERNAL_HOSTNAME or WEBHOOK_HOST not set!")
            return

        webhook_url = f"https://{host}/{TELEGRAM_TOKEN}"
        set_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}"
        r = requests.get(set_url, timeout=10)
        print(f"setWebhook: {r.status_code} | {r.text}")

        if r.status_code == 200 and r.json().get("ok"):
            print(f"✅ Webhook OK: {webhook_url}")
        else:
            print(f"❌ Webhook FAILED: {r.text}")
    except Exception as e:
        print(f"❌ Webhook exception: {e}")

if __name__ == "__main__":
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port)
