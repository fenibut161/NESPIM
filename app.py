import os
import sys
import telebot
import requests
import time
import base64
import urllib3
import json
import logging
import re
from html import escape, unescape
from flask import Flask, request, send_from_directory
from threading import Thread, RLock
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice
)
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
data_lock = RLock()

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# --- DATA ---
user_credits = defaultdict(int)
user_credit_history = defaultdict(list)
user_message_count = defaultdict(int)
user_last_activity = defaultdict(float)
user_chat_history = defaultdict(list)  # <--- ДОБАВЛЕНО: память диалогов агента

user_state = {}
user_edit_model = {}
user_face_mode = {}
user_generate_model = {}
user_generate_aspect = {}
user_pending_photo = {}
user_video_mode = {}
user_video_frames = {}
user_video_params = {}
user_video_model = {}
user_video_history = defaultdict(list)

# --- CHAIN EDIT ---
user_last_image = {}
user_last_edit_model = {}
user_last_face_mode = {}
user_last_edit_aspect = {}

# --- EDIT ASPECT ---
user_edit_aspect = {}

# --- MODELS ---
FLUX_MODEL = "black-forest-labs/flux.2-pro"
SEEDREAM_MODEL = "bytedance-seed/seedream-4.5"

ASPECT_PROMPTS = {
    "9:16": "vertical 9:16 portrait orientation, tall composition, full frame, mobile phone wallpaper format",
    "16:9": "horizontal 16:9 widescreen landscape orientation, cinematic wide composition",
    "1:1": "square 1:1 composition, Instagram post format, centered subject",
    "4:3": "standard 4:3 photo composition, classic portrait or landscape ratio",
}

# --- GIST SYNC ---
def load_data():
    global user_credits, user_credit_history, user_message_count, user_last_activity, user_chat_history
    data = None
    source = "fresh"

    if GIST_ID and GITHUB_TOKEN:
        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        try:
            r = requests.get(url, headers=headers, timeout=30)
            logging.info(f"[LOAD] Gist GET {r.status_code}")
            if r.status_code == 200:
                gist_data = r.json()
                content = gist_data["files"]["bot_data.json"]["content"]
                data = json.loads(content)
                logging.info(f"[LOAD] Raw Gist content: {str(data)[:200]}")
                if data and isinstance(data, dict) and any([
                    data.get("credits"), data.get("history"), data.get("messages")
                ]):
                    source = "Gist"
                    total_credits = sum(data.get("credits", {}).values())
                    logging.info(f"[LOAD] Gist parsed OK: {len(data.get('credits', {}))} users, {total_credits} total credits")
                else:
                    logging.info("[LOAD] Gist returned empty/invalid data, fallback to local")
                    data = None
            else:
                logging.error(f"[LOAD] Gist HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            logging.error(f"[LOAD] Gist exception: {e}")

    if data is None:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                source = "local file"
                logging.info(f"[LOAD] Local file OK: {len(data.get('credits', {}))} users")
        except FileNotFoundError:
            logging.info("[LOAD] No local file, starting fresh")
            data = {}
        except Exception as e:
            logging.error(f"[LOAD] Local file error: {e}")
            data = {}

    user_credits = defaultdict(int, {int(k): v for k, v in data.get("credits", {}).items()})
    user_credit_history = defaultdict(list, {int(k): v for k, v in data.get("history", {}).items()})
    user_message_count = defaultdict(int, {int(k): v for k, v in data.get("messages", {}).items()})
    user_last_activity = defaultdict(float, {int(k): v for k, v in data.get("last_activity", {}).items()})
    user_chat_history = defaultdict(list, {int(k): v for k, v in data.get("chat_history", {}).items()})
    logging.info(f"[LOAD] Final state from {source}: {sum(user_credits.values())} total credits")

def save_data():
    with data_lock:
        data = {
            "credits": dict(user_credits),
            "history": dict(user_credit_history),
            "messages": dict(user_message_count),
            "last_activity": dict(user_last_activity),
            "chat_history": dict(user_chat_history),
        }
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                logging.info("[SAVE] Local file OK")
        except Exception as e:
            logging.error(f"[SAVE] Local file error: {e}")

        if GIST_ID and GITHUB_TOKEN:
            try:
                url = f"https://api.github.com/gists/{GIST_ID}"
                headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
                payload = {"files": {"bot_data.json": {"content": json.dumps(data, ensure_ascii=False, indent=2)}}}
                total_credits = sum(data["credits"].values())
                logging.info(f"[SAVE] Sending to Gist: {len(data['credits'])} users, {total_credits} total credits")
                r = requests.patch(url, json=payload, headers=headers, timeout=30)
                logging.info(f"[SAVE] Gist response: {r.status_code} | {r.text[:300]}")
                if r.status_code == 200:
                    logging.info("[SAVE] Gist OK")
                else:
                    logging.error(f"[SAVE] Gist FAILED {r.status_code}")
            except Exception as e:
                logging.error(f"[SAVE] Gist exception: {e}")
        else:
            logging.warning(f"[SAVE] Skipped Gist: GIST_ID={'set' if GIST_ID else 'missing'}, GITHUB_TOKEN={'set' if GITHUB_TOKEN else 'missing'}")

    sys.stdout.flush()

load_data()

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)

