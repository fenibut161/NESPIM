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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)

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

user_last_image = {}
user_last_edit_model = {}
user_last_face_mode = {}
user_last_edit_aspect = {}
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

# --- WEB APP HTML (с выбором разрешения) ---
WEBAPP_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <title>Kling 3.0 Studio</title>
    <style>
        :root { --bg-color: var(--tg-theme-bg-color, #18181b); --text-color: var(--tg-theme-text-color, #ffffff); --hint-color: var(--tg-theme-hint-color, #9ca3af); --btn-color: var(--tg-theme-button-color, #3b82f6); --btn-text: var(--tg-theme-button-text-color, #ffffff); --sec-bg: var(--tg-theme-secondary-bg-color, #27272a); }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-color); color: var(--text-color); margin: 0; padding: 16px; padding-bottom: 95px; }
        .header { text-align: center; margin-bottom: 18px; }
        .header h1 { font-size: 20px; margin: 0; font-weight: 700; }
        .header p { font-size: 13px; color: var(--hint-color); margin: 4px 0 0 0; }
        .card { background: var(--sec-bg); border-radius: 16px; padding: 16px; margin-bottom: 16px; }
        .card-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .aspect-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
        .aspect-btn { background: rgba(255,255,255,0.05); border: 2px solid transparent; color: var(--text-color); padding: 10px; border-radius: 12px; text-align: center; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.2s; }
        .aspect-btn.active { border-color: var(--btn-color); background: rgba(59, 130, 246, 0.15); }
        .scene-block { background: rgba(0,0,0,0.25); border-radius: 14px; padding: 14px; margin-bottom: 14px; }
        .scene-head { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; margin-bottom: 10px; }
        .scene-del { color: #ef4444; font-size: 12px; cursor: pointer; }
        textarea { width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: var(--text-color); padding: 10px; font-size: 14px; resize: none; height: 60px; outline: none; margin-bottom: 10px; }
        textarea:focus { border-color: var(--btn-color); }
        .scene-img-box { border: 1px dashed rgba(255,255,255,0.2); border-radius: 10px; padding: 10px; text-align: center; cursor: pointer; background: rgba(255,255,255,0.02); min-height: 36px; display: flex; align-items: center; justify-content: center; }
        .scene-img-box img { max-height: 120px; border-radius: 6px; }
        .empty-hint { font-size: 12px; color: var(--hint-color); display: flex; align-items: center; gap: 6px; }
        .del-img-badge { position: absolute; top: 6px; right: 6px; background: rgba(239,68,68,0.9); color: #fff; border-radius: 50%; width: 22px; height: 22px; font-size: 12px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
        .dur-row { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; font-size: 13px; color: var(--hint-color); }
        input[type="range"] { accent-color: var(--btn-color); width: 58%; }
        .sec-num { font-weight: 700; color: #3b82f6; width: 32px; text-align: right; }
        .add-scene-btn { width: 100%; padding: 14px; background: rgba(255,255,255,0.08); border: none; border-radius: 12px; color: var(--text-color); font-weight: 600; font-size: 14px; cursor: pointer; }
        .main-btn { position: fixed; bottom: 16px; left: 16px; right: 16px; background: var(--btn-color); color: var(--btn-text); border: none; padding: 16px; border-radius: 14px; font-size: 15px; font-weight: 700; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.4); cursor: pointer; text-align: center; }
        .main-btn:disabled { background: #52525b; color: #9ca3af; cursor: not-allowed; }
    </style>
</head>
<body>
<div class="header"><h1>✨ Kling 3.0 Studio</h1><p>Покадровый конструктор фильма (до 18 секунд)</p></div>
<div class="card">
    <div class="card-title">Формат кадра</div>
    <div class="aspect-grid">
        <div class="aspect-btn active" onclick="setAspect('16:9', this)">🖥 16:9</div>
        <div class="aspect-btn" onclick="setAspect('9:16', this)">📱 9:16</div>
        <div class="aspect-btn" onclick="setAspect('1:1', this)">⬜ 1:1</div>
    </div>
</div>
<div class="card">
    <div class="card-title">Разрешение видео</div>
    <div class="aspect-grid" id="resGrid">
        <div class="aspect-btn active" onclick="setRes('480p', this)">480p</div>
        <div class="aspect-btn" onclick="setRes('720p', this)">720p</div>
        <div class="aspect-btn" onclick="setRes('1080p', this)">1080p</div>
    </div>
</div>
<div class="card">
    <div class="card-title"><span>Сцены фильма (макс. 6)</span><span style="font-size:13px; font-weight:700" id="totalSec">3с (15 🔷)</span></div>
    <div id="scenesContainer"></div>
    <button class="add-scene-btn" onclick="addScene()" id="addBtn">+ Добавить следующий кадр</button>
</div>
<input type="file" id="hiddenFile" accept="image/*" style="display:none">
<button class="main-btn" id="submitBtn" onclick="submitStudio()">🚀 Запустить рендер (15 🔷)</button>
<script>
    const tg = window.Telegram.WebApp; tg.ready(); tg.expand();
    let currentAspect = '16:9', currentRes = '480p', activeUploadIdx = null;
    let scenes = [{ prompt: '', dur: 3, photo: null }];
    const MAX_KLING_SEC = 18;
    function renderScenes() {
        const cont = document.getElementById('scenesContainer'); cont.innerHTML = '';
        scenes.forEach((sc, idx) => {
            let imgHtml = sc.photo ? `<img src="data:image/jpeg;base64,${sc.photo}"><div class="del-img-badge" onclick="event.stopPropagation(); removePhoto(${idx})">✕</div>` : `<div class="empty-hint"><span style="font-size:16px">🖼</span> Прикрепить референс для Сцены ${idx+1}</div>`;
            cont.innerHTML += `
                <div class="scene-block">
                    <div class="scene-head"><span>Сцена ${idx + 1}</span>${scenes.length > 1 ? `<span class="scene-del" onclick="delScene(${idx})">Удалить</span>` : ''}</div>
                    <textarea placeholder="Что происходит в этой сцене..." oninput="scenes[${idx}].prompt = this.value">${sc.prompt}</textarea>
                    <div class="scene-img-box" onclick="triggerUpload(${idx})">${imgHtml}</div>
                    <div class="dur-row"><span>Длительность:</span><input type="range" min="2" max="6" value="${sc.dur}" oninput="scenes[${idx}].dur = parseInt(this.value); this.nextElementSibling.innerText = this.value + 'с'; updateSummary()"><span class="sec-num">${sc.dur}с</span></div>
                </div>`;
        });
        document.getElementById('addBtn').style.display = scenes.length >= 6 ? 'none' : 'block'; updateSummary();
    }
    function addScene() { if (scenes.length < 6) { scenes.push({ prompt: '', dur: 3, photo: null }); renderScenes(); } }
    function delScene(i) { scenes.splice(i, 1); renderScenes(); }
    function setAspect(asp, el) { currentAspect = asp; document.querySelectorAll('.aspect-grid .aspect-btn').forEach(b => b.classList.remove('active')); el.classList.add('active'); }
    function setRes(res, el) { currentRes = res; const grid = document.getElementById('resGrid'); if (grid) { grid.querySelectorAll('.aspect-btn').forEach(b => b.classList.remove('active')); el.classList.add('active'); } }
    function triggerUpload(idx) { activeUploadIdx = idx; document.getElementById('hiddenFile').click(); }
    function removePhoto(idx) { scenes[idx].photo = null; renderScenes(); }
    document.getElementById('hiddenFile').addEventListener('change', async function(e) {
        if (e.target.files && e.target.files[0] && activeUploadIdx !== null) {
            const b64 = await compressImg(e.target.files[0]); scenes[activeUploadIdx].photo = b64; renderScenes();
        }
        e.target.value = '';
    });
    function compressImg(file) { return new Promise(res => { const r = new FileReader(); r.onload = e => { const img = new Image(); img.onload = () => { const cvs = document.createElement('canvas'); let w = img.width, h = img.height, max = 800; if (w > h && w > max) { h *= max / w; w = max; } else if (h > max) { w *= max / h; h = max; } cvs.width = w; cvs.height = h; cvs.getContext('2d').drawImage(img, 0, 0, w, h); res(cvs.toDataURL('image/jpeg', 0.8).split(',')[1]); }; img.src = e.target.result; }; r.readAsDataURL(file); }); }
    function updateSummary() {
        const tot = scenes.reduce((a, b) => a + b.dur, 0); const btn = document.getElementById('submitBtn'); const badge = document.getElementById('totalSec');
        if (tot > MAX_KLING_SEC) { badge.innerHTML = `<span style="color:#ef4444">⚠️ Лимит 18с! У вас ${tot}с</span>`; btn.disabled = true; btn.innerText = `⚠️ Уменьшите секунды (максимум 18с)`; }
        else { const cost = tot * 5; badge.innerHTML = `<span style="color:#3b82f6">${tot}с (${cost} 🔷)</span>`; btn.disabled = false; btn.innerText = `🚀 Запустить рендер фильма (${cost} 🔷)`; }
    }
    async function submitStudio() {
        if (scenes.some(s => s.prompt.trim().length === 0)) { tg.showAlert('Пожалуйста, заполните описание для каждой сцены!'); return; }
        const btn = document.getElementById('submitBtn'); btn.disabled = true; btn.innerText = '⏳ Передача в студию...';
        const payload = { user_id: tg.initDataUnsafe?.user?.id || 0, scenes: scenes, aspect_ratio: currentAspect, resolution: currentRes };
        try {
            const r = await fetch('/api/webapp_submit_video', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const res = await r.json(); if (res.ok) tg.close(); else { tg.showAlert('Ошибка: ' + res.error); btn.disabled = false; updateSummary(); }
        } catch(e) { tg.showAlert('Ошибка связи с сервером бота'); btn.disabled = false; updateSummary(); }
    }
    renderScenes();
</script>
</body>
</html>'''

# --- GIST SYNC ---
def load_data():
    global user_credits, user_credit_history, user_message_count, user_last_activity, user_chat_history
    data = None
    if GIST_ID and GITHUB_TOKEN:
        try:
            r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=15)
            if r.status_code == 200:
                data = json.loads(r.json()["files"]["bot_data.json"]["content"])
        except: pass
    if not data:
        try:
            with open(DATA_FILE, "r") as f: data = json.load(f)
        except: data = {}
    user_credits = defaultdict(int, {int(k): v for k, v in data.get("credits", {}).items()})
    user_credit_history = defaultdict(list, {int(k): v for k, v in data.get("history", {}).items()})
    user_message_count = defaultdict(int, {int(k): v for k, v in data.get("messages", {}).items()})
    user_last_activity = defaultdict(float, {int(k): v for k, v in data.get("last_activity", {}).items()})
    user_chat_history = defaultdict(list, {int(k): v for k, v in data.get("chat_history", {}).items()})
    logging.info(f"[LOAD] {sum(user_credits.values())} credits")

def save_data():
    with data_lock:
        snap = {"credits": dict(user_credits), "history": dict(user_credit_history), "messages": dict(user_message_count), "last_activity": dict(user_last_activity), "chat_history": dict(user_chat_history)}
    try:
        with open(DATA_FILE, "w") as f: json.dump(snap, f, ensure_ascii=False, indent=2)
    except: pass
    if GIST_ID and GITHUB_TOKEN:
        def _g():
            try:
                requests.patch(f"https://api.github.com/gists/{GIST_ID}", json={"files": {"bot_data.json": {"content": json.dumps(snap, ensure_ascii=False)}}}, headers={"Authorization": f"token {GITHUB_TOKEN}"}, timeout=20)
            except: pass
        Thread(target=_g, daemon=True).start()

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

# --- КЭШ МОДЕЛЕЙ (ТОЛЬКО ДЛЯ ДЛИТЕЛЬНОСТИ) ---
VIDEO_MODELS_CACHE = {}
VIDEO_MODELS_CACHE_TIME = 0

def get_video_models_capabilities(force_refresh=False):
    global VIDEO_MODELS_CACHE, VIDEO_MODELS_CACHE_TIME
    now = time.time()
    if not force_refresh and VIDEO_MODELS_CACHE and (now - VIDEO_MODELS_CACHE_TIME < 3600):
        return VIDEO_MODELS_CACHE
    try:
        resp = requests.get("https://openrouter.ai/api/v1/videos/models", timeout=15)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            VIDEO_MODELS_CACHE = {m["id"]: m for m in data}
            VIDEO_MODELS_CACHE_TIME = now
            return VIDEO_MODELS_CACHE
    except: pass
    return VIDEO_MODELS_CACHE

def validate_video_request(model_id, params):
    caps = get_video_models_capabilities().get(model_id)
    if not caps:
        return True, None
    errors = []
    dur = params.get("duration")
    if dur is not None and "supported_durations" in caps:
        if dur not in caps["supported_durations"]:
            errors.append(f"Длительность {dur}с не поддерживается")
    if errors:
        return False, " | ".join(errors)
    return True, None

PACKAGES = {
    "start": {"name": "Старт", "credits": 50, "price_stars": 250, "price_rub": 400, "desc": "50 🔷 на любые операции"},
    "optima": {"name": "Оптима", "credits": 150, "price_stars": 625, "price_rub": 1000, "desc": "150 🔷 (выгоднее)"},
    "maxi": {"name": "Макси", "credits": 400, "price_stars": 1500, "price_rub": 2400, "desc": "400 🔷 (максимальная выгода)"},
}

CREDIT_COSTS = {"image_pro": 2, "edit_pro": 3, "deepseek_session": 1}

def _build_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot",
    }

# ================== ИИ-АГЕНТ (полный) ==================
def helper_web_search(query):
    try:
        items = []
        rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ru&gl=RU&ceid=RU:ru"
        r = requests.get(rss_url, timeout=8)
        if r.status_code == 200:
            try:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:3]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    items.append(f"Новость: {title}")
            except Exception: pass
        if len(items) < 3:
            url = "https://html.duckduckgo.com/html/"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            dr = requests.post(url, data={"q": query, "kl": "ru-ru"}, headers=headers, timeout=10)
            text = dr.text
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
            clean = [re.sub(r'<.*?>', '', s).strip() for s in snippets[:3]]
            items.extend(clean)
        return items if items else ["Актуальных данных по запросу не обнаружено."]
    except Exception as e:
        return [f"Справка поиска: {e}"]

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

def extract_deepseek_tools(choice_msg):
    if choice_msg.get("tool_calls"):
        return choice_msg["tool_calls"], choice_msg.get("content", "")
    content = choice_msg.get("content", "")
    if "<｜tool" in content or "<|tool" in content:
        raw_matches = re.findall(
            r"<[｜\|]tool.*?begin[｜\|]>function<[｜\|]tool.*?sep[｜\|]>(\w+)\s*\n?({[^<]+})",
            content
        )
        t_calls = []
        for fn_name, arg_str in raw_matches:
            t_calls.append({
                "id": f"call_{int(time.time()*1000)}",
                "type": "function",
                "function": {"name": fn_name.strip(), "arguments": arg_str.strip()}
            })
        if t_calls:
            clean_text = re.split(r"<[｜\|]tool", content)[0].strip()
            clean_text = re.sub(r"\b(попис|минут|секун|поиск|созда|арт|функц)$", "", clean_text).strip()
            return t_calls, clean_text
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

def run_agent(chat_id, user_text):
    history = list(user_chat_history.get(chat_id, []))
    if len(history) > 20:
        history = history[-18:]
    system_prompt = (
        "Ты — персональный ИИ-агент и кинорежиссер NESPIM в Telegram. Ты умный, вежливый, инициативный.\n"
        "Твои возможности (инструменты):\n"
        "1. web_search — гуглить в интернете новости, факты, справку.\n"
        "2. fetch_webpage — читать ссылки юзера.\n"
        "3. generate_image — генерировать арты (Flux Pro, стоит 2 🔷).\n"
        "4. generate_multiscene_video — снимать видео Kling 3.0 Pro (5 🔷/сек).\n"
        "5. get_my_balance — проверять баланс юзера.\n"
        "6. clear_memory — очищать память беседы.\n\n"
        "ВАЖНЕЙШИЕ ПРАВИЛА СКОРОСТИ И ПОИСКА:\n"
        "- Делай СТРОГО НЕ БОЛЕЕ ОДНОГО вызова web_search за весь ответ! Получив данные поиска, сразу формируй финальный ответ юзеру. Запрещено перебирать поисковые запросы повторно.\n"
        "- Если юзер прислал ссылку — вызови fetch_webpage ровно один раз.\n\n"
        "ПРАВИЛА ТРАТ НА ВИДЕО:\n"
        "- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО вызывать generate_multiscene_video без предварительного согласия юзера!\n"
        "  Когда юзер просит видеоролик:\n"
        "  1) Предложи красивый покадровый сценарий с секундами.\n"
        "  2) Посчитай стоимость рендера (5 🔷 за 1 сек).\n"
        "  3) ОБЯЗАТЕЛЬНО спроси: «Создаем видео? Стоимость ХХ 🔷».\n"
        "  4) ТОЛЬКО получив утвердительный ответ («Да/Создавай») — вызывай функцию с confirmed_by_user=True.\n"
        "- Если юзер просит просто нарисовать арт/картинку — СРАЗУ вызывай generate_image.\n"
        "- Отвечай понятно, емко, на русском языке."
    )
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]
    headers = _build_headers()
    for turn in range(4):
        payload = {"model": "deepseek/deepseek-chat", "messages": messages, "tools": AGENT_TOOLS}
        try:
            r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
            if r.status_code != 200:
                return f"⚠️ Ошибка OpenRouter: {r.status_code}"
            data = r.json()
            if "error" in data:
                return f"❌ Ошибка API: {data['error'].get('message', 'limit')}"
            choice_msg = data["choices"][0]["message"]
            tool_calls, clean_content = extract_deepseek_tools(choice_msg)
            if tool_calls:
                choice_msg["content"] = clean_content
                choice_msg["tool_calls"] = tool_calls
                messages.append(choice_msg)
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"]["arguments"]
                    call_id = tc["id"]
                    try: args = json.loads(fn_args)
                    except: args = {}
                    res_content = ""
                    if fn_name == "web_search":
                        res_content = "\n".join(helper_web_search(args.get("query", "")))
                    elif fn_name == "fetch_webpage":
                        res_content = helper_fetch_webpage(args.get("url", ""))
                    elif fn_name == "get_my_balance":
                        bal = user_credits.get(chat_id, 0)
                        rem = 50 - user_message_count.get(chat_id, 0)
                        res_content = f"Баланс: {bal} 🔷. Осталось сообщений в пакете чата: {rem}/50."
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
                            res_content = f"Недостаточно токенов (нужно {cost} 🔷)."
                        else:
                            bot.send_message(chat_id, f"🎨 Агент генерирует изображение ({asp})...")
                            full_p = f"{p}. {ASPECT_PROMPTS.get(asp, '')}" if asp in ASPECT_PROMPTS else p
                            img_bytes = generate_image_flux(full_p)
                            if img_bytes:
                                out_b, _ = _prepare_image_bytes(img_bytes)
                                bot.send_photo(chat_id, out_b or img_bytes, caption="🎨 Создано ИИ-агентом")
                                res_content = "Картинка успешно создана и отправлена."
                            else:
                                if chat_id != ADMIN_ID:
                                    with data_lock:
                                        user_credits[chat_id] += cost
                                        save_data()
                                res_content = "Ошибка генерации картинки (токены возвращены)."
                    elif fn_name == "generate_multiscene_video":
                        scenes = args.get("scenes", [])
                        asp = args.get("aspect_ratio", "16:9")
                        is_confirmed = args.get("confirmed_by_user", False)
                        total_d = sum(s.get("duration", 3) for s in scenes)
                        cost = total_d * 5
                        if not is_confirmed:
                            res_content = (
                                f"СТОП! Правило безопасности платформы: нельзя запустить видео без подтверждения юзером! "
                                f"Выведи юзеру сценарий ({total_d} сек, цена {cost} 🔷) и спроси его: 'Запускаем видеоролик в производство?'."
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
                                res_content = f"Недостаточно 🔷. Нужно {cost}."
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
            logging.error(f"[AGENT] {e}")
            return "⚠️ Произошла ошибка при работе ИИ-агента."
    return "⚠️ Поиск не дал однозначного ответа."

# ================== IMAGE HELPERS ==================
def _safe_resample():
    try: return Image.Resampling.LANCZOS
    except: return Image.LANCZOS

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
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}],
        "modalities": ["image"]
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)
    except Exception as e:
        logging.error(f"Flux edit error: {e}")
        return None, str(e)

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
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}],
        "modalities": ["image"]
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
        img = Image.open(io.BytesIO(base64.b64decode(b64_str)))
        img.thumbnail(max_size, _safe_resample())
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except: return b64_str

def is_valid_mp4(d): return d and len(d) > 500 and b"ftyp" in d[:100]

def send_video_safe(chat_id, data, caption="✅ Ваше видео готово!"):
    try:
        f = io.BytesIO(data); f.name = "video.mp4"
        bot.send_video(chat_id, f, caption=caption, supports_streaming=True, timeout=120)
        return True
    except:
        try:
            f = io.BytesIO(data); f.name = "video.mp4"
            bot.send_document(chat_id, f, caption=caption)
            return True
        except: return False

def poll_video_task(polling_url, headers, chat_id, status_message_id, model_display=""):
    start_time = time.time()
    last_edit = 0
    for attempt in range(1, 110):
        time.sleep(8)
        try:
            resp = requests.get(polling_url, headers=headers, timeout=25)
            if resp.status_code != 200: continue
            data = resp.json()
            status = data.get("status", "unknown")
            progress = data.get("progress")
            elapsed = int(time.time() - start_time)
            mins = elapsed // 60
            if status in ("in_progress", "processing", "pending", "running", "queued"):
                if progress and progress > 5:
                    filled = int(progress / 10)
                    bar = "█" * filled + "░" * (10 - filled)
                    text = f"🎬 <b>{model_display}</b>\n📊 Прогресс: <b>{int(progress)}%</b>\n[{bar}]\n⏱ Прошло: {mins} мин ({elapsed} сек)\n🔄 Опрос #{attempt}"
                else:
                    if mins < 1: stage = "Подготовка запроса"
                    elif mins < 2: stage = "Анализ референсов"
                    elif mins < 4: stage = "Генерация кадров"
                    elif mins < 7: stage = "Рендеринг видео"
                    else: stage = "Финализация и кодирование"
                    text = f"🎬 <b>{model_display}</b>\n⏳ {stage}...\n⏱ Прошло: {mins} мин\n🔄 Опрос #{attempt} (OpenRouter)"
            elif status == "completed":
                try: bot.edit_message_text("✅ <b>Генерация завершена!</b>\n⏳ Начинаю скачивание...", chat_id, status_message_id, parse_mode="HTML")
                except: pass
                time.sleep(2)
                downloaded = False
                job_id = polling_url.rstrip("/").split("/")[-1]
                urls = data.get("unsigned_urls", []) or []
                for dl_attempt in range(1, 11):
                    try:
                        bot.edit_message_text(f"✅ Генерация завершена\n⏳ Скачиваю... (попытка {dl_attempt}/10)", chat_id, status_message_id, parse_mode="HTML")
                    except: pass
                    for u in urls:
                        try:
                            vr = requests.get(u, timeout=120, allow_redirects=True)
                            if vr.status_code == 200 and is_valid_mp4(vr.content):
                                if send_video_safe(chat_id, vr.content, "✅ Готово! Kling 3.0 Pro"):
                                    downloaded = True; break
                        except: pass
                    if downloaded: break
                    try:
                        content_url = f"https://openrouter.ai/api/v1/videos/{job_id}/content"
                        vr = requests.get(content_url, headers=headers, timeout=120)
                        if vr.status_code == 200 and is_valid_mp4(vr.content):
                            if send_video_safe(chat_id, vr.content, "✅ Готово! Kling 3.0 Pro"):
                                downloaded = True; break
                    except: pass
                    time.sleep(min(4 + dl_attempt * 1.8, 18))
                if not downloaded:
                    try: bot.edit_message_text(f"⚠️ Видео готово (Job {job_id}), но скачать не удалось. Попробуйте позже.", chat_id, status_message_id)
                    except: pass
                return
            elif status in ("failed", "cancelled", "expired"):
                err = data.get("error", status)
                try: bot.edit_message_text(f"❌ Ошибка генерации: {err}", chat_id, status_message_id)
                except: pass
                return
            now = time.time()
            if now - last_edit > 11:
                try: bot.edit_message_text(text, chat_id, status_message_id, parse_mode="HTML"); last_edit = now
                except: pass
        except Exception as e: logging.warning(f"[POLL] {e}")
    try: bot.edit_message_text("⏰ Время ожидания вышло (~15 мин).", chat_id, status_message_id)
    except: pass

def generate_video_async(chat_id, prompt=None, first=None, last=None, multi_prompt=None):
    params = user_video_params.get(chat_id, {})
    dur = int(params.get("duration", 5))
    cost = dur * 5
    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Нужно {cost} 🔷")
                return False
            user_credits[chat_id] -= cost
            save_data()
        bot.send_message(chat_id, f"✅ Списано {cost} 🔷")
    model = user_video_model.get(chat_id, "bytedance/seedance-2.0")
    model_name = {"bytedance/seedance-2.0": "Seedance 2.0", "kwaivgi/kling-video-o1": "Kling O1", "kwaivgi/kling-v3.0-pro": "Kling 3.0 Pro"}.get(model, model)
    asp = params.get("aspect_ratio", "16:9")
    res = params.get("resolution", "480p")
    aud = params.get("audio", True)
    headers = _build_headers()
    payload = {"model": model, "duration": dur, "aspect_ratio": asp}

    # === ИСПРАВЛЕНИЕ ДЛЯ СТУДИИ: имитируем обычный текстовый запрос ===
    if multi_prompt:
        scenes_text = []
        all_photos = []
        for i, s in enumerate(multi_prompt, 1):
            scene_dur = int(s.get("duration", s.get("dur", 3)))
            scenes_text.append(f"Scene {i} ({scene_dur}s): {s.get('prompt', '')}")
            if s.get("photo"):
                all_photos.append(s["photo"])

        payload["prompt"] = "\n\n".join(scenes_text)
        # frame_images: первый кадр = first_frame, последний = last_frame (если >1)
        frames = []
        if len(all_photos) > 0:
            first_b64 = compress_image_if_needed(all_photos[0])
            frames.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{first_b64}"}, "frame_type": "first_frame"})
        if len(all_photos) > 1:
            last_b64 = compress_image_if_needed(all_photos[-1])
            frames.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{last_b64}"}, "frame_type": "last_frame"})
        if frames:
            payload["frame_images"] = frames
        # Остальные фото (средние) добавим в input_references, если модель поддерживает
        if len(all_photos) > 2 and feats.get("references"):
            refs = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(p)}"}} for p in all_photos[1:-1]]
            if refs:
                payload["input_references"] = refs
        model_name += " [Studio]"

    elif prompt:
        payload["prompt"] = prompt
        frames = []
        if first:
            frames.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(first)}"}, "frame_type": "first_frame"})
        if last:
            frames.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{compress_image_if_needed(last)}"}, "frame_type": "last_frame"})
        if frames: payload["frame_images"] = frames

    feats = VIDEO_MODEL_FEATURES.get(model, {})
    if feats.get("resolution"): payload["resolution"] = res
    if feats.get("audio"): payload["audio"] = aud

    is_valid, error_msg = validate_video_request(model, {
        "duration": dur, "resolution": res, "aspect_ratio": asp,
        "frame_images": payload.get("frame_images"),
        "multi_prompt": bool(multi_prompt)
    })
    if not is_valid:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost; save_data()
        bot.send_message(chat_id, f"❌ Модель не поддерживает: {error_msg}")
        return False

    logging.info(f"[VIDEO PAYLOAD] model={model} dur={dur}")
    try:
        r = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
        logging.info(f"[VIDEO] status={r.status_code}")
        if r.status_code not in (200, 202):
            with data_lock:
                if chat_id != ADMIN_ID:
                    user_credits[chat_id] += cost; save_data()
            bot.send_message(chat_id, f"❌ Ошибка {r.status_code}")
            return False
        j = r.json()
        if "polling_url" in j:
            m = bot.send_message(chat_id, f"🎬 <b>Генерация {model_name}</b>\n\n✅ Запрос принят. Ждём...", parse_mode="HTML")
            Thread(target=poll_video_task, args=(j["polling_url"], headers, chat_id, m.message_id, model_name), daemon=True).start()
            return True
        if j.get("unsigned_urls"):
            vr = requests.get(j["unsigned_urls"][0], timeout=60)
            if vr.status_code == 200 and is_valid_mp4(vr.content):
                send_video_safe(chat_id, vr.content)
                return True
        if j.get("b64_json"):
            raw = base64.b64decode(j["b64_json"])
            if is_valid_mp4(raw):
                send_video_safe(chat_id, raw)
                return True
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost; save_data()
        bot.send_message(chat_id, "❌ Пустой ответ. 🔷 возвращены.")
        return False
    except Exception as e:
        logging.error(f"VIDEO EXC: {e}")
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost; save_data()
        bot.send_message(chat_id, "❌ Ошибка связи.")
        return False

# ================== KEYBOARDS ==================
def main_menu_keyboard():
    m = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(KeyboardButton("🖼 Создать изображение"), KeyboardButton("🎨 Редактировать фото"),
          KeyboardButton("🎥 Создать видео"), KeyboardButton("💬 Спросить (чат)"),
          KeyboardButton("👤 Профиль"), KeyboardButton("💰 Магазин"),
          KeyboardButton("📖 Инструкция"))
    return m

def back_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("🔙 Главное меню"))

def video_model_keyboard():
    mk = InlineKeyboardMarkup(row_width=1)
    mk.add(InlineKeyboardButton("🌱 Seedance 2.0", callback_data="vmodel_seedance-2.0"),
           InlineKeyboardButton("🎬 Kling O1", callback_data="vmodel_kling-o1"),
           InlineKeyboardButton("🎥 Kling 3.0 Pro", callback_data="vmodel_kling-pro"))
    return mk

def video_params_keyboard(chat_id):
    p = user_video_params.get(chat_id, {})
    d = p.get("duration", 5)
    r = p.get("resolution", "480p")
    a = p.get("audio", True)
    asp = p.get("aspect_ratio", "16:9")
    mk = InlineKeyboardMarkup(row_width=3)
    mk.add(InlineKeyboardButton(f"{'✅' if d==5 else '⬜'} 5с", callback_data="vid_dur_5"),
           InlineKeyboardButton(f"{'✅' if d==10 else '⬜'} 10с", callback_data="vid_dur_10"),
           InlineKeyboardButton(f"{'✅' if d==15 else '⬜'} 15с", callback_data="vid_dur_15"))
    mk.add(InlineKeyboardButton(f"{'✅' if r=='480p' else '⬜'} 480p", callback_data="vid_res_480p"),
           InlineKeyboardButton(f"{'✅' if r=='720p' else '⬜'} 720p", callback_data="vid_res_720p"),
           InlineKeyboardButton(f"{'✅' if r=='1080p' else '⬜'} 1080p", callback_data="vid_res_1080p"))
    mk.add(InlineKeyboardButton(f"{'✅' if asp=='16:9' else '⬜'} 16:9", callback_data="vid_aspect_16_9"),
           InlineKeyboardButton(f"{'✅' if asp=='9:16' else '⬜'} 9:16", callback_data="vid_aspect_9_16"),
           InlineKeyboardButton(f"{'✅' if asp=='1:1' else '⬜'} 1:1", callback_data="vid_aspect_1_1"))
    mk.add(InlineKeyboardButton(f"{'✅' if a else '⬜'} Со звуком", callback_data="vid_audio_true"),
           InlineKeyboardButton(f"{'✅' if not a else '⬜'} Без звука", callback_data="vid_audio_false"))
    mk.add(InlineKeyboardButton("✅ Готово", callback_data="vid_params_done"))
    return mk

# ================== HANDLERS ==================
@bot.message_handler(commands=["start"])
def start_cmd(m):
    chat = m.chat.id
    user_state[chat] = "main"
    bot.send_message(chat, "👋 Привет! Выберите действие:", reply_markup=main_menu_keyboard())

# Генерация изображений
@bot.message_handler(func=lambda m: m.text == "🖼 Создать изображение")
def menu_generate_image(m):
    chat = m.chat.id
    user_state[chat] = "select_model_generate"
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(InlineKeyboardButton("🌊 Flux (2🔷)", callback_data="gen_flux"),
           InlineKeyboardButton("🎨 Seedream (2🔷)", callback_data="gen_seedream"))
    bot.send_message(chat, "Выбери модель для генерации:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("gen_flux", "gen_seedream"))
def select_generate_model(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_generate_model[chat] = "flux" if call.data == "gen_flux" else "seedream"
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(InlineKeyboardButton("16:9", callback_data="gen_aspect_16_9"),
           InlineKeyboardButton("9:16", callback_data="gen_aspect_9_16"),
           InlineKeyboardButton("1:1", callback_data="gen_aspect_1_1"),
           InlineKeyboardButton("4:3", callback_data="gen_aspect_4_3"))
    bot.edit_message_text("Выберите формат кадра:", chat, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("gen_aspect_"))
def set_generate_aspect(call):
    chat = call.message.chat.id
    asp = call.data.split("_", 2)[2].replace("_", ":")
    user_generate_aspect[chat] = asp
    bot.answer_callback_query(call.id, f"Формат: {asp}")
    user_state[chat] = "awaiting_generate_prompt"
    bot.send_message(chat, "✏️ Введите описание для генерации изображения:")

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_generate_prompt")
def handle_generate_prompt(m):
    chat = m.chat.id
    prompt = m.text
    model = user_generate_model.get(chat, "flux")
    aspect = user_generate_aspect.get(chat, "16:9")
    cost = CREDIT_COSTS["image_pro"]
    with data_lock:
        if chat != ADMIN_ID and user_credits.get(chat, 0) < cost:
            bot.send_message(chat, f"❌ Недостаточно 🔷. Нужно {cost}")
            return
        if chat != ADMIN_ID:
            user_credits[chat] -= cost
            user_credit_history[chat].append((time.time(), -cost, f"Генерация {model} {aspect}"))
            save_data()
    bot.send_message(chat, "🎨 Генерирую изображение...")
    full_p = f"{prompt}. {ASPECT_PROMPTS.get(aspect, '')}" if aspect in ASPECT_PROMPTS else prompt
    img_bytes = generate_image_flux(full_p) if model == "flux" else generate_image_seedream(full_p)
    if img_bytes:
        out_b, _ = _prepare_image_bytes(img_bytes)
        bot.send_photo(chat, out_b or img_bytes, caption=f"🎨 Готово! ({aspect})")
    else:
        with data_lock:
            if chat != ADMIN_ID:
                user_credits[chat] += cost
                save_data()
        bot.send_message(chat, "❌ Ошибка генерации. Токены 🔷 возвращены.")
    user_state.pop(chat, None)

# Редактирование фото
@bot.message_handler(func=lambda m: m.text == "🎨 Редактировать фото")
def menu_edit_photo(m):
    chat = m.chat.id
    user_state[chat] = "select_model_edit"
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(InlineKeyboardButton("🌊 Flux (3🔷)", callback_data="edit_flux"),
           InlineKeyboardButton("🎨 Seedream (3🔷)", callback_data="edit_seedream"))
    bot.send_message(chat, "Выбери модель редактирования:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("edit_flux", "edit_seedream"))
def select_edit_model(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_edit_model[chat] = "flux" if call.data == "edit_flux" else "seedream"
    user_state[chat] = "awaiting_edit_photo"
    bot.edit_message_text("📸 Загрузите фото для редактирования:", chat, call.message.message_id)
    bot.send_message(chat, "Отправьте фото:")

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_edit_photo")
def handle_edit_photo_upload(m):
    chat = m.chat.id
    file_info = bot.get_file(m.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode()
    user_pending_photo[chat] = b64
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(InlineKeyboardButton("✅ Сохранить лицо", callback_data="edit_face_on"),
           InlineKeyboardButton("❌ Обычное", callback_data="edit_face_off"))
    bot.send_message(chat, "Сохранить черты лица человека?", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("edit_face_on", "edit_face_off"))
def set_edit_face_mode(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_face_mode[chat] = (call.data == "edit_face_on")
    user_state[chat] = "awaiting_edit_prompt"
    bot.send_message(chat, "✏️ Введите описание изменений:")

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_edit_prompt")
def handle_edit_prompt(m):
    chat = m.chat.id
    prompt = m.text
    model = user_edit_model.get(chat, "flux")
    b64 = user_pending_photo.get(chat)
    face_mode = user_face_mode.get(chat, False)
    cost = CREDIT_COSTS["edit_pro"]
    if not b64:
        bot.send_message(chat, "❌ Фото не найдено. Начните заново.")
        return
    with data_lock:
        if chat != ADMIN_ID and user_credits.get(chat, 0) < cost:
            bot.send_message(chat, f"❌ Недостаточно 🔷. Нужно {cost}.")
            return
        if chat != ADMIN_ID:
            user_credits[chat] -= cost
            user_credit_history[chat].append((time.time(), -cost, f"Редактирование {model}"))
            save_data()
    bot.send_message(chat, "🎨 Редактирую фото...")
    if face_mode:
        prompt = f"Keep the person's face exactly the same, only change the environment, clothing, background, lighting or style according to: {prompt}"
    img_bytes, err = edit_image_flux(prompt, b64) if model == "flux" else edit_image_seedream(prompt, b64)
    if img_bytes:
        out_b, _ = _prepare_image_bytes(img_bytes)
        bot.send_photo(chat, out_b or img_bytes, caption="🎨 Готово!")
    else:
        with data_lock:
            if chat != ADMIN_ID:
                user_credits[chat] += cost
                save_data()
        bot.send_message(chat, f"❌ Ошибка редактирования: {err}. Токены 🔷 возвращены.")
    user_state.pop(chat, None)

# ========== ВИДЕО (полный функционал без мультисцены через диалог) ==========
@bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
def menu_video(m):
    chat = m.chat.id
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
    studio_url = f"https://{host}/studio" if host else ""
    mk = InlineKeyboardMarkup(row_width=1)
    if studio_url:
        mk.add(InlineKeyboardButton("✨ Kling 3.0 Видео-Студия [Покадровый Web App]", web_app=WebAppInfo(url=studio_url)))
    mk.add(
        InlineKeyboardButton("📝 Текст в видео (Обычный промпт)", callback_data="vid_text"),
        InlineKeyboardButton("🖼 Картинка в видео (Оживление фото)", callback_data="vid_image"),
    )
    bot.send_message(chat, "Выберите инструмент генерации видео:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("vid_text", "vid_image"))
def choose_video_mode(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_video_mode[chat] = "text" if call.data == "vid_text" else "image_one"
    user_state[chat] = "select_video_model"
    bot.delete_message(chat, call.message.message_id)
    bot.send_message(chat, "🎥 Выберите видеомодель:", reply_markup=video_model_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("vmodel_"))
def set_video_model(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    model_key = call.data.split("_", 1)[1]
    model_map = {
        "seedance-2.0": "bytedance/seedance-2.0",
        "kling-o1": "kwaivgi/kling-video-o1",
        "kling-pro": "kwaivgi/kling-v3.0-pro",
    }
    if model_key in model_map:
        user_video_model[chat] = model_map[model_key]
        bot.delete_message(chat, call.message.message_id)
        mk = InlineKeyboardMarkup()
        mk.add(InlineKeyboardButton("⚙️ Настроить параметры", callback_data="setup_video_params"),
               InlineKeyboardButton("▶️ Пропустить (по умолчанию)", callback_data="skip_video_params"))
        bot.send_message(chat, "Желаете настроить длительность, разрешение, звук?\n(по умолчанию: 5 сек, 480p, звук вкл.)", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("setup_video_params", "skip_video_params"))
def video_params_choice(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.delete_message(chat, call.message.message_id)
    if call.data == "setup_video_params":
        user_video_params[chat] = {"duration": 5, "resolution": "480p", "audio": True, "aspect_ratio": "16:9"}
        bot.send_message(chat, "Настройте параметры видео:", reply_markup=video_params_keyboard(chat))
        user_state[chat] = "setting_video_params"
    else:
        proceed_after_video_params(chat)

def proceed_after_video_params(chat_id):
    mode = user_video_mode.get(chat_id, "text")
    if mode == "text":
        user_state[chat_id] = "awaiting_video_prompt"
        bot.send_message(chat_id, "✏️ Введите описание видео (промпт):")
    else:
        user_state[chat_id] = "awaiting_video_image_first"
        bot.send_message(chat_id, "📸 Загрузите ПЕРВЫЙ кадр (начальное изображение):")

@bot.callback_query_handler(func=lambda c: c.data.startswith("vid_") and user_state.get(c.message.chat.id) == "setting_video_params")
def handle_video_param_buttons(call):
    chat = call.message.chat.id
    data = call.data
    bot.answer_callback_query(call.id)
    params = user_video_params.setdefault(chat, {})
    if data == "vid_params_done":
        bot.edit_message_reply_markup(chat, call.message.message_id, reply_markup=None)
        user_state[chat] = None
        proceed_after_video_params(chat)
        return
    if data.startswith("vid_dur_"):
        params["duration"] = int(data.split("_")[-1])
    elif data.startswith("vid_res_"):
        params["resolution"] = data.split("_")[-1]
    elif data.startswith("vid_aspect_"):
        asp = data.split("_")[-2] + ":" + data.split("_")[-1]
        params["aspect_ratio"] = asp
    elif data == "vid_audio_true":
        params["audio"] = True
    elif data == "vid_audio_false":
        params["audio"] = False
    bot.edit_message_reply_markup(chat, call.message.message_id, reply_markup=video_params_keyboard(chat))

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_first")
def handle_video_first_frame(m):
    chat = m.chat.id
    file_info = bot.get_file(m.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode()
    user_video_frames[chat] = {"first": b64}
    mk = InlineKeyboardMarkup()
    mk.add(InlineKeyboardButton("📸 Добавить последний кадр", callback_data="add_last_frame"),
           InlineKeyboardButton("▶️ Продолжить без него", callback_data="skip_last_frame"))
    bot.send_message(chat, "✅ Первый кадр загружен. Добавить финальный кадр?", reply_markup=mk)
    user_state[chat] = "awaiting_video_image_choice"

@bot.callback_query_handler(func=lambda c: c.data in ("add_last_frame", "skip_last_frame"))
def handle_last_frame_choice(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "add_last_frame":
        user_state[chat] = "awaiting_video_image_last"
        bot.send_message(chat, "📸 Загрузите ПОСЛЕДНИЙ кадр (финальное изображение):")
    else:
        user_state[chat] = "awaiting_video_prompt"
        bot.send_message(chat, "✏️ Введите описание (промпт) движения для видео:")
    bot.delete_message(chat, call.message.message_id)

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_last")
def handle_video_last_frame(m):
    chat = m.chat.id
    file_info = bot.get_file(m.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode()
    user_video_frames[chat]["last"] = b64
    user_state[chat] = "awaiting_video_prompt"
    bot.send_message(chat, "✅ Последний кадр загружен.\n✏️ Введите описание (промпт) для видео:")

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "awaiting_video_prompt")
def handle_video_prompt(m):
    chat = m.chat.id
    prompt = m.text
    user_state[chat] = None
    first_frame = user_video_frames.get(chat, {}).get("first")
    last_frame = user_video_frames.get(chat, {}).get("last")
    user_video_frames.pop(chat, None)
    Thread(target=generate_video_async, args=(chat, prompt, first_frame, last_frame), daemon=True).start()

# Профиль, магазин, админка, чат
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile(m):
    chat = m.chat.id
    credits = user_credits.get(chat, 0)
    history = user_credit_history.get(chat, [])[-5:]
    text = f"👤 <b>Ваш профиль</b>\n\n💰 Баланс: {credits} 🔷\n\n"
    if history:
        text += "📋 <b>Последние операции:</b>\n"
        for ts, delta, reason in history:
            sign = "+" if delta > 0 else ""
            text += f"{sign}{delta} 🔷 – {escape(reason)}\n"
    bot.send_message(chat, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "💰 Магазин")
def shop(m):
    chat = m.chat.id
    text = "🛒 <b>Магазин токенов 🔷</b>\n\n"
    for key, pkg in PACKAGES.items():
        text += f"<b>{pkg['name']}</b>: {pkg['credits']} 🔷 — {pkg['price_stars']} ⭐️ / {pkg['price_rub']} ₽\n"
    bot.send_message(chat, text, parse_mode="HTML")
    mk = InlineKeyboardMarkup(row_width=2)
    for key, pkg in PACKAGES.items():
        mk.add(InlineKeyboardButton(f"{pkg['name']} ⭐️", callback_data=f"buy_stars_{key}"),
               InlineKeyboardButton(f"{pkg['name']} 💳", callback_data=f"buy_card_{key}"))
    bot.send_message(chat, "Оплата Stars (Telegram) или перевод на карту:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_stars_"))
def initiate_stars_payment(call):
    chat = call.message.chat.id
    pkg_key = call.data[10:]
    pkg = PACKAGES.get(pkg_key)
    if pkg:
        try:
            bot.send_invoice(chat, title=f"Пакет «{pkg['name']}»", description=pkg['desc'],
                             provider_token="", currency="XTR",
                             prices=[LabeledPrice(label="XTR", amount=pkg['price_stars'])],
                             start_parameter="shop", invoice_payload=f"package_{pkg_key}")
        except Exception as e:
            logging.error(f"Invoice error: {e}")
            bot.send_message(chat, f"❌ Ошибка: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(query):
    bot.answer_pre_checkout_query(query.id, ok=True)

@bot.message_handler(content_types=["successful_payment"])
def process_payment(m):
    chat = m.chat.id
    pkg_key = m.successful_payment.invoice_payload.split("_")[1]
    pkg = PACKAGES.get(pkg_key)
    if pkg:
        with data_lock:
            user_credits[chat] += pkg["credits"]
            user_credit_history[chat].append((time.time(), pkg["credits"], f"Покупка {pkg['name']}"))
            save_data()
        bot.send_message(chat, f"✅ Начислено {pkg['credits']} 🔷")

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_card_"))
def handle_card_payment(call):
    chat = call.message.chat.id
    pkg_key = call.data[9:]
    pkg = PACKAGES.get(pkg_key)
    if not pkg: return
    user = call.from_user
    username = f"@{user.username}" if user.username else "без username"
    bot.send_message(chat,
        f"💳 <b>Оплата картой — пакет «{pkg['name']}»</b>\n\n"
        f"Сумма: <b>{pkg['price_rub']} ₽</b>\n"
        f"Вы получите: <b>{pkg['credits']} 🔷</b>\n\n"
        f"Переведите сумму на Т-Банк / СБЕР:\n<code>+79192329005</code>\n\n"
        f"❗️ Укажите в комментарии ваш Telegram ID: <code>{chat}</code>\n\n"
        "После перевода 🔷 начислятся вручную.", parse_mode="HTML")
    try:
        mk = InlineKeyboardMarkup()
        mk.add(InlineKeyboardButton(f"✅ Начислить {pkg['credits']}🔷", callback_data=f"admin_grant_{chat}_{pkg_key}"))
        bot.send_message(ADMIN_ID, f"Запрос оплаты от {username} (ID: {chat}) на {pkg['name']}", reply_markup=mk)
    except: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_grant_"))
def admin_grant_credits(call):
    if call.from_user.id != ADMIN_ID: return
    parts = call.data.split("_")
    target_id = int(parts[2])
    pkg_key = parts[3]
    pkg = PACKAGES.get(pkg_key)
    if not pkg: return
    with data_lock:
        user_credits[target_id] += pkg["credits"]
        user_credit_history[target_id].append((time.time(), pkg["credits"], f"Покупка {pkg['name']} (карта)"))
        save_data()
    bot.edit_message_text(f"✅ Начислено пользователю {target_id}: +{pkg['credits']} 🔷", call.message.chat.id, call.message.message_id)
    try: bot.send_message(target_id, f"🎉 Администратор начислил вам {pkg['credits']} 🔷")
    except: pass

@bot.message_handler(commands=["admin"])
def admin_panel(m):
    if m.chat.id != ADMIN_ID: return
    total = sum(user_credits.values())
    bot.send_message(m.chat.id, f"👑 Админ-панель\nПользователей: {len(user_credits)}\n🔷 всего: {total}")

@bot.message_handler(commands=["addcredits"])
def add_credits(m):
    if m.chat.id != ADMIN_ID: return
    try:
        _, uid, amt = m.text.split()
        uid, amt = int(uid), int(amt)
        with data_lock:
            user_credits[uid] += amt
            user_credit_history[uid].append((time.time(), amt, "Начисление админом"))
            save_data()
        bot.send_message(m.chat.id, f"✅ Начислено {amt} 🔷 пользователю {uid}")
        try: bot.send_message(uid, f"🎉 Администратор начислил вам {amt} 🔷")
        except: pass
    except: bot.send_message(m.chat.id, "Формат: /addcredits <uid> <amount>")

@bot.message_handler(commands=["videomodels"])
def show_video_models(m):
    if m.chat.id != ADMIN_ID: return
    caps = get_video_models_capabilities(force_refresh=True)
    text = "🎥 <b>Видео-модели (OpenRouter)</b>\n\n"
    for mid, m in list(caps.items())[:6]:
        text += f"<b>{m.get('name', mid)}</b>\n"
        text += f"  • durations: {m.get('supported_durations', [])[:6]}...\n"
        text += f"  • resolutions: {m.get('supported_resolutions', [])}\n"
        text += f"  • aspect: {m.get('supported_aspect_ratios', [])}\n"
        text += f"  • frame_images: {m.get('supported_frame_images', [])}\n\n"
    bot.send_message(m.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "📖 Инструкция")
def instruction(m):
    bot.send_message(m.chat.id, "Инструкция: используйте кнопки меню.\nВидео создаётся через студию, по тексту или по фото.")

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_to_main(m):
    chat = m.chat.id
    user_state.pop(chat, None)
    bot.send_message(chat, "Главное меню:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.text == "💬 Спросить (чат)")
def chat_mode(m):
    chat = m.chat.id
    user_state[chat] = "chat"
    bot.send_message(chat, "Задайте вопрос:")

@bot.message_handler(func=lambda m: user_state.get(m.chat.id) == "chat")
def handle_chat_message(m):
    chat = m.chat.id
    reply = run_agent(chat, m.text)
    bot.send_message(chat, reply, reply_markup=back_keyboard())

# ================== WEB APP SUBMIT ==================
@app.route("/api/webapp_submit_video", methods=["POST"])
def webapp_submit_video():
    data = request.json or {}
    uid = int(data.get("user_id", 0))
    scenes = data.get("scenes", [])
    asp = data.get("aspect_ratio", "16:9")
    res = data.get("resolution", "480p")
    if not uid or not scenes:
        return jsonify({"ok": False, "error": "Неверные данные"}), 400
    for s in scenes:
        s["duration"] = int(s.get("dur", s.get("duration", 3)))
    total = sum(s.get("duration", 3) for s in scenes)
    cost = total * 5
    with data_lock:
        if uid != ADMIN_ID and user_credits.get(uid, 0) < cost:
            return jsonify({"ok": False, "error": f"Недостаточно 🔷. Нужно {cost}"}), 400
        if uid != ADMIN_ID:
            user_credits[uid] -= cost
            user_credit_history[uid].append((time.time(), -cost, f"Студия {total}с"))
            save_data()
    try:
        bot.send_message(uid, f"🎬 Студия: {len(scenes)} сцен ({total} сек). Kling 3.0 Pro...", parse_mode="HTML")
    except: pass
    user_video_model[uid] = "kwaivgi/kling-v3.0-pro"
    user_video_params[uid] = {"duration": total, "aspect_ratio": asp, "resolution": res, "audio": True}
    Thread(target=generate_video_async, args=(uid, None, None, None, scenes), daemon=True).start()
    return jsonify({"ok": True})

# Flask routes
@app.route("/")
def index(): return "Bot is running"
@app.route("/studio")
def studio(): return WEBAPP_HTML
@app.route("/health")
def h(): return "OK"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        try:
            update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
            bot.process_new_updates([update])
            return "", 200
        except Exception as e:
            logging.error(f"Webhook error: {e}")
            return "", 500
    return "", 403

def set_webhook():
    try:
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
        if host:
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
            time.sleep(1)
            requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url=https://{host}/{TELEGRAM_TOKEN}", timeout=10)
            logging.info("Webhook set")
    except Exception as e:
        logging.error(f"Webhook err: {e}")

Thread(target=set_webhook, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Starting on {port}")
    app.run(host="0.0.0.0", port=port)
