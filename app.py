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
OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Словари состояний и данных
user_state = {}
user_edit_model = {}
user_face_mode = {}
user_generate_model = {}
user_pending_photo = {}
user_video_mode = {}
user_video_frames = {}
user_video_params = {}

# ================== 1. GIGACHAT ==================
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
            logging.error(f"GigaChat: ошибка получения токена {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"GigaChat: исключение {e}")
        return None

def download_gigachat_file(token, file_id):
    url = f"https://gigachat.devices.sberbank.ru/api/v1/files/{file_id}/content"
    headers = {"Authorization": f"Bearer {token}", "Accept": "image/jpeg"}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            return response.content
        else:
            logging.error(f"GigaChat: ошибка скачивания {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"GigaChat: исключение {e}")
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
                file_data = download_gigachat_file(token, file_id)
                if file_data:
                    return file_data
            logging.error("GigaChat: не найден file_id в ответе")
        else:
            logging.error(f"GigaChat: ошибка {response.status_code}")
    except Exception as e:
        logging.error(f"GigaChat: исключение {e}")
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

# ================== 4. ГЕНЕРАЦИЯ ВИДЕО (с улучшенной обработкой ошибок) ==================
def compress_image_if_needed(b64_str, max_size=(640, 640), quality=80):
    try:
        img_data = base64.b64decode(b64_str)
        img = Image.open(io.BytesIO(img_data))
        img.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logging.error(f"Ошибка сжатия изображения: {e}")
        return b64_str

def _is_valid_mp4(data):
    if not data or len(data) < 500:
        return False
    return b'ftyp' in data[:100]

def _send_video_safe(chat_id, data, caption="✅ Ваше видео готово!"):
    try:
        video_file = io.BytesIO(data)
        video_file.name = "video.mp4"
        bot.send_video(
            chat_id,
            video_file,
            caption=caption,
            supports_streaming=True,
            timeout=120
        )
        logging.info(f"Видео отправлено в чат {chat_id}")
        return True
    except Exception as e:
        logging.error(f"Ошибка send_video: {e}")
        try:
            doc_file = io.BytesIO(data)
            doc_file.name = "video.mp4"
            bot.send_document(chat_id, doc_file, caption="✅ Видео (как файл)")
            return True
        except Exception as e2:
            logging.error(f"Ошибка send_document: {e2}")
            bot.send_message(chat_id, "❌ Видео сгенерировано, но не удалось отправить файл.")
            return False

def poll_video_task(polling_url, headers, chat_id, max_attempts=90, interval=10):
    logging.info(f"Начинаю опрос: {polling_url} для chat_id={chat_id}")
    for attempt in range(1, max_attempts + 1):
        time.sleep(interval)
        try:
            resp = requests.get(polling_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                logging.error(f"Опрос: статус {resp.status_code}, тело: {resp.text[:200]}")
                continue

            data = resp.json()
            status = data.get("status")
            logging.info(f"Опрос {attempt}: статус={status}")

            if status == "completed":
                job_id = polling_url.split('/')[-1]

                unsigned_urls = data.get("unsigned_urls", [])
                if unsigned_urls:
                    video_url = unsigned_urls[0]
                    logging.info(f"Скачиваю по unsigned_url: {video_url[:80]}...")
                    try:
                        video_resp = requests.get(video_url, timeout=60, allow_redirects=True)
                        ct = video_resp.headers.get('Content-Type', 'unknown')
                        logging.info(f"unsigned_url: статус {video_resp.status_code}, "
                                     f"размер {len(video_resp.content)}, Content-Type: {ct}")
                        if video_resp.status_code == 200 and _is_valid_mp4(video_resp.content):
                            _send_video_safe(chat_id, video_resp.content)
                            return
                        else:
                            logging.warning(f"unsigned_url вернул невалидный MP4. "
                                          f"Первые 50 байт: {video_resp.content[:50].hex()}")
                    except Exception as e:
                        logging.error(f"Ошибка скачивания unsigned_url: {e}")

                content_url = f"https://openrouter.ai/api/v1/videos/{job_id}/content"
                logging.info(f"Скачиваю через /content: {content_url}")
                try:
                    video_resp = requests.get(content_url, headers=headers, timeout=60)
                    ct = video_resp.headers.get('Content-Type', 'unknown')
                    logging.info(f"/content: статус {video_resp.status_code}, "
                                 f"размер {len(video_resp.content)}, Content-Type: {ct}")
                    if video_resp.status_code == 200 and _is_valid_mp4(video_resp.content):
                        _send_video_safe(chat_id, video_resp.content)
                        return
                    else:
                        logging.error(f"/content вернул невалидный MP4. "
                                      f"Первые 50 байт: {video_resp.content[:50].hex()}")
                except Exception as e:
                    logging.error(f"Ошибка скачивания /content: {e}")

                bot.send_message(chat_id, "❌ Видео сгенерировано, но файл повреждён или пустой.")
                return

            elif status in ["failed", "cancelled", "expired"]:
                logging.error(f"Задача провалена: {data}")
                bot.send_message(chat_id, f"❌ Ошибка генерации видео: {status}")
                return
            else:
                logging.info(f"В процессе: {status}")

        except Exception as e:
            logging.error(f"Ошибка опроса: {e}")

    bot.send_message(chat_id, "❌ Время ожидания истекло (более 15 минут).")

def _handle_video_error(chat_id, status_code, error_body):
    """Отправляет пользователю понятное сообщение об ошибке."""
    if status_code == 400 and "InputImageSensitiveContentDetected" in error_body:
        bot.send_message(chat_id, "❌ Модель отклонила изображение: на нём обнаружено лицо реального человека. "
                                   "Попробуйте использовать изображение без реальных людей.")
        return
    # Общее сообщение
    err_msg = f"❌ Не удалось запустить генерацию видео. Код ошибки: {status_code}"
    if error_body:
        err_msg += f" ({error_body[:200]})"
    bot.send_message(chat_id, err_msg)

def generate_video_seedance_async(chat_id, prompt, first_frame_b64=None, last_frame_b64=None):
    params = user_video_params.get(chat_id, {})
    duration = params.get('duration', 5)
    resolution = params.get('resolution', '480p')
    audio = params.get('audio', True)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot"
    }
    models_to_try = ["bytedance/seedance-2.0", "bytedance/seedance-2.0-fast"]

    for model in models_to_try:
        logging.info(f"Пробую модель {model} для chat_id={chat_id} с параметрами: duration={duration}, resolution={resolution}, audio={audio}")
        payload = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": "16:9",
            "audio": audio
        }

        frame_images = []
        if first_frame_b64:
            compressed = compress_image_if_needed(first_frame_b64)
            frame_images.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{compressed}"},
                "frame_type": "first_frame"
            })
        if last_frame_b64:
            compressed = compress_image_if_needed(last_frame_b64)
            frame_images.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{compressed}"},
                "frame_type": "last_frame"
            })
        if frame_images:
            payload["frame_images"] = frame_images

        safe = {k: v for k, v in payload.items()}
        if "frame_images" in safe:
            safe["frame_images"] = [
                {**item, "image_url": {"url": "<base64>"}} for item in safe["frame_images"]
            ]
        logging.info(f"Payload: {json.dumps(safe, ensure_ascii=False)}")

        try:
            resp = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
            logging.info(f"{model}: HTTP {resp.status_code}")
            logging.info(f"{model}: ответ: {resp.text[:500]}")

            if resp.status_code not in (200, 202):
                # Проверим на специфическую ошибку контента
                if resp.status_code == 400 and "InputImageSensitiveContentDetected" in resp.text:
                    _handle_video_error(chat_id, resp.status_code, resp.text)
                    return False
                # Иначе просто запишем и попробуем следующую модель
                logging.error(f"Ошибка {resp.status_code}: {resp.text[:300]}")
                continue

            data = resp.json()

            if "polling_url" in data:
                Thread(target=poll_video_task,
                       args=(data["polling_url"], headers, chat_id),
                       daemon=True).start()
                return True

            if "unsigned_urls" in data and data["unsigned_urls"]:
                video_url = data["unsigned_urls"][0]
                video_resp = requests.get(video_url, timeout=60, allow_redirects=True)
                if video_resp.status_code == 200 and _is_valid_mp4(video_resp.content):
                    _send_video_safe(chat_id, video_resp.content)
                    return True

            if "b64_json" in data:
                try:
                    raw = base64.b64decode(data["b64_json"])
                    if _is_valid_mp4(raw):
                        _send_video_safe(chat_id, raw)
                        return True
                except Exception:
                    pass

            logging.warning("Нет polling_url, пробую следующую модель...")

        except Exception as e:
            logging.error(f"Исключение при запросе к {model}: {e}")

    # Если все модели провалились, но специфическая ошибка не сработала, показываем общую
    _handle_video_error(chat_id, 0, "Все доступные видеомодели не смогли обработать запрос.")
    return False