os.makedirs("static", exist_ok=True)

VIDEO_MODEL_FEATURES = {
    "bytedance/seedance-2.0": {"audio": True, "resolution": True},
    "kwaivgi/kling-video-o1": {"audio": True, "resolution": True},
    "kwaivgi/kling-v3-pro": {"audio": True, "resolution": True},
}

PACKAGES = {
    "start": {"name": "Старт", "credits": 50, "price_stars": 250, "price_rub": 400, "desc": "50 🔷 на любые операции"},
    "optima": {"name": "Оптима", "credits": 150, "price_stars": 625, "price_rub": 1000, "desc": "150 🔷 (выгоднее)"},
    "maxi": {"name": "Макси", "credits": 400, "price_stars": 1500, "price_rub": 2400, "desc": "400 🔷 (максимальная выгода)"},
}

CREDIT_COSTS = {
    "image_pro": 2,
    "edit_pro": 3,
    "video": {5: 25, 10: 50, 15: 100},
    "deepseek_session": 1,
}

def _build_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot",
    }

# ================== AGENT TOOLS HELPERS ==================
def helper_web_search(query):
    try:
        url = "https://lite.duckduckgo.com/lite/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.post(url, data={"q": query}, headers=headers, timeout=10)
        text = unescape(r.text)
        snippets = re.findall(r'<td class=[\x27"]result-snippet[\x27"]>(.*?)</td>', text, re.DOTALL)
        clean = [re.sub(r'<.*?>', '', s).strip() for s in snippets[:4]]
        return clean if clean else ["По запросу ничего не найдено в поисковике."]
    except Exception as e:
        return [f"Ошибка веб-поиска: {e}"]

