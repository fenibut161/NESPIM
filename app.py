import os
import sys
import telebot
import requests
import time
import base64
import urllib3
import urllib.parse
import json
import logging
import re
import xml.etree.ElementTree as ET
from html import escape, unescape
from flask import Flask, request, send_from_directory, jsonify
from threading import Thread, RLock
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, WebAppInfo
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
user_chat_history = defaultdict(list)

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

# --- TELEGRAM WEB APP HTML TEMPLATE ---
WEBAPP_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <title>Kling 3.0 Studio</title>
    <style>
        :root {
            --bg-color: var(--tg-theme-bg-color, #18181b);
            --text-color: var(--tg-theme-text-color, #ffffff);
            --hint-color: var(--tg-theme-hint-color, #9ca3af);
            --btn-color: var(--tg-theme-button-color, #3b82f6);
            --btn-text: var(--tg-theme-button-text-color, #ffffff);
            --sec-bg: var(--tg-theme-secondary-bg-color, #27272a);
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color); color: var(--text-color); margin: 0; padding: 16px; padding-bottom: 95px;
        }
        .header { text-align: center; margin-bottom: 18px; }
        .header h1 { font-size: 20px; margin: 0; font-weight: 700; }
        .header p { font-size: 13px; color: var(--hint-color); margin: 4px 0 0 0; }
        .card { background: var(--sec-bg); border-radius: 16px; padding: 16px; margin-bottom: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .card-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .aspect-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
        .aspect-btn {
            background: rgba(255,255,255,0.05); border: 2px solid transparent; color: var(--text-color);
            padding: 10px; border-radius: 12px; text-align: center; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.2s;
        }
        .aspect-btn.active { border-color: var(--btn-color); background: rgba(59, 130, 246, 0.15); }
        
        .scene-block { background: rgba(0,0,0,0.25); border-radius: 14px; padding: 14px; margin-bottom: 14px; border: 1px solid rgba(255,255,255,0.05); }
        .scene-head { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; margin-bottom: 10px; }
        .scene-del { color: #ef4444; font-size: 12px; cursor: pointer; padding: 4px; }
        
        textarea {
            width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px; color: var(--text-color); padding: 10px; font-size: 14px; resize: none; height: 60px; outline: none; margin-bottom: 10px;
        }
        textarea:focus { border-color: var(--btn-color); }
        
        .scene-img-box {
            border: 1px dashed rgba(255,255,255,0.2); border-radius: 10px; padding: 10px; text-align: center; cursor: pointer;
            background: rgba(255,255,255,0.02); transition: all 0.2s; position: relative; overflow: hidden; min-height: 36px;
            display: flex; align-items: center; justify-content: center;
        }
        .scene-img-box:hover { border-color: var(--btn-color); }
        .scene-img-box img { max-height: 120px; border-radius: 6px; object-fit: contain; }
        .empty-hint { font-size: 12px; color: var(--hint-color); display: flex; align-items: center; gap: 6px; }
        .del-img-badge {
            position: absolute; top: 6px; right: 6px; background: rgba(239, 68, 68, 0.9); color: #fff;
            border-radius: 50%; width: 22px; height: 22px; font-size: 12px; display: flex; align-items: center; justify-content: center; cursor: pointer;
        }

        .dur-row { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; font-size: 13px; color: var(--hint-color); }
        input[type="range"] { accent-color: var(--btn-color); width: 58%; }
        .sec-num { font-weight: 700; color: #3b82f6; width: 32px; text-align: right; }
        
        .add-scene-btn { width: 100%; padding: 14px; background: rgba(255,255,255,0.08); border: none; border-radius: 12px; color: var(--text-color); font-weight: 600; font-size: 14px; cursor: pointer; }
        .main-btn {
            position: fixed; bottom: 16px; left: 16px; right: 16px; background: var(--btn-color); color: var(--btn-text);
            border: none; padding: 16px; border-radius: 14px; font-size: 15px; font-weight: 700; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.4); cursor: pointer; text-align: center;
        }
        .main-btn:disabled { background: #52525b; color: #9ca3af; cursor: not-allowed; }
    </style>
</head>
<body>

<div class="header">
    <h1>✨ Kling 3.0 Studio</h1>
    <p>Покадровый конструктор фильма (до 18 секунд)</p>
</div>

<div class="card">
    <div class="card-title">Формат кадра</div>
    <div class="aspect-grid">
        <div class="aspect-btn active" onclick="setAspect('16:9', this)">🖥 16:9</div>
        <div class="aspect-btn" onclick="setAspect('9:16', this)">📱 9:16</div>
        <div class="aspect-btn" onclick="setAspect('1:1', this)">⬜ 1:1</div>
    </div>
</div>

<div class="card">
    <div class="card-title">
        <span>Сцены фильма (макс. 6)</span>
        <span style="font-size:13px; font-weight:700" id="totalSec">3с (15 🔷)</span>
    </div>
    <div id="scenesContainer"></div>
    <button class="add-scene-btn" onclick="addScene()" id="addBtn">+ Добавить следующий кадр</button>
</div>

<input type="file" id="hiddenFile" accept="image/*" style="display:none">
<button class="main-btn" id="submitBtn" onclick="submitStudio()">🚀 Запустить рендер (15 🔷)</button>

<script>
    const tg = window.Telegram.WebApp;
    tg.ready(); tg.expand();

    let currentAspect = '16:9';
    let activeUploadIdx = null;
    let scenes = [{ prompt: '', dur: 3, photo: null }];
    const MAX_KLING_SEC = 18;

    function renderScenes() {
        const cont = document.getElementById('scenesContainer');
        cont.innerHTML = '';
        scenes.forEach((sc, idx) => {
            let imgHtml = sc.photo 
                ? `<img src="data:image/jpeg;base64,${sc.photo}"><div class="del-img-badge" onclick="event.stopPropagation(); removePhoto(${idx})">✕</div>`
                : `<div class="empty-hint"><span style="font-size:16px">🖼</span> Прикрепить референс для Сцены ${idx+1}</div>`;

            cont.innerHTML += `
                <div class="scene-block">
                    <div class="scene-head">
                        <span>Сцена ${idx + 1}</span>
                        ${scenes.length > 1 ? `<span class="scene-del" onclick="delScene(${idx})">Удалить</span>` : ''}
                    </div>
                    <textarea placeholder="Что происходит в этой сцене..." oninput="scenes[${idx}].prompt = this.value">${sc.prompt}</textarea>
                    <div class="scene-img-box" onclick="triggerUpload(${idx})">${imgHtml}</div>
                    <div class="dur-row">
                        <span>Длительность:</span>
                        <input type="range" min="2" max="6" value="${sc.dur}" oninput="scenes[${idx}].dur = parseInt(this.value); this.nextElementSibling.innerText = this.value + 'с'; updateSummary()">
                        <span class="sec-num">${sc.dur}с</span>
                    </div>
                </div>
            `;
        });
        document.getElementById('addBtn').style.display = scenes.length >= 6 ? 'none' : 'block';
        updateSummary();
    }

    function addScene() { if (scenes.length < 6) { scenes.push({ prompt: '', dur: 3, photo: null }); renderScenes(); } }
    function delScene(i) { scenes.splice(i, 1); renderScenes(); }
    function setAspect(asp, el) {
        currentAspect = asp;
        document.querySelectorAll('.aspect-btn').forEach(b => b.classList.remove('active'));
        el.classList.add('active');
    }

    function triggerUpload(idx) {
        activeUploadIdx = idx;
        document.getElementById('hiddenFile').click();
    }

    function removePhoto(idx) {
        scenes[idx].photo = null;
        renderScenes();
    }

    document.getElementById('hiddenFile').addEventListener('change', async function(e) {
        if (e.target.files && e.target.files[0] && activeUploadIdx !== null) {
            const b64 = await compressImg(e.target.files[0]);
            scenes[activeUploadIdx].photo = b64;
            renderScenes();
        }
        e.target.value = '';
    });

    function compressImg(file) {
        return new Promise(res => {
            const r = new FileReader();
            r.onload = e => {
                const img = new Image();
                img.onload = () => {
                    const cvs = document.createElement('canvas');
                    let w = img.width, h = img.height, max = 800;
                    if (w > h && w > max) { h *= max / w; w = max; }
                    else if (h > max) { w *= max / h; h = max; }
                    cvs.width = w; cvs.height = h;
                    cvs.getContext('2d').drawImage(img, 0, 0, w, h);
                    res(cvs.toDataURL('image/jpeg', 0.8).split(',')[1]);
                };
                img.src = e.target.result;
            };
            r.readAsDataURL(file);
        });
    }

    function updateSummary() {
        const tot = scenes.reduce((a, b) => a + b.dur, 0);
        const btn = document.getElementById('submitBtn');
        const badge = document.getElementById('totalSec');

        if (tot > MAX_KLING_SEC) {
            badge.innerHTML = `<span style="color:#ef4444">⚠️ Лимит 18с! У вас ${tot}с</span>`;
            btn.disabled = true;
            btn.innerText = `⚠️ Уменьшите секунды (максимум 18с)`;
        } else {
            const cost = tot * 5;
            badge.innerHTML = `<span style="color:#3b82f6">${tot}с (${cost} 🔷)</span>`;
            btn.disabled = false;
            btn.innerText = `🚀 Запустить рендер фильма (${cost} 🔷)`;
        }
    }

    async function submitStudio() {
        if (scenes.some(s => s.prompt.trim().length === 0)) {
            tg.showAlert('Пожалуйста, заполните текстовое описание действия для каждой созданной сцены!');
            return;
        }
        const btn = document.getElementById('submitBtn');
        btn.disabled = true; btn.innerText = '⏳ Передача в студию...';

        const payload = {
            user_id: tg.initDataUnsafe?.user?.id || 0,
            scenes: scenes,
            aspect_ratio: currentAspect
        };

        try {
            const r = await fetch('/api/webapp_submit_video', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const res = await r.json();
            if (res.ok) tg.close();
            else { tg.showAlert('Ошибка: ' + res.error); btn.disabled = false; updateSummary(); }
        } catch(e) { tg.showAlert('Ошибка связи с сервером бота'); btn.disabled = false; updateSummary(); }
    }

    renderScenes();
</script>
</body>
</html>
"""

# --- GIST SYNC ---
def load_data():
    global user_credits, user_credit_history, user_message_count, user_last_activity, user_chat_history
    data = None
    source = "fresh"

    if GIST_ID and GITHUB_TOKEN:
        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        try:
            r = requests.get(url, headers=headers, timeout=15)
            logging.info(f"[LOAD] Gist GET {r.status_code}")
            if r.status_code == 200:
                gist_data = r.json()
                content = gist_data["files"]["bot_data.json"]["content"]
                data = json.loads(content)
                if data and isinstance(data, dict):
                    source = "Gist"
        except Exception as e:
            logging.error(f"[LOAD] Gist exception: {e}")

    if data is None:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                source = "local file"
        except Exception:
            data = {}

    user_credits = defaultdict(int, {int(k): v for k, v in data.get("credits", {}).items()})
    user_credit_history = defaultdict(list, {int(k): v for k, v in data.get("history", {}).items()})
    user_message_count = defaultdict(int, {int(k): v for k, v in data.get("messages", {}).items()})
    user_last_activity = defaultdict(float, {int(k): v for k, v in data.get("last_activity", {}).items()})
    user_chat_history = defaultdict(list, {int(k): v for k, v in data.get("chat_history", {}).items()})
    logging.info(f"[LOAD] Final state from {source}: {sum(user_credits.values())} total credits")

def save_data():
    with data_lock:
        snapshot = {
            "credits": dict(user_credits),
            "history": dict(user_credit_history),
            "messages": dict(user_message_count),
            "last_activity": dict(user_last_activity),
            "chat_history": dict(user_chat_history),
        }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[SAVE LOCAL] {e}")

    if GIST_ID and GITHUB_TOKEN:
        def _async_gist():
            try:
                url = f"https://api.github.com/gists/{GIST_ID}"
                headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
                payload = {"files": {"bot_data.json": {"content": json.dumps(snapshot, ensure_ascii=False, indent=2)}}}
                requests.patch(url, json=payload, headers=headers, timeout=20)
            except Exception as e:
                logging.error(f"[SAVE GIST ASYNC ERR] {e}")
        Thread(target=_async_gist, daemon=True).start()

load_data()

bot = telebot.TeleBot(TELEGRAM_TOKEN)
bot.request_timeout = 120
app = Flask(__name__)

os.makedirs("static", exist_ok=True)

VIDEO_MODEL_FEATURES = {
    "bytedance/seedance-2.0": {"audio": True, "resolution": True},
    "kwaivgi/kling-video-o1": {"audio": True, "resolution": True},
    "kwaivgi/kling-v3.0-pro": {"audio": True, "resolution": True, "multi_prompt": True, "references": True},
}

PACKAGES = {
    "start": {"name": "Старт", "credits": 50, "price_stars": 250, "price_rub": 400, "desc": "50 🔷 на любые операции"},
    "optima": {"name": "Оптима", "credits": 150, "price_stars": 625, "price_rub": 1000, "desc": "150 🔷 (выгоднее)"},
    "maxi": {"name": "Макси", "credits": 400, "price_stars": 1500, "price_rub": 2400, "desc": "400 🔷 (максимальная выгода)"},
}

CREDIT_COSTS = {
    "image_pro": 2,
    "edit_pro": 3,
    "video": {5: 25, 10: 50, 15: 75},
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
# ИСПРАВЛЕНО: DuckDuckGo Lite теперь основной источник (стабильнее для ботов)
def helper_web_search(query):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://lite.duckduckgo.com/",
        }
        items = []

        # 1. DuckDuckGo Lite (primary)
        try:
            url = "https://lite.duckduckgo.com/lite/"
            r = requests.post(url, data={"q": query, "kl": "ru-ru"}, headers=headers, timeout=15)
            if r.status_code == 200:
                text = r.text
                # Parse result blocks: link + snippet
                rows = re.findall(
                    r'<a[^>]+class="result-link"[^>]*>(.*?)</a>.*?<td[^>]+class="result-snippet"[^>]*>(.*?)</td>',
                    text, re.DOTALL | re.IGNORECASE
                )
                for row in rows[:6]:
                    t = re.sub(r'<.*?>', '', row[0]).strip()
                    s = re.sub(r'<.*?>', '', row[1]).strip()
                    if t or s:
                        items.append(f"{t}: {s}" if t and s else (t or s))
        except Exception as e:
            logging.warning(f"DDG Lite error: {e}")

        # 2. DuckDuckGo HTML fallback
        if len(items) < 2:
            try:
                url = "https://html.duckduckgo.com/html/"
                r = requests.post(url, data={"q": query, "kl": "ru-ru"}, headers=headers, timeout=15)
                if r.status_code == 200:
                    text = r.text
                    titles = re.findall(r'<a[^>]+class="result__a"[^>]*>(.*?)</a>', text, re.DOTALL)
                    snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
                    for i in range(min(len(titles), len(snippets), 5)):
                        t = re.sub(r'<.*?>', '', titles[i]).strip()
                        s = re.sub(r'<.*?>', '', snippets[i]).strip()
                        if t or s and not any(t in it for it in items):
                            items.append(f"{t}: {s}" if t and s else (t or s))
            except Exception as e:
                logging.warning(f"DDG HTML fallback error: {e}")

        # 3. Google News RSS (news-only fallback)
        if len(items) < 2:
            try:
                rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ru&gl=RU&ceid=RU:ru"
                r = requests.get(rss_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    root = ET.fromstring(r.content)
                    for item in root.findall(".//item")[:3]:
                        title = item.find("title").text if item.find("title") is not None else ""
                        if title:
                            items.append(f"Новость: {title}")
            except Exception:
                pass

        return items if items else ["Поиск не дал результатов. Попробуйте уточнить запрос."]
    except Exception as e:
        return [f"Ошибка поиска: {e}"]

def helper_fetch_webpage(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
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
            "description": "Поиск актуальных новостей, фактов, документации или информации в интернете",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Точный поисковый запрос на русском или английском"}
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
            "name": "generate_multiscene_video",
            "description": "Снять кинематографичный многосценовый видеоролик Kling 3.0 Pro со звуком (5 🔷/сек).",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string", "description": "Описание действия в конкретном кадре"},
                                "duration": {"type": "integer", "description": "Секунды (от 2 до 6)"}
                            },
                            "required": ["prompt", "duration"]
                        }
                    },
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1"]},
                    "confirmed_by_user": {"type": "boolean"}
                },
                "required": ["scenes", "aspect_ratio", "confirmed_by_user"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_balance",
            "description": "Проверить текущий баланс токенов 🔷 пользователя",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_memory",
            "description": "Очистить память диалога с пользователем",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# ================== DEEPSEEK AGENT CORE ==================
# ИСПРАВЛЕНО: добавлены fallback-парсинги JSON из markdown и inline JSON,
# а также нативный tool_calls из OpenRouter
def extract_deepseek_tools(choice_msg):
    # 1. Native OpenAI format (OpenRouter standard)
    if choice_msg.get("tool_calls"):
        return choice_msg["tool_calls"], choice_msg.get("content", "")

    content = choice_msg.get("content", "")
    if not content:
        return None, ""

    # 2. DeepSeek XML-like format in content
    if "<｜tool" in content or "<|tool" in content:
        unified = content.replace("<|", "<｜").replace("|>", "｜>")
        pattern = r'<｜tool▁call▁begin｜>function<｜tool▁sep｜>(\w+)\s*\n?(\{.*?\})<｜tool▁call▁end｜>'
        raw_matches = re.findall(pattern, unified, re.DOTALL)
        if not raw_matches:
            pattern2 = r'<｜tool▁sep｜>(\w+)(?:\s*\n?)([\s\S]*?)(?:<｜tool▁call▁end｜>|<｜tool▁calls▁end｜>|$)'
            raw_matches = re.findall(pattern2, unified, re.DOTALL)

        t_calls = []
        for fn_name, arg_str in raw_matches:
            fn_name = fn_name.strip()
            arg_str = arg_str.strip()
            if not arg_str.startswith("{"):
                json_match = re.search(r'(\{.*\})', arg_str, re.DOTALL)
                if json_match:
                    arg_str = json_match.group(1)
            t_calls.append({
                "id": f"call_{int(time.time()*1000)}_{len(t_calls)}",
                "type": "function",
                "function": {"name": fn_name, "arguments": arg_str}
            })
        if t_calls:
            clean_text = unified.split("<｜tool")[0].strip()
            clean_text = re.sub(r"\b(попис|минут|секун|поиск|созда|арт|функц)$", "", clean_text).strip()
            return t_calls, clean_text

    # 3. Fallback: JSON inside markdown code block (```json ... ```)
    md_json = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content, re.DOTALL)
    if md_json:
        try:
            data = json.loads(md_json.group(1))
            if "name" in data and "arguments" in data:
                tc = {
                    "id": f"call_{int(time.time()*1000)}",
                    "type": "function",
                    "function": {
                        "name": data["name"],
                        "arguments": json.dumps(data["arguments"], ensure_ascii=False)
                    }
                }
                clean = content[:md_json.start()].strip()
                return [tc], clean
        except Exception:
            pass

    # 4. Fallback: inline JSON object with name+arguments
    inline = re.search(r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{[\s\S]*?\})\s*\}', content, re.DOTALL)
    if inline:
        try:
            tc = {
                "id": f"call_{int(time.time()*1000)}",
                "type": "function",
                "function": {"name": inline.group(1), "arguments": inline.group(2)}
            }
            return [tc], content[:inline.start()].strip()
        except Exception:
            pass

    return None, content

def ask_deepseek(prompt):
    headers = _build_headers()
    payload = {"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"DeepSeek exception: {e}")
    return "⚠️ Ошибка соединения"

# ИСПРАВЛЕНО: добавлен tool_choice: "auto", parallel_tool_calls: False,
# усилен system prompt, добавлено логирование raw-ответа
def run_agent(chat_id, user_text):
    history = list(user_chat_history.get(chat_id, []))
    if len(history) > 20:
        history = history[-18:]

    system_prompt = (
        "Ты — персональный ИИ-агент NESPIM в Telegram. У тебя есть инструменты (functions/tools).\n"
        "ПРАВИЛО №1: Если пользователь спрашивает о событиях после 2024 года, погоду, курсы валют, "
        "новости, спортивные результаты, актуальные факты или что-то, что могло измениться за последние месяцы — "
        "ты ОБЯЗАН вызвать функцию web_search. Не отвечай из своей памяти на актуальные вопросы.\n"
        "ПРАВИЛО №2: Если пользователь прислал ссылку — вызови fetch_webpage ровно один раз.\n"
        "ПРАВИЛО №3: Если пользователь просит картинку ('нарисуй', 'арт', 'сгенерируй изображение') — "
        "вызови generate_image немедленно. aspect_ratio по умолчанию '16:9'.\n"
        "ПРАВИЛО №4: Для видео сначала предложи сценарий, посчитай стоимость (5 🔷/сек), спроси подтверждение. "
        "Только потом generate_multiscene_video с confirmed_by_user=True.\n"
        "ПРАВИЛО №5: Делай СТРОГО НЕ БОЛЕЕ ОДНОГО вызова инструмента за раз. Получив результат — сразу формируй финальный ответ.\n"
        "ПРАВИЛО №6: Отвечай понятно, емко, на русском языке.\n\n"
        "Доступные инструменты:\n"
        "• web_search — поиск в интернете (Google/DuckDuckgo). Используй для актуальной информации.\n"
        "• fetch_webpage — чтение ссылок.\n"
        "• generate_image — генерация картинки (2 🔷).\n"
        "• generate_multiscene_video — видео Kling 3.0 Pro (5 🔷/сек).\n"
        "• get_my_balance — баланс токенов.\n"
        "• clear_memory — очистить историю диалога."
    )

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]
    headers = _build_headers()

    for turn in range(4):
        payload = {
            "model": "deepseek/deepseek-chat",
            "messages": messages,
            "tools": AGENT_TOOLS,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        try:
            r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
            if r.status_code != 200:
                return f"⚠️ Ошибка OpenRouter: {r.status_code}"

            data = r.json()
            if "error" in data:
                return f"❌ Ошибка API: {data['error'].get('message', 'limit')}"

            choice_msg = data["choices"][0]["message"]
            
            # ИСПРАВЛЕНО: логируем raw-ответ для отладки
            logging.info(f"[AGENT RAW] {json.dumps(choice_msg, ensure_ascii=False)[:800]}")

            tool_calls, clean_content = extract_deepseek_tools(choice_msg)

            if tool_calls:
                choice_msg["content"] = clean_content
                choice_msg["tool_calls"] = tool_calls
                messages.append(choice_msg)

                for tc in tool_calls:
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
                    elif fn_name == "generate_multiscene_video":
                        scenes = args.get("scenes", [])
                        asp = args.get("aspect_ratio", "16:9")
                        is_confirmed = args.get("confirmed_by_user", False)
                        total_d = sum(s.get("duration", 3) for s in scenes)
                        cost = total_d * 5

                        if not is_confirmed:
                            res_content = (
                                f"СТОП! Правило безопасности платформы: вы НЕ можете запустить рендер видео без подтверждения юзером! "
                                f"Выведи юзеру этот режиссерский сценарий (общая длительность {total_d} сек, цена {cost} 🔷) "
                                f"и спроси его: 'Запускаем видеоролик в производство?'."
                            )
                        else:
                            can_gen = False
                            with data_lock:
                                if chat_id == ADMIN_ID or user_credits.get(chat_id, 0) >= cost:
                                    if chat_id != ADMIN_ID:
                                        user_credits[chat_id] -= cost
                                        user_credit_history[chat_id].append((time.time(), -cost, f"Агент: видео {total_d}с"))
                                        save_data()
                                    can_gen = True

                            if not can_gen:
                                res_content = f"Недостаточно 🔷. Нужно {cost}, баланс {user_credits.get(chat_id, 0)}."
                            else:
                                bot.send_message(chat_id, f"🎬 Принято! Агент отправляет сценарий в Kling 3.0 Pro ({total_d} сек)...")
                                user_video_model[chat_id] = "kwaivgi/kling-v3.0-pro"
                                user_video_params[chat_id] = {"duration": total_d, "aspect_ratio": asp, "audio": True, "resolution": "720p"}
                                Thread(target=generate_video_async, args=(chat_id, None, None, None, scenes), daemon=True).start()
                                res_content = "Генерация многосценового видео успешно запущена в фоновом потоке."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": fn_name,
                        "content": str(res_content)
                    })
            else:
                final_text = choice_msg.get("content", "")
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": final_text})
                user_chat_history[chat_id] = history[-20:]
                return final_text
        except Exception as e:
            logging.error(f"[AGENT EXCEPTION] {e}")
            return "⚠️ Произошла ошибка при работе ИИ-агента."

    return "⚠️ Поиск не дал однозначного ответа."

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
        if "error" in data:
            return None, data["error"].get("message", "OpenRouter Error")
        msg = data["choices"][0]["message"]
        if "images" in msg and msg["images"]:
            img_url = msg["images"][0]["image_url"]["url"]
        elif msg.get("content", "").startswith("data:image/"):
            img_url = msg["content"]
        elif msg.get("content", ""):
            content = msg["content"]
            url_match = re.search(r'(https?://\S+\.(?:jpg|jpeg|png|webp|gif))', content, re.IGNORECASE)
            if url_match:
                img_url = url_match.group(1)
                return requests.get(img_url, timeout=30).content, None
            elif content.startswith("data:image/"):
                img_url = content
            else:
                return None, f"Нет изображения в ответе. Ответ: {content[:200]}"
        else:
            return None, "Нет изображения в ответе"
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

def generate_video_async(chat_id, prompt=None, first_frame_b64=None, last_frame_b64=None, multi_prompt=None, multi_photos_b64=None):
    params = user_video_params.get(chat_id, {})
    duration = params.get("duration", 5)
    cost = duration * 5

    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Недостаточно 🔷. Нужно {cost}, у вас {user_credits.get(chat_id, 0)}. Пополните баланс в магазине 💰.")
                return False
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Видео {duration}с"))
            save_data()
        bot.send_message(chat_id, f"✅ Списано {cost} 🔷. Осталось: {user_credits[chat_id]}")

    resolution = params.get("resolution", "480p")
    audio = params.get("audio", True)
    aspect = params.get("aspect_ratio", "16:9")
    model_id = user_video_model.get(chat_id, "bytedance/seedance-2.0")

    model_names = {
        "bytedance/seedance-2.0": "Seedance 2.0",
        "kwaivgi/kling-video-o1": "Kling O1",
        "kwaivgi/kling-v3.0-pro": "Kling 3.0 Pro",
    }
    model_display = model_names.get(model_id, model_id)
    headers = _build_headers()
    payload = {"model": model_id, "duration": duration, "aspect_ratio": aspect}

    frame_images = []

    if multi_prompt:
        clean_mp = []
        for idx, item in enumerate(multi_prompt):
            sc_dict = {"prompt": item.get("prompt", ""), "duration": int(item.get("duration", 3))}
            if item.get("photo"):
                d_url = f"data:image/jpeg;base64,{compress_image_if_needed(item['photo'])}"
                sc_dict["image"] = d_url
                f_type = "first_frame" if idx == 0 else ("last_frame" if idx == len(multi_prompt)-1 else "reference")
                frame_images.append({"type": "image_url", "image_url": {"url": d_url}, "frame_type": f_type})
            clean_mp.append(sc_dict)
        payload["multi_prompt"] = clean_mp
        model_display += " [Мультисцена Studio]"
    elif prompt:
        payload["prompt"] = prompt
        if multi_photos_b64 and isinstance(multi_photos_b64, list):
            for idx, b64 in enumerate(multi_photos_b64[:9]):
                d_url = f"data:image/jpeg;base64,{compress_image_if_needed(b64)}"
                f_type = "first_frame" if idx == 0 else ("last_frame" if idx == len(multi_photos_b64)-1 and len(multi_photos_b64)>1 else "reference")
                frame_images.append({"type": "image_url", "image_url": {"url": d_url}, "frame_type": f_type})
        else:
            if first_frame_b64:
                d_url = f"data:image/jpeg;base64,{compress_image_if_needed(first_frame_b64)}"
                frame_images.append({"type": "image_url", "image_url": {"url": d_url}, "frame_type": "first_frame"})
            if last_frame_b64:
                d_url = f"data:image/jpeg;base64,{compress_image_if_needed(last_frame_b64)}"
                frame_images.append({"type": "image_url", "image_url": {"url": d_url}, "frame_type": "last_frame"})

    features = VIDEO_MODEL_FEATURES.get(model_id, {})
    if features.get("resolution"):
        payload["resolution"] = resolution
    if features.get("audio"):
        payload["audio"] = audio
    if frame_images:
        payload["frame_images"] = frame_images

    logging.info(f"Video payload: {json.dumps({k: v for k, v in payload.items() if k != 'frame_images'}, ensure_ascii=False)}")
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
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🌱 Seedance 2.0", callback_data="vmodel_seedance-2.0"),
        InlineKeyboardButton("🎬 Kling O1", callback_data="vmodel_kling-o1"),
        InlineKeyboardButton("🎥 Kling 3.0 Pro", callback_data="vmodel_kling-pro"),
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
    text = f"👤 <b>Ваш профиль</b>\n\n💰 Баланс: {credits} 🔷\n\n"
    if history:
        text += "📋 <b>Последние операции:</b>\n"
        for ts, delta, reason in history[-5:]:
            sign = "+" if delta > 0 else ""
            text += f"{sign}{delta} 🔷 – {escape(reason)}\n"
    else:
        text += "📋 <b>Операций пока нет.</b>"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💳 Пополнить баланс", callback_data="goto_shop"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "goto_shop")
def goto_shop(call):
    bot.answer_callback_query(call.id)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    shop(call.message)

# ================== SHOP & HELP ==================
@bot.message_handler(func=lambda m: m.text == "💰 Магазин")
def shop(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    text = (
        "🛒 <b>Магазин токенов 🔷</b>\n"
        " 🔷 за токены приобретается:\n"
        "• Генерация (Flux/Seedream) — 2 🔷\n"
        "• Редактирование фото (Flux/Seedream) — 3 🔷\n"
        "• Видеоролики (Seedance / Kling Pro) — 5 🔷 за 1 сек\n"
        "• Чат с ИИ-агентом — 1 🔷 за 50 сообщений\n\n"
        "Выберите пакет:"
    )
    for key, pkg in PACKAGES.items():
        text += f"\n<b>{escape(pkg['name'])}</b>: {pkg['credits']} 🔷 — {pkg['price_stars']} ⭐️ / {pkg['price_rub']} ₽"
    bot.send_message(chat_id, text, parse_mode="HTML")
    markup = InlineKeyboardMarkup(row_width=2)
    for key, pkg in PACKAGES.items():
        markup.add(
            InlineKeyboardButton(f"{pkg['name']} ⭐️ {pkg['price_stars']}", callback_data=f"buy_stars_{key}"),
            InlineKeyboardButton(f"{pkg['name']} 💳 {pkg['price_rub']}₽", callback_data=f"buy_card_{key}"),
        )
    bot.send_message(chat_id, "Оплата Stars (Telegram) или перевод на карту:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "📖 Инструкция")
def menu_help(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    text = (
        "📖 <b>Руководство пользователя NESPIM</b>\n\n"
        "🤖 <b>1. Спросить (ИИ-Агент)</b>\n"
        "Твой умный ассистент. Он помнит контекст диалога, гуглит свежую информацию, читает ссылки и сам рисует арты или снимает трейлеры.\n"
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
        "• <b>Обычное видео</b> — анимация картинок или ролик по тексту.\n"
        "• <b>Визуальная Студия Kling 3.0 (Web App)</b> — покадровый конструктор! В каждую созданную сцену можно вставить свой референс картинки.\n"
        "💎 <b>Цена:</b> 5 🔷 за 1 секунду видео.\n\n"
        "💰 <b>5. Баланс и покупки</b>\n"
        "В «Профиле» виден остаток токенов. Пополнить баланс можно в «Магазине» за Telegram Stars ⭐️ мгновенно или переводом на карту.\n\n"
        "💡 <i>Если бот застрял или ждет фото, а вы передумали — просто нажмите кнопку «🔙 Главное меню» или отправьте /start.</i>"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")

# --- STARS PAYMENT ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_stars_"))
def initiate_stars_payment(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    pkg_key = call.data[10:]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
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
    bot.answer_callback_query(call.id, "Реквизиты отправлены")
    pkg_key = call.data[9:]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        return
    user = call.from_user
    username = f"@{user.username}" if user.username else "без username"
    bot.send_message(
        chat_id,
        f"💳 <b>Оплата картой — пакет «{pkg['name']}»</b>\n\n"
        f"Сумма: <b>{pkg['price_rub']} ₽</b>\n"
        f"Вы получите: <b>{pkg['credits']} 🔷</b>\n\n"
        f"Переведите сумму на Т-Банк / СБЕР по номеру:\n"
        f"<code>+79192329005</code>\n\n"
        f"❗️ <b>Укажите в комментарии к переводу ваш Telegram ID:</b>\n"
        f"<code>{chat_id}</code>\n\n"
        f"После перевода 🔷 начислятся вручную в течение 15 минут.",
        parse_mode="HTML",
    )
    try:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"✅ Начислить {pkg['credits']}🔷", callback_data=f"admin_grant_{chat_id}_{pkg_key}"))
        bot.send_message(
            ADMIN_ID,
            f"💳 <b>Запрос на оплату картой</b>\n\n"
            f"Пользователь: {username}\n"
            f"ID: <code>{chat_id}</code>\n"
            f"Пакет: <b>{pkg['name']}</b>\n"
            f"Сумма: {pkg['price_rub']} ₽\n"
            f"🔷: {pkg['credits']}",
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_grant_"))
def admin_grant_credits(call):
    bot.answer_callback_query(call.id)
    if call.from_user.id != ADMIN_ID:
        return
    parts = call.data.split("_")
    if len(parts) < 4:
        return
    target_id = int(parts[2])
    pkg_key = parts[3]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        return
    with data_lock:
        user_credits[target_id] = user_credits.get(target_id, 0) + pkg["credits"]
        user_credit_history[target_id].append((time.time(), pkg["credits"], f"Покупка пакета {pkg['name']} (карта)"))
        save_data()
    bot.edit_message_text(
        f"✅ <b>Начислено</b>\nПользователю {target_id}: +{pkg['credits']} 🔷",
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
        confirm_text = f"✅ Начислено {amt} 🔷 пользователю <code>{uid}</code>. Текущий баланс: {current_balance} 🔷"
        bot.send_message(message.chat.id, confirm_text, parse_mode="HTML")

        try:
            bot.send_message(uid, f"🎉 Администратор начислил вам {amt} 🔷.\nВаш баланс: {current_balance} 🔷")
        except Exception:
            pass
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
                except Exception:
                    pass
            else:
                bot.send_message(message.chat.id, "Недостаточно 🔷")
    except Exception:
        bot.send_message(message.chat.id, "Формат: /removecredits <uid> <amount>")

# ================== START & MENU ==================
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    send_main_menu(chat_id, "👋 Привет! Я умею генерировать изображения, редактировать фото, снимать видео Kling 3.0 в удобной Web-Студии, а в режиме «Чат» работаю как полноценный ИИ-агент. Выбери действие ниже.")

def send_main_menu(chat_id, text="Главное меню:"):
    bot.send_message(chat_id, text, reply_markup=main_menu_keyboard())

# --- GENERATION ---
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

@bot.callback_query_handler(func=lambda call: call.data in ("gen_flux", "gen_seedream"))
def select_generate_model(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_generate_model[chat_id] = "flux" if call.data == "gen_flux" else "seedream"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("16:9", callback_data="gen_aspect_16_9"),
        InlineKeyboardButton("9:16", callback_data="gen_aspect_9_16"),
        InlineKeyboardButton("1:1", callback_data="gen_aspect_1_1"),
        InlineKeyboardButton("4:3", callback_data="gen_aspect_4_3"),
    )
    bot.edit_message_text("Выберите формат кадра:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gen_aspect_"))
def set_generate_aspect(call):
    chat_id = call.message.chat.id
    asp = call.data.split("_", 2)[2].replace("_", ":")
    user_generate_aspect[chat_id] = asp
    bot.answer_callback_query(call.id, f"Формат: {asp}")
    user_state[chat_id] = "awaiting_generate_prompt"
    bot.send_message(chat_id, "✏️ Введите описание для генерации изображения:", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_generate_prompt")
def handle_generate_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    prompt = message.text
    model = user_generate_model.get(chat_id, "flux")
    aspect = user_generate_aspect.get(chat_id, "16:9")
    cost = CREDIT_COSTS["image_pro"]

    with data_lock:
        if chat_id != ADMIN_ID and user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, f"❌ Недостаточно 🔷. Нужно {cost}, у вас {user_credits.get(chat_id, 0)}.")
            send_main_menu(chat_id)
            return
        if chat_id != ADMIN_ID:
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Генерация {model} {aspect}"))
            save_data()

    bot.send_message(chat_id, "🎨 Генерирую изображение...")
    full_p = f"{prompt}. {ASPECT_PROMPTS.get(aspect, '')}" if aspect in ASPECT_PROMPTS else prompt
    img_bytes = generate_image_flux(full_p) if model == "flux" else generate_image_seedream(full_p)

    if img_bytes:
        out_b, _ = _prepare_image_bytes(img_bytes)
        bot.send_photo(chat_id, out_b or img_bytes, caption=f"🎨 Готово! ({aspect})")
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                save_data()
        bot.send_message(chat_id, "❌ Ошибка генерации. Токены 🔷 возвращены.")
    user_state.pop(chat_id, None)
    user_generate_model.pop(chat_id, None)
    user_generate_aspect.pop(chat_id, None)
    send_main_menu(chat_id)

# --- EDITING ---
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

@bot.callback_query_handler(func=lambda call: call.data in ("edit_flux", "edit_seedream"))
def select_edit_model(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_edit_model[chat_id] = "flux" if call.data == "edit_flux" else "seedream"
    user_state[chat_id] = "awaiting_edit_photo"
    bot.edit_message_text("📸 Загрузите фото для редактирования:", chat_id, call.message.message_id)
    bot.send_message(chat_id, "Отправьте фото:", reply_markup=back_keyboard())

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_edit_photo")
def handle_edit_photo_upload(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode("utf-8")
    user_pending_photo[chat_id] = b64

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Сохранить лицо", callback_data="edit_face_on"),
        InlineKeyboardButton("❌ Обычное", callback_data="edit_face_off"),
    )
    bot.send_message(chat_id, "Сохранить черты лица человека?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ("edit_face_on", "edit_face_off"))
def set_edit_face_mode(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_face_mode[chat_id] = (call.data == "edit_face_on")
    user_state[chat_id] = "awaiting_edit_prompt"
    bot.send_message(chat_id, "✏️ Введите описание изменений:\n(например: «сделай киберпанк фон, неоновый свет»)", reply_markup=back_keyboard())
    bot.delete_message(chat_id, call.message.message_id)

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_edit_prompt")
def handle_edit_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    prompt = message.text
    model = user_edit_model.get(chat_id, "flux")
    b64 = user_pending_photo.get(chat_id)
    face_mode = user_face_mode.get(chat_id, False)
    cost = CREDIT_COSTS["edit_pro"]

    if not b64:
        bot.send_message(chat_id, "❌ Фото не найдено. Начните заново.")
        send_main_menu(chat_id)
        return

    with data_lock:
        if chat_id != ADMIN_ID and user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, f"❌ Недостаточно 🔷. Нужно {cost}.")
            send_main_menu(chat_id)
            return
        if chat_id != ADMIN_ID:
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Редактирование {model}"))
            save_data()

    bot.send_message(chat_id, "🎨 Редактирую фото...")
    if face_mode:
        prompt = f"Keep the person's face exactly the same, only change the environment, clothing, background, lighting or style according to: {prompt}"

    img_bytes, err = edit_image_flux(prompt, b64) if model == "flux" else edit_image_seedream(prompt, b64)

    if img_bytes:
        out_b, _ = _prepare_image_bytes(img_bytes)
        photo_bytes = out_b or img_bytes
        b64_new = base64.b64encode(photo_bytes).decode("utf-8")
        user_last_image[chat_id] = b64_new
        user_last_edit_model[chat_id] = model
        user_last_face_mode[chat_id] = face_mode

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔄 Продолжить редактирование", callback_data="continue_edit"),
            InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")
        )
        bot.send_photo(chat_id, photo_bytes, caption="🎨 Готово!", reply_markup=markup)
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                save_data()
        bot.send_message(chat_id, f"❌ Ошибка редактирования: {err}. Токены 🔷 возвращены.")
        send_main_menu(chat_id)

    user_state.pop(chat_id, None)
    user_edit_model.pop(chat_id, None)
    user_face_mode.pop(chat_id, None)
    user_pending_photo.pop(chat_id, None)

@bot.callback_query_handler(func=lambda call: call.data == "continue_edit")
def continue_edit_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    b64 = user_last_image.get(chat_id)
    if not b64:
        bot.send_message(chat_id, "❌ Предыдущее изображение не найдено. Начните заново.")
        send_main_menu(chat_id)
        return
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    user_pending_photo[chat_id] = b64
    user_edit_model[chat_id] = user_last_edit_model.get(chat_id, "flux")
    user_face_mode[chat_id] = user_last_face_mode.get(chat_id, False)
    user_state[chat_id] = "awaiting_edit_prompt"
    bot.send_message(chat_id, "🔄 Режим цепочки редактирования.\n✏️ Введите описание следующих изменений:", reply_markup=back_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    for d in [user_state, user_edit_model, user_face_mode, user_pending_photo,
              user_last_image, user_last_edit_model, user_last_face_mode,
              user_generate_model, user_generate_aspect, user_video_frames,
              user_video_params, user_video_model, user_video_mode, user_edit_aspect]:
        d.pop(chat_id, None)
    send_main_menu(chat_id)

# --- VIDEO ---
@bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
def menu_video(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_video_mode"

    host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
    studio_url = f"https://{host}/studio" if host else ""

    markup = InlineKeyboardMarkup(row_width=1)
    if studio_url:
        markup.add(InlineKeyboardButton("✨ Kling 3.0 Видео-Студия [Покадровый Web App]", web_app=WebAppInfo(url=studio_url)))
    markup.add(
        InlineKeyboardButton("📝 Текст в видео (Обычный промпт)", callback_data="vid_text"),
        InlineKeyboardButton("🎬 Мультисцена через диалог бота", callback_data="vid_multi"),
        InlineKeyboardButton("🖼 Картинка в видео (Оживление фото)", callback_data="vid_image"),
    )
    bot.send_message(message.chat.id, "Выберите инструмент генерации видео:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ("vid_text", "vid_image", "vid_multi"))
def select_video_mode(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    data = call.data
    if data == "vid_text":
        user_video_mode[chat_id] = "text"
        user_video_frames[chat_id] = {"first": None, "last": None}
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "🎥 Выберите видеомодель:", reply_markup=video_model_keyboard())
    elif data == "vid_multi":
        user_video_mode[chat_id] = "multi"
        user_video_model[chat_id] = "kwaivgi/kling-v3.0-pro"
        user_video_frames[chat_id] = {"multi_list": []}
        bot.delete_message(chat_id, call.message.message_id)
        start_video_param_selection(chat_id)
    elif data == "vid_image":
        user_video_mode[chat_id] = "image_one"
        user_video_frames[chat_id] = {"first": None, "last": None}
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "🎥 Выберите видеомодель:", reply_markup=video_model_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("vmodel_"))
def set_video_model(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    model_key = call.data.split("_", 1)[1]
    model_map = {
        "seedance-2.0": "bytedance/seedance-2.0",
        "kling-o1": "kwaivgi/kling-video-o1",
        "kling-pro": "kwaivgi/kling-v3.0-pro",
    }
    if model_key in model_map:
        user_video_model[chat_id] = model_map[model_key]
        bot.delete_message(chat_id, call.message.message_id)
        if user_video_mode.get(chat_id) == "image_one":
            user_state[chat_id] = "awaiting_video_image_first"
            bot.send_message(chat_id, "📸 Загрузите ПЕРВЫЙ кадр (начальное изображение):", reply_markup=back_keyboard())
        else:
            start_video_param_selection(chat_id)
    else:
        bot.send_message(chat_id, "Ошибка выбора модели")

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_first")
def handle_video_first_frame(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode("utf-8")
    if chat_id not in user_video_frames:
        user_video_frames[chat_id] = {}
    user_video_frames[chat_id]["first"] = b64

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📸 Добавить последний кадр", callback_data="add_last_frame"),
        InlineKeyboardButton("▶️ Продолжить без него", callback_data="skip_last_frame"),
    )
    bot.send_message(chat_id, "✅ Первый кадр загружен. Добавить финальный кадр?", reply_markup=markup)
    user_state[chat_id] = "awaiting_video_image_choice"

@bot.callback_query_handler(func=lambda call: call.data in ("add_last_frame", "skip_last_frame"))
def handle_last_frame_choice(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "add_last_frame":
        user_state[chat_id] = "awaiting_video_image_last"
        bot.send_message(chat_id, "📸 Загрузите ПОСЛЕДНИЙ кадр (финальное изображение):", reply_markup=back_keyboard())
    else:
        user_state[chat_id] = "awaiting_video_prompt"
        bot.send_message(chat_id, "✏️ Введите описание (промпт) движения для видео:", reply_markup=back_keyboard())
    bot.delete_message(chat_id, call.message.message_id)

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_last")
def handle_video_last_frame(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode("utf-8")
    if chat_id not in user_video_frames:
        user_video_frames[chat_id] = {}
    user_video_frames[chat_id]["last"] = b64
    user_state[chat_id] = "awaiting_video_prompt"
    bot.send_message(chat_id, "✅ Последний кадр загружен.\n✏️ Введите описание (промпт) для видео:", reply_markup=back_keyboard())

# ================== VIDEO PROMPT HANDLERS ==================
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

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_multi_prompt")
def handle_video_multi_prompt(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    raw_text = message.text
    multi_prompt = []
    total_dur = 0
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            dur = int(parts[0])
            multi_prompt.append({"prompt": parts[1], "duration": dur})
            total_dur += dur
        else:
            multi_prompt.append({"prompt": line, "duration": 3})
            total_dur += 3
    if not multi_prompt:
        bot.send_message(chat_id, "❌ Не удалось распознать сценарий. Попробуйте еще раз.")
        send_main_menu(chat_id)
        return
    if chat_id not in user_video_params:
        user_video_params[chat_id] = {}
    user_video_params[chat_id]["duration"] = total_dur
    user_video_params[chat_id]["multi_prompt_data"] = multi_prompt
    if chat_id not in user_video_frames:
        user_video_frames[chat_id] = {}
    user_video_frames[chat_id]["multi_list"] = []
    user_state[chat_id] = "awaiting_multi_photos"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("▶️ Сгенерировать видео без фото", callback_data="run_multi_video"))
    msg = bot.send_message(
        chat_id,
        "📸 <b>Шаг 2 из 2: Референсы стиля (от 0 до 9 фото)</b>\n\n"
        "Прикрепите картинки, которые Kling 3.0 возьмет за визуальную основу:\n"
        "• 1-е фото станет начальным кадром.\n"
        "• Последнее фото — финальным кадром.\n"
        "• Остальные фото зададут стиль персонажей и окружения.\n\n"
        "<i>Отправляйте фото по одному или сразу альбомом из нескольких штук. Когда загрузите всё нужное — нажмите кнопку ниже:</i>",
        parse_mode="HTML",
        reply_markup=markup
    )
    user_video_params[chat_id]["multi_status_msg_id"] = msg.message_id

# --- OTHER MENU HANDLERS ---
@bot.message_handler(func=lambda m: m.text == "💬 Спросить (чат)")
def menu_chat(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    bot.send_message(message.chat.id, "🤖 Режим ИИ-агента активирован!\nЯ помню контекст диалога, гуглю информацию, читаю ссылки, рисую арты и снимаю мини-фильмы. Каждые 50 сообщений списывается 1 🔷.", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def menu_profile(message):
    user_last_activity[message.chat.id] = time.time()
    profile(message)

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
        "