# ================== 5. КЛАВИАТУРЫ ДЛЯ ПАРАМЕТРОВ ==================
def video_params_keyboard(chat_id):
    params = user_video_params.get(chat_id, {})
    duration = params.get('duration', 5)
    resolution = params.get('resolution', '480p')
    audio = params.get('audio', True)

    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton(f"{'✅' if duration==5 else '⬜'} 5 сек", callback_data="vid_dur_5"),
        InlineKeyboardButton(f"{'✅' if duration==10 else '⬜'} 10 сек", callback_data="vid_dur_10"),
        InlineKeyboardButton(f"{'✅' if duration==15 else '⬜'} 15 сек", callback_data="vid_dur_15")
    )
    markup.add(
        InlineKeyboardButton(f"{'✅' if resolution=='480p' else '⬜'} 480p", callback_data="vid_res_480p"),
        InlineKeyboardButton(f"{'✅' if resolution=='720p' else '⬜'} 720p", callback_data="vid_res_720p"),
        InlineKeyboardButton(f"{'✅' if resolution=='1080p' else '⬜'} 1080p", callback_data="vid_res_1080p")
    )
    markup.add(
        InlineKeyboardButton(f"{'✅' if audio else '⬜'} Со звуком", callback_data="vid_audio_true"),
        InlineKeyboardButton(f"{'✅' if not audio else '⬜'} Без звука", callback_data="vid_audio_false")
    )
    markup.add(InlineKeyboardButton("✅ Готово, продолжить", callback_data="vid_params_done"))
    return markup