def helper_fetch_webpage(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        text = unescape(r.text)
        text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<.*?>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2500] if text else "Веб-страница пустая."
    except Exception as e:
        return f"Не удалось прочитать ссылку: {e}"

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Поиск актуальных новостей, фактов, документации или информации в интернете Google/DuckDuckGo",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Прочесть текстовое содержимое веб-страницы по ссылке (URL)",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Прямая ссылка http/https"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Нарисовать и отправить юзеру картинку через нейросеть Flux Pro. Списывает 2 токена 🔷.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Промпт для генерации картинки на английском или русском"},
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3"], "description": "Формат кадра"}
                },
                "required": ["prompt", "aspect_ratio"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_balance",
            "description": "Проверить текущий баланс токенов 🔷 пользователя и остаток сообщений в пакете чата",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_memory",
            "description": "Очистить память диалога с пользователем (когда просят забыть контекст)",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# ================== DEEPSEEK AGENT CORE ==================
def ask_deepseek(prompt):
    # Оставлено для обратной совместимости системных вызовов
    headers = _build_headers()
    payload = {"model": "deepseek/deepseek-v4-pro", "messages": [{"role": "user", "content": prompt}]}
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        logging.error(f"DeepSeek error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logging.error(f"DeepSeek exception: {e}")
    return "⚠️ Ошибка соединения"

def run_agent(chat_id, user_text):
    history = list(user_chat_history.get(chat_id, []))
    if len(history) > 20:
        history = history[-18:]

    system_prompt = (
        "Ты — персональный ИИ-агент и помощник в Telegram. Ты умный, вежливый, инициативный.\n"
        "Твои возможности (инструменты):\n"
        "1. web_search — гуглить в интернете факты, новости, документацию.\n"
        "2. fetch_webpage — читать ссылки, присланные пользователем.\n"
        "3. generate_image — генерировать арты/картинки (нейросеть Flux Pro, стоит 2 🔷).\n"
        "4. get_my_balance — проверять баланс токенов 🔷 пользователя.\n"
        "5. clear_memory — очищать историю текущей беседы.\n\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "- Если юзер просит нарисовать картинку/арт/логотип — НЕ описывай её словами, а СРАЗУ вызывай функцию generate_image!\n"
        "- Если юзер кидает ссылку — прочти её через fetch_webpage перед ответом.\n"
        "- Если юзер спрашивает о событиях после 2024 года — используй web_search.\n"
        "- Отвечай понятно, емко, на языке собеседника (обычно русский)."
    )

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]
    headers = _build_headers()

    for turn in range(5):
        payload = {
            "model": "deepseek/deepseek-v4-pro",
            "messages": messages,
            "tools": AGENT_TOOLS
        }
        try:
            r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
            if r.status_code != 200:
                logging.error(f"[AGENT ERROR] {r.status_code}: {r.text[:300]}")
                return "⚠️ Ошибка связи с нейросетью."

            data = r.json()
            msg = data["choices"][0]["message"]

            if "tool_calls" in msg and msg["tool_calls"]:
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"]["arguments"]
                    call_id = tc["id"]

                    try:
                        args = json.loads(fn_args)
                    except Exception:
                        args = {}

                    logging.info(f"[AGENT TOOL] chat_id={chat_id} -> {fn_name}({args})")
                    res_content = ""

                    if fn_name == "web_search":
                        res_content = "\n".join(helper_web_search(args.get("query", "")))
                    elif fn_name == "fetch_webpage":
                        res_content = helper_fetch_webpage(args.get("url", ""))
                    elif fn_name == "get_my_balance":
                        bal = user_credits.get(chat_id, 0)
                        rem_msgs = 50 - user_message_count.get(chat_id, 0)
                        res_content = f"Баланс: {bal} 🔷. Осталось сообщений в пакете чата: {rem_msgs}/50."
                    elif fn_name == "clear_memory":
                        user_chat_history[chat_id] = []
                        save_data()
                        res_content = "Память диалога успешно очищена."
                    elif fn_name == "generate_image":
                        p = args.get("prompt", "")
                        asp = args.get("aspect_ratio", "16:9")
                        cost = CREDIT_COSTS["image_pro"]
                        can_gen = False

                        with data_lock:
                            if chat_id == ADMIN_ID or user_credits.get(chat_id, 0) >= cost:
                                if chat_id != ADMIN_ID:
                                    user_credits[chat_id] -= cost
                                    user_credit_history[chat_id].append((time.time(), -cost, f"Агент: арт {asp}"))
                                    save_data()
                                can_gen = True

                        if not can_gen:
                            res_content = f"У юзера недостаточно токенов (нужно {cost} 🔷, баланс {user_credits.get(chat_id, 0)})."
                        else:
                            bot.send_message(chat_id, f"🎨 Агент генерирует изображение ({asp})...")
                            full_p = f"{p}. {ASPECT_PROMPTS.get(asp, '')}" if asp in ASPECT_PROMPTS else p
                            img_bytes = generate_image_flux(full_p)
                            if img_bytes:
                                out_b, _ = _prepare_image_bytes(img_bytes)
                                bot.send_photo(chat_id, out_b or img_bytes, caption="🎨 Создано ИИ-агентом")
                                res_content = "Картинка успешно создана и отправлена в чат юзеру."
                            else:
                                if chat_id != ADMIN_ID:
                                    with data_lock:
                                        user_credits[chat_id] += cost
                                        save_data()
                                res_content = "Ошибка генерации картинки (токены возвращены юзеру)."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": fn_name,
                        "content": str(res_content)
                    })
            else:
                final_text = msg.get("content", "")
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": final_text})
                user_chat_history[chat_id] = history[-20:]
                return final_text
        except Exception as e:
            logging.error(f"[AGENT EXCEPTION] {e}")
            return "⚠️ Произошла ошибка при работе ИИ-агента."

    return "⚠️ Агент превысил лимит шагов рассуждения."

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

def _prepare_image_bytes(img_data, quality=95, max_size_mb=5):
    try:
        img = Image.open(io.BytesIO(img_data))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        output = buf.getvalue()
        if len(output) > max_size_mb * 1024 * 1024 and quality > 60:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            output = buf.getvalue()
        return output, None
    except Exception as e:
        return None, str(e)

# ================== FLUX ==================
def generate_image_flux(prompt):
    payload = {"model": FLUX_MODEL, "messages": [{"role": "user", "content": prompt}], "modalities": ["image"]}
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)[0]
    except Exception as e:
        logging.error(f"Flux generation error: {e}")
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
        logging.error(f"Flux edit error: {e}")
        return None, str(e)

# ================== SEEDREAM ==================
def generate_image_seedream(prompt):
    payload = {"model": SEEDREAM_MODEL, "messages": [{"role": "user", "content": prompt}], "modalities": ["image"]}
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)[0]
    except Exception as e:
        logging.error(f"Seedream generation error: {e}")
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
        logging.error(f"Seedream edit error: {e}")
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
        logging.error(f"Compress error: {e}")
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
        logging.error(f"send_video error: {e}")
        try:
            doc_file = io.BytesIO(data)
            doc_file.name = "video.mp4"
            bot.send_document(chat_id, doc_file, caption="✅ Видео (как файл)")
            return True
        except Exception as e2:
            logging.error(f"send_document error: {e2}")
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
                bot.send_message(chat_id, f"❌ Недостаточно 🔷. Нужно {cost}, у вас {user_credits.get(chat_id, 0)}. Пополните баланс в магазине 💰.")
                return False
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Видео {duration}с"))
            save_data()
        bot.send_message(chat_id, f"✅ Списано {cost} 🔷. Осталось: {user_credits[chat_id]}")
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
    headers = _build_headers()
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
    logging.info(f"Video payload: {json.dumps({k: v for k, v in payload.items() if k != 'frame_images'})}")
    try:
        resp = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
        if resp.status_code not in (200, 202):
            with data_lock:
                if chat_id != ADMIN_ID:
                    user_credits[chat_id] = user_credits.get(chat_id, 0) + cost
                    user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео"))
                    save_data()
            bot.send_message(chat_id, f"❌ Ошибка {resp.status_code}. 🔷 возвращены.")
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
        bot.send_message(chat_id, "❌ Пустой ответ. 🔷 возвращены.")
    except Exception as e:
        logging.error(f"Video exception: {e}")
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, "Возврат за видео (ошибка)"))
                save_data()
        bot.send_message(chat_id, "❌ Ошибка связи. 🔷 возвращены.")
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
        KeyboardButton("📖 Инструкция"),
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
    text = f"👤 **Ваш профиль**\n\n💰 Баланс: {credits} 🔷\n\n"
    if history:
        text += "📋 **Последние операции:**\n"
        for ts, delta, reason in history[-5:]:
            sign = "+" if delta > 0 else ""
            text += f"{sign}{delta} 🔷 – {escape(reason)}\n"
    else:
        text += "📋 **Операций пока нет.**"
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
        "🛒 **Магазин токенов 🔷**\n"
        " 🔷 за токены приобретается:\n"
        "• Генерация (Flux/Seedream) — 2 🔷\n"
        "• Редактирование фото (Flux/Seedream) — 3 🔷\n"
        "• Видео 5 сек — 25 🔷, 10 сек — 50 🔷, 15 сек — 100 🔷\n"
        "• Чат с ИИ-агентом — 1 🔷 за 50 сообщений\n\n"
        "Выберите пакет:"
    )
    for key, pkg in PACKAGES.items():
        text += f"\n **{escape(pkg['name'])}**: {pkg['credits']} 🔷 — {pkg['price_stars']} ⭐️ / {pkg['price_rub']} ₽"
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
        logging.error(f"Invoice error: {e}")
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
        bot.send_message(chat_id, f"✅ Оплата прошла! Начислено {pkg['credits']} 🔷.\nБаланс: {user_credits[chat_id]} 🔷")

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
        f"💳 **Оплата картой — пакет «{pkg['name']}»**\n\n"
        f"Сумма: **{pkg['price_rub']} ₽**\n"
        f"Вы получите: **{pkg['credits']} 🔷**\n\n"
        f"Переведите сумму на Т-Банк / СБЕР по номеру:\n"
        f"`+79192329005`\n\n"
        f"❗️ **Укажите в комментарии к переводу ваш Telegram ID:**\n"
        f"`{chat_id}`\n\n"
        f"После перевода 🔷 начислятся вручную в течение 15 минут.",
        parse_mode="HTML",
    )
    bot.answer_callback_query(call.id, "Реквизиты отправлены")
    try:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"✅ Начислить {pkg['credits']}🔷", callback_data=f"admin_grant_{chat_id}_{pkg_key}"))
        bot.send_message(
            ADMIN_ID,
            f"💳 **Запрос на оплату картой**\n\n"
            f"Пользователь: {username}\n"
            f"ID: `{chat_id}`\n"
            f"Пакет: **{pkg['name']}**\n"
            f"Сумма: {pkg['price_rub']} ₽\n"
            f"🔷: {pkg['credits']}",
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

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
    bot.answer_callback_query(call.id, f"Начислено {pkg['credits']} 🔷")
    bot.edit_message_text(
        f"✅ **Начислено**\nПользователю {target_id}: +{pkg['credits']} 🔷",
        call.message.chat.id,
        call.message.message_id,
    )
    try:
        bot.send_message(target_id, f"🎉 Администратор начислил вам {pkg['credits']} 🔷 (пакет «{pkg['name']}»).\nВаш баланс: {user_credits[target_id]} 🔷")
    except Exception as e:
        logging.error(f"Не удалось уведомить {target_id}: {e}")

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
        text = f"👑 Админ-панель\nПользователей: {len(user_credits)}\n🔷 всего: {total_credits}\n\nКоманды:\n/addcredits <uid> <amount>\n/removecredits <uid> <amount>"
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

        current_balance = user_credits[uid]
        history_count = len(user_credit_history[uid])
        confirm_text = (
            f"✅ **Начисление выполнено**\n\n"
            f"👤 Пользователь: `{uid}`\n"
            f"➕ Начислено: {amt} 🔷\n"
            f"💰 Текущий баланс: {current_balance} 🔷\n"
            f"📋 Всего операций: {history_count}"
        )
        bot.send_message(message.chat.id, confirm_text, parse_mode="HTML")

        try:
            bot.send_message(uid, f"🎉 Администратор начислил вам {amt} 🔷.\nВаш баланс: {current_balance} 🔷")
        except Exception as e:
            logging.error(f"Не удалось уведомить {uid}: {e}")
    except Exception:
        bot.send_message(message.chat.id, "Формат: /addcredits <uid> <amount>")

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
                bot.send_message(message.chat.id, f"✅ Списано {amt} 🔷 у {uid}\nТекущий баланс: {user_credits[uid]} 🔷")
                try:
                    bot.send_message(uid, f"ℹ️ Администратор списал {amt} 🔷. Баланс: {user_credits[uid]}")
                except Exception as e:
                    logging.error(f"Не удалось уведомить {uid}: {e}")
            else:
                bot.send_message(message.chat.id, "Недостаточно 🔷")
    except Exception as e:
        logging.error(f"Remove credits error: {e}")
        bot.send_message(message.chat.id, "Формат: /removecredits <uid> <amount>")

# ================== START & MENU ==================
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    send_main_menu(chat_id, "👋 Привет! Я умею генерировать изображения (Flux/Seedream), редактировать фото, создавать видео, а в режиме «Чат» работаю как полноценный ИИ-агент с доступом в интернет. Выбери действие ниже.")

def send_main_menu(chat_id, text="Главное меню:"):
    bot.send_message(chat_id, text, reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.text == "🖼 Создать изображение")
def menu_generate_image(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_model_generate"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌊 Flux (2🔷)", callback_data="gen_flux"),
        InlineKeyboardButton("🎨 Seedream (2🔷)", callback_data="gen_seedream"),
    )
    bot.send_message(message.chat.id, "Выбери модель для генерации:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🎨 Редактировать фото")