def start_video_param_selection(chat_id):
    user_video_params[chat_id] = user_video_params.get(chat_id, {})
    text = "Настройте параметры видео, затем нажмите «Готово»:"
    bot.send_message(chat_id, text, reply_markup=video_params_keyboard(chat_id))

# ================== 6. ГЛАВНОЕ МЕНЮ ==================
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

# ================== 7. ОБРАБОТЧИКИ ==================
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
    user_video_frames.pop(message.chat.id, None)
    user_video_params.pop(message.chat.id, None)
    user_video_mode.pop(message.chat.id, None)
    send_main_menu(message.chat.id)

# --- Колбэки для параметров видео (СПЕЦИФИЧНЫЕ) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('vid_dur_'))
def set_video_duration(call):
    chat_id = call.message.chat.id
    duration = int(call.data.split('_')[-1])
    user_video_params[chat_id]['duration'] = duration
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Длительность: {duration} сек")

@bot.callback_query_handler(func=lambda call: call.data.startswith('vid_res_'))
def set_video_resolution(call):
    chat_id = call.message.chat.id
    resolution = call.data.split('_')[-1]
    user_video_params[chat_id]['resolution'] = resolution
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Разрешение: {resolution}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('vid_audio_'))
def set_video_audio(call):
    chat_id = call.message.chat.id
    audio = call.data.split('_')[-1] == 'true'
    user_video_params[chat_id]['audio'] = audio
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Звук: {'включён' if audio else 'выключен'}")

@bot.callback_query_handler(func=lambda call: call.data == 'vid_params_done')
def video_params_done(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, call.message.message_id)
    params = user_video_params.get(chat_id, {})
    if 'duration' not in params:
        params['duration'] = 5
    if 'resolution' not in params:
        params['resolution'] = '480p'
    if 'audio' not in params:
        params['audio'] = True
    user_video_params[chat_id] = params

    user_state[chat_id] = "awaiting_video_prompt"
    bot.send_message(chat_id, "✏️ Теперь введите описание (промпт) для видео:", reply_markup=back_keyboard())
    bot.answer_callback_query(call.id)

# --- Колбэк выбора режима видео (только для конкретных значений) ---
@bot.callback_query_handler(func=lambda call: call.data in ('vid_text', 'vid_image'))
def select_video_mode(call):
    chat_id = call.message.chat.id
    data = call.data

    if data == 'vid_text':
        user_video_mode[chat_id] = 'text'
        user_video_frames[chat_id] = {'first': None, 'last': None}
        bot.delete_message(chat_id, call.message.message_id)
        start_video_param_selection(chat_id)

    elif data == 'vid_image':
        user_video_mode[chat_id] = 'image_one'
        user_video_frames[chat_id] = {'first': None, 'last': None}
        user_state[chat_id] = "awaiting_video_image_first"
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "📸 Загрузи ПЕРВЫЙ кадр (начальное изображение):", reply_markup=back_keyboard())

    bot.answer_callback_query(call.id)

# --- Колбэки для выбора модели генерации изображений ---
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

# --- Обработка загрузки кадров для видео ---
@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_first")
def handle_video_first_frame(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode('utf-8')
    user_video_frames[chat_id]['first'] = b64
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
        user_state[chat_id] = "awaiting_video_image_last"
        bot.send_message(chat_id, "📸 Загрузи ПОСЛЕДНИЙ кадр:", reply_markup=back_keyboard())
    else:
        user_state[chat_id] = None
        start_video_param_selection(chat_id)
    bot.answer_callback_query(call.id)

@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_last")
def handle_video_last_frame(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode('utf-8')
    user_video_frames[chat_id]['last'] = b64
    user_state[chat_id] = None
    start_video_param_selection(chat_id)

# --- Генерация изображений ---
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

# --- Редактирование фото ---
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

# --- ФИНАЛЬНАЯ ГЕНЕРАЦИЯ ВИДЕО ---
@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_prompt")
def handle_video_prompt(message):
    chat_id = message.chat.id
    prompt = message.text
    user_state[chat_id] = None

    logging.info(f"=== НАЧАЛО ГЕНЕРАЦИИ ВИДЕО для {chat_id} ===")
    logging.info(f"Промт: {prompt}")
    first_frame = user_video_frames.get(chat_id, {}).get('first')
    last_frame = user_video_frames.get(chat_id, {}).get('last')

    bot.send_message(chat_id, "🎬 Генерирую видео... Это может занять до 15 минут. Я пришлю его, когда оно будет готово.")

    Thread(target=generate_video_seedance_async, args=(chat_id, prompt, first_frame, last_frame), daemon=True).start()

# --- Чат ---
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

# ================== 8. ЗАПУСК ==================
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