def menu_edit_photo(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_model_edit"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌊 Flux (3🔷)", callback_data="edit_flux"),
        InlineKeyboardButton("🎨 Seedream (3🔷)", callback_data="edit_seedream"),
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
    bot.send_message(message.chat.id, "🤖 Режим ИИ-агента активирован!\nЯ запоминаю контекст диалога, умею сам гуглить свежую информацию, переходить по ссылкам и рисовать арты (просто попроси «нарисуй...»). Каждые 50 сообщений списывается 1 🔷.", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def menu_profile(message):
    user_last_activity[message.chat.id] = time.time()
    profile(message)

@bot.message_handler(func=lambda m: m.text == "💰 Магазин")
def menu_shop(message):
    user_last_activity[message.chat.id] = time.time()
    shop(message)

@bot.message_handler(func=lambda m: m.text == "📖 Инструкция")
def menu_help(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    text = (
        "📖 <b>Руководство пользователя</b>\n\n"
        "🤖 <b>1. Спросить (ИИ-Агент)</b>\n"
        "Твой умный ассистент. Он помнит контекст диалога, умеет гуглить свежую информацию, переходить по ссылкам и рисовать арты по просьбе (просто напиши <i>«нарисуй киберпанк кота 1:1»</i>).\n"
        "Команды агенту в чате:\n"
        "• <i>«Забудь всё»</i> — очистить память разговора.\n"
        "• <i>«Какой баланс?»</i> — проверить токены.\n"
        "💎 <b>Цена:</b> 1 🔷 за пакет из 50 сообщений.\n\n"
        "🖼 <b>2. Создать изображение</b>\n"
        "Генерация картинок по тексту. Модели:\n"
        "• <b>Flux Pro</b> — фотореализм и идеальные детали.\n"
        "• <b>Seedream</b> — сочные цвета и арт-стили.\n"
        "💎 <b>Цена:</b> 2 🔷 за картинку.\n\n"
        "🎨 <b>3. Редактировать фото</b>\n"
        "Изменение ваших фотографий по тексту.\n"
        "• Режим <b>«Сохранить лицо»</b> — нейросеть поменяет фон и одежду, но оставит черты лица человека неизменными.\n"
        "• Можно дорабатывать фото шаг за шагом по цепочке.\n"
        "💎 <b>Цена:</b> 3 🔷 за обработку.\n\n"
        "🎥 <b>4. Создать видео</b>\n"
        "Генерация видеороликов из текста или по фото (модели Seedance 2.0, Kling Pro/O1).\n"
        "💎 <b>Цена:</b> 5 сек — 25 🔷 | 10 сек — 50 🔷 | 15 сек — 100 🔷\n\n"
        "💰 <b>5. Баланс и покупки</b>\n"
        "В «Профиле» виден остаток токенов. Пополнить баланс можно в «Магазине» за Telegram Stars ⭐️ мгновенно или переводом на карту.\n\n"
        "💡 <i>Если бот застрял или ждет фото, а вы передумали — просто нажмите кнопку «🔙 Главное меню» или отправьте /start.</i>"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_to_main(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state.pop(chat_id, None)
    user_edit_model.pop(chat_id, None)
    user_face_mode.pop(chat_id, None)
    user_generate_model.pop(chat_id, None)
    user_generate_aspect.pop(chat_id, None)
    user_pending_photo.pop(chat_id, None)
    user_video_frames.pop(chat_id, None)
    user_video_params.pop(chat_id, None)
    user_video_model.pop(chat_id, None)
    user_video_mode.pop(chat_id, None)
    user_last_image.pop(chat_id, None)
    user_last_edit_model.pop(chat_id, None)
    user_last_face_mode.pop(chat_id, None)
    user_last_edit_aspect.pop(chat_id, None)
    user_edit_aspect.pop(chat_id, None)
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

# --- GENERATION: model → aspect → prompt ---
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
    user_state[chat_id] = "selecting_aspect"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📱 9:16 (сторис/телефон)", callback_data="aspect_9_16"),
        InlineKeyboardButton("🖥 16:9 (широкий)", callback_data="aspect_16_9"),
        InlineKeyboardButton("⬜ 1:1 (квадрат/инста)", callback_data="aspect_1_1"),
        InlineKeyboardButton("📷 4:3 (фото)", callback_data="aspect_4_3"),
    )
    bot.send_message(chat_id, "Выберите формат изображения:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("aspect_"))
def set_aspect(call):
    chat_id = call.message.chat.id
    aspect = call.data.split("_")[1] + ":" + call.data.split("_")[2]
    user_generate_aspect[chat_id] = aspect
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = "awaiting_generate_prompt"
    bot.send_message(chat_id, f"Формат: {aspect}. Введите описание изображения:", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id, f"Формат {aspect}")

# --- EDITING: model → aspect → face → photo ---
@bot.callback_query_handler(func=lambda call: call.data in ("edit_flux", "edit_seedream"))
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
        InlineKeyboardButton("📱 9:16 (сторис)", callback_data="edit_aspect_9_16"),
        InlineKeyboardButton("🖥 16:9 (широкий)", callback_data="edit_aspect_16_9"),
        InlineKeyboardButton("⬜ 1:1 (квадрат)", callback_data="edit_aspect_1_1"),
        InlineKeyboardButton("📷 4:3 (фото)", callback_data="edit_aspect_4_3"),
    )
    bot.send_message(chat_id, "Выберите формат итогового изображения:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_aspect_"))
def set_edit_aspect(call):
    chat_id = call.message.chat.id
    parts = call.data.split("_")
    aspect = parts[2] + ":" + parts[3]
    user_edit_aspect[chat_id] = aspect
    bot.answer_callback_query(call.id, f"Формат: {aspect}")
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

# --- CHAIN EDIT callbacks ---
@bot.callback_query_handler(func=lambda call: call.data == "edit_again")
def edit_again(call):
    chat_id = call.message.chat.id
    if chat_id not in user_last_image:
        bot.answer_callback_query(call.id, "Нет сохранённого фото")
        return

    user_pending_photo[chat_id] = user_last_image[chat_id]
    user_edit_model[chat_id] = user_last_edit_model.get(chat_id, "flux")
    user_face_mode[chat_id] = user_last_face_mode.get(chat_id, "full_edit")
    user_edit_aspect[chat_id] = user_last_edit_aspect.get(chat_id, "16:9")
    user_state[chat_id] = "awaiting_prompt"

    logging.info(f"[EDIT AGAIN] chat_id={chat_id}, model={user_edit_model[chat_id]}, "
                 f"face={user_face_mode[chat_id]}, aspect={user_edit_aspect[chat_id]}")

    bot.send_message(chat_id, "✏️ Введите новый промпт для доработки этого фото:", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id, "Готово к редактированию")

@bot.callback_query_handler(func=lambda call: call.data == "goto_main")
def goto_main_handler(call):
    chat_id = call.message.chat.id
    for d in [user_state, user_edit_model, user_face_mode, user_generate_model,
              user_generate_aspect, user_pending_photo, user_last_image,
              user_last_edit_model, user_last_face_mode, user_last_edit_aspect,
              user_edit_aspect, user_video_frames, user_video_params,
              user_video_model, user_video_mode]:
        d.pop(chat_id, None)
    bot.delete_message(chat_id, call.message.message_id)
    send_main_menu(chat_id)
    bot.answer_callback_query(call.id, "Главное меню")

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
    aspect = user_generate_aspect.pop(chat_id, "16:9")
    user_state[chat_id] = None
    cost = CREDIT_COSTS["image_pro"]

    aspect_hint = ASPECT_PROMPTS.get(aspect, "")
    full_prompt = f"{prompt}. {aspect_hint}" if aspect_hint else prompt

    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Недостаточно 🔷. Нужно {cost} 🔷.")
                send_main_menu(chat_id)
                return
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Генерация {model} {aspect}"))
            save_data()
        bot.send_message(chat_id, f"✅ Списано {cost} 🔷. Осталось: {user_credits[chat_id]}")
    bot.send_message(chat_id, f"🎨 Генерирую через {model} ({aspect})...")
    if model == "flux":
        img_data = generate_image_flux(full_prompt)
    else:
        img_data = generate_image_seedream(full_prompt)
    if img_data:
        output, err = _prepare_image_bytes(img_data)
        if err:
            logging.error(f"Image prepare error: {err}")
            output = img_data
        try:
            bot.send_photo(chat_id, output, caption=f"✅ Готово! ({aspect})")
        except Exception as e:
            logging.error(f"Image send error: {e}")
            bot.send_document(chat_id, img_data, caption=f"✅ Готово (файл) ({aspect})")
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, f"Возврат за генерацию {model}"))
                save_data()
        bot.send_message(chat_id, f"❌ Ошибка генерации. {cost} 🔷 возвращены.")
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
    aspect = user_edit_aspect.pop(chat_id, None)
    user_state[chat_id] = None

    if aspect and aspect in ASPECT_PROMPTS:
        if not prompt.lower().startswith(ASPECT_PROMPTS[aspect].lower()[:10]):
            prompt = f"{ASPECT_PROMPTS[aspect]}. {prompt}"
        user_last_edit_aspect[chat_id] = aspect

    if face_mode == "keep_face":
        prompt = "Keep the face and facial features completely unchanged. Do not modify the face. Only apply the following changes: " + prompt

    cost = CREDIT_COSTS["edit_pro"]
    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Недостаточно 🔷. Нужно {cost} 🔷.")
                send_main_menu(chat_id)
                return
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Редактирование {model}"))
            save_data()
        bot.send_message(chat_id, f"✅ Списано {cost} 🔷. Осталось: {user_credits[chat_id]}")

    logging.info(f"[EDIT] chat_id={chat_id}, model={model}, face={face_mode}, aspect={aspect}")
    bot.send_message(chat_id, f"🎨 Редактирую через {model}...")

    if model == "flux":
        img_data, error_msg = edit_image_flux(prompt, photo_base64)
    else:
        img_data, error_msg = edit_image_seedream(prompt, photo_base64)

    if img_data:
        caption = f"✅ Отредактировано ({model})"
        if face_mode == "keep_face":
            caption += " с сохранением лица"

        user_last_image[chat_id] = base64.b64encode(img_data).decode('utf-8')
        user_last_edit_model[chat_id] = model
        user_last_face_mode[chat_id] = face_mode
        if aspect:
            user_last_edit_aspect[chat_id] = aspect

        output, err = _prepare_image_bytes(img_data)
        if err:
            logging.error(f"Edit prepare error: {err}")
            output = img_data

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🔄 Продолжить редактирование", callback_data="edit_again"),
            InlineKeyboardButton("🔙 Главное меню", callback_data="goto_main"),
        )

        try:
            bot.send_photo(chat_id, output, caption=caption, reply_markup=markup)
        except Exception as e:
            logging.error(f"Edit image send error: {e}")
            bot.send_document(chat_id, io.BytesIO(img_data), caption=caption, reply_markup=markup)
        return

    elif error_msg:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, f"Возврат за редактирование {model}"))
                save_data()
        bot.send_message(chat_id, f"❌ Ошибка редактирования. {cost} 🔷 возвращены.")
        bot.send_message(chat_id, f"❌ Не удалось отредактировать изображение.\n{error_msg}")
        send_main_menu(chat_id)
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, "Возврат за редактирование (пустой ответ)"))
                save_data()
        bot.send_message(chat_id, "❌ Не удалось отредактировать изображение. 🔷 возвращены.")
        send_main_menu(chat_id)

# ================== VIDEO PROMPT ==================
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_prompt")
def handle_video_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    prompt = message.text
    user_state[chat_id] = None
    logging.info(f"=== VIDEO START {chat_id} ===")
    logging.info(f"Prompt: {prompt}")
    first_frame = user_video_frames.get(chat_id, {}).get("first")
    last_frame = user_video_frames.get(chat_id, {}).get("last")
    user_video_frames.pop(chat_id, None)
    Thread(target=generate_video_async, args=(chat_id, prompt, first_frame, last_frame), daemon=True).start()

# ================== CHAT (AGENT MODE) ==================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text_chat(message):
    if message.text.startswith("/"):
        return
    if message.text in [
        "🖼 Создать изображение", "🎨 Редактировать фото", "🎥 Создать видео",
        "💬 Спросить (чат)", "👤 Профиль", "💰 Магазин", "🔙 Главное меню",
        "📖 Инструкция",
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
        "selecting_aspect", "select_model_edit", "select_model_generate",
    ]:
        return

    if chat_id == ADMIN_ID:
        reply = run_agent(chat_id, message.text)
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
                bot.send_message(chat_id, "❌ Недостаточно 🔷 для продолжения чата. Пополните баланс в магазине 💰.")
                return
            pending_charge = True
        user_message_count[chat_id] = next_count
        save_data()

    reply = run_agent(chat_id, message.text)

    if pending_charge and reply and not reply.startswith("⚠️") and not reply.startswith("❌"):
        with data_lock:
            user_credits[chat_id] -= CREDIT_COSTS["deepseek_session"]
            user_credit_history[chat_id].append((time.time(), -CREDIT_COSTS["deepseek_session"], "Пакет из 50 сообщений Агента"))
            user_message_count[chat_id] = 0
            save_data()
        bot.send_message(chat_id, f"💬 Использовано 50 сообщений. Списано {CREDIT_COSTS['deepseek_session']} 🔷. Осталось: {user_credits[chat_id]} 🔷.")
    elif pending_charge:
        with data_lock:
            user_message_count[chat_id] -= 1
            save_data()
        bot.send_message(chat_id, "⚠️ Ошибка получения ответа агента. 🔷 не списаны.")

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

@app.route("/health")
def health():
    return "OK", 200

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        try:
            json_data = json.loads(request.get_data().decode("utf-8"))
            update = telebot.types.Update.de_json(json_data)
            bot.process_new_updates([update])
            return "OK", 200
        except Exception as e:
            logging.error(f"Webhook processing error: {e}")
            return "Bad Request", 400
    return "Forbidden", 403

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

def set_webhook():
    try:
        del_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true"
        r = requests.get(del_url, timeout=10)
        logging.info(f"deleteWebhook: {r.status_code} | {r.text}")

        time.sleep(1)

        host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if not host:
            host = os.getenv("WEBHOOK_HOST")

        if not host:
            logging.error("ERROR: RENDER_EXTERNAL_HOSTNAME or WEBHOOK_HOST not set!")
            return

        webhook_url = f"https://{host}/{TELEGRAM_TOKEN}"
        set_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}"
        r = requests.get(set_url, timeout=10)
        logging.info(f"setWebhook: {r.status_code} | {r.text}")

        if r.status_code == 200 and r.json().get("ok"):
            logging.info("✅ Webhook OK")
        else:
            logging.error("❌ Webhook FAILED")
    except Exception as e:
        logging.error(f"❌ Webhook exception: {e}")

if __name__ == "__main__":
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port)
