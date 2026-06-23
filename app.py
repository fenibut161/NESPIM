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
    <h1>â¨ Kling 3.0 Studio</h1>
    <p>ÐÐ¾ÐºÐ°Ð´ÑÐ¾Ð²ÑÐ¹ ÐºÐ¾Ð½ÑÑÑÑÐºÑÐ¾Ñ ÑÐ¸Ð»ÑÐ¼Ð° (Ð´Ð¾ 18 ÑÐµÐºÑÐ½Ð´)</p>
</div>
<div class="card">
    <div class="card-title">Ð¤Ð¾ÑÐ¼Ð°Ñ ÐºÐ°Ð´ÑÐ°</div>
    <div class="aspect-grid">
        <div class="aspect-btn active" onclick="setAspect('16:9', this)">ð¥ 16:9</div>
        <div class="aspect-btn" onclick="setAspect('9:16', this)">ð± 9:16</div>
        <div class="aspect-btn" onclick="setAspect('1:1', this)">â¬ 1:1</div>
    </div>
</div>
<div class="card">
    <div class="card-title">
        <span>Ð¡ÑÐµÐ½Ñ ÑÐ¸Ð»ÑÐ¼Ð° (Ð¼Ð°ÐºÑ. 6)</span>
        <span style="font-size:13px; font-weight:700" id="totalSec">3Ñ (15 ð·)</span>
    </div>
    <div id="scenesContainer"></div>
    <button class="add-scene-btn" onclick="addScene()" id="addBtn">+ ÐÐ¾Ð±Ð°Ð²Ð¸ÑÑ ÑÐ»ÐµÐ´ÑÑÑÐ¸Ð¹ ÐºÐ°Ð´Ñ</button>
</div>
<input type="file" id="hiddenFile" accept="image/*" style="display:none">
<button class="main-btn" id="submitBtn" onclick="submitStudio()">ð ÐÐ°Ð¿ÑÑÑÐ¸ÑÑ ÑÐµÐ½Ð´ÐµÑ (15 ð·)</button>
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
                ? `<img src="data:image/jpeg;base64,${sc.photo}"><div class="del-img-badge" onclick="event.stopPropagation(); removePhoto(${idx})">â</div>`
                : `<div class="empty-hint"><span style="font-size:16px">ð¼</span> ÐÑÐ¸ÐºÑÐµÐ¿Ð¸ÑÑ ÑÐµÑÐµÑÐµÐ½Ñ Ð´Ð»Ñ Ð¡ÑÐµÐ½Ñ ${idx+1}</div>`;
            cont.innerHTML += `
                <div class="scene-block">
                    <div class="scene-head">
                        <span>Ð¡ÑÐµÐ½Ð° ${idx + 1}</span>
                        ${scenes.length > 1 ? `<span class="scene-del" onclick="delScene(${idx})">Ð£Ð´Ð°Ð»Ð¸ÑÑ</span>` : ''}
                    </div>
                    <textarea placeholder="Ð§ÑÐ¾ Ð¿ÑÐ¾Ð¸ÑÑÐ¾Ð´Ð¸Ñ Ð² ÑÑÐ¾Ð¹ ÑÑÐµÐ½Ðµ..." oninput="scenes[${idx}].prompt = this.value">${sc.prompt}</textarea>
                    <div class="scene-img-box" onclick="triggerUpload(${idx})">${imgHtml}</div>
                    <div class="dur-row">
                        <span>ÐÐ»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ:</span>
                        <input type="range" min="2" max="6" value="${sc.dur}" oninput="scenes[${idx}].dur = parseInt(this.value); this.nextElementSibling.innerText = this.value + 'Ñ'; updateSummary()">
                        <span class="sec-num">${sc.dur}Ñ</span>
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
            badge.innerHTML = `<span style="color:#ef4444">â ï¸ ÐÐ¸Ð¼Ð¸Ñ 18Ñ! Ð£ Ð²Ð°Ñ ${tot}Ñ</span>`;
            btn.disabled = true;
            btn.innerText = `â ï¸ Ð£Ð¼ÐµÐ½ÑÑÐ¸ÑÐµ ÑÐµÐºÑÐ½Ð´Ñ (Ð¼Ð°ÐºÑÐ¸Ð¼ÑÐ¼ 18Ñ)`;
        } else {
            const cost = tot * 5;
            badge.innerHTML = `<span style="color:#3b82f6">${tot}Ñ (${cost} ð·)</span>`;
            btn.disabled = false;
            btn.innerText = `ð ÐÐ°Ð¿ÑÑÑÐ¸ÑÑ ÑÐµÐ½Ð´ÐµÑ ÑÐ¸Ð»ÑÐ¼Ð° (${cost} ð·)`;
        }
    }
    async function submitStudio() {
        if (scenes.some(s => s.prompt.trim().length === 0)) {
            tg.showAlert('ÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°, Ð·Ð°Ð¿Ð¾Ð»Ð½Ð¸ÑÐµ ÑÐµÐºÑÑÐ¾Ð²Ð¾Ðµ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ Ð´Ð»Ñ ÐºÐ°Ð¶Ð´Ð¾Ð¹ ÑÐ¾Ð·Ð´Ð°Ð½Ð½Ð¾Ð¹ ÑÑÐµÐ½Ñ!');
            return;
        }
        const btn = document.getElementById('submitBtn');
        btn.disabled = true; btn.innerText = 'â³ ÐÐµÑÐµÐ´Ð°ÑÐ° Ð² ÑÑÑÐ´Ð¸Ñ...';
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
            else { tg.showAlert('ÐÑÐ¸Ð±ÐºÐ°: ' + res.error); btn.disabled = false; updateSummary(); }
        } catch(e) { tg.showAlert('ÐÑÐ¸Ð±ÐºÐ° ÑÐ²ÑÐ·Ð¸ Ñ ÑÐµÑÐ²ÐµÑÐ¾Ð¼ Ð±Ð¾ÑÐ°'); btn.disabled = false; updateSummary(); }
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
    "start": {"name": "Ð¡ÑÐ°ÑÑ", "credits": 50, "price_stars": 250, "price_rub": 400, "desc": "50 ð· Ð½Ð° Ð»ÑÐ±ÑÐµ Ð¾Ð¿ÐµÑÐ°ÑÐ¸Ð¸"},
    "optima": {"name": "ÐÐ¿ÑÐ¸Ð¼Ð°", "credits": 150, "price_stars": 625, "price_rub": 1000, "desc": "150 ð· (Ð²ÑÐ³Ð¾Ð´Ð½ÐµÐµ)"},
    "maxi": {"name": "ÐÐ°ÐºÑÐ¸", "credits": 400, "price_stars": 1500, "price_rub": 2400, "desc": "400 ð· (Ð¼Ð°ÐºÑÐ¸Ð¼Ð°Ð»ÑÐ½Ð°Ñ Ð²ÑÐ³Ð¾Ð´Ð°)"},
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
def helper_web_search(query):
    try:
        items = []
        try:
            rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=ru&gl=RU&ceid=RU:ru"
            r = requests.get(rss_url, timeout=8)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:3]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    items.append(f"ÐÐ¾Ð²Ð¾ÑÑÑ: {title}")
        except Exception:
            pass
        if len(items) < 3:
            try:
                url = "https://html.duckduckgo.com/html/"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                dr = requests.post(url, data={"q": query, "kl": "ru-ru"}, headers=headers, timeout=10)
                text = dr.text
                snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
                clean = [re.sub(r'<.*?>', '', s).strip() for s in snippets[:3]]
                items.extend(clean)
            except Exception:
                pass
        return items if items else ["ÐÐºÑÑÐ°Ð»ÑÐ½ÑÑ Ð´Ð°Ð½Ð½ÑÑ Ð¿Ð¾ ÑÑÐ¾Ð¼Ñ Ð·Ð°Ð¿ÑÐ¾ÑÑ Ð½Ðµ Ð¾Ð±Ð½Ð°ÑÑÐ¶ÐµÐ½Ð¾."]
    except Exception as e:
        return [f"Ð¡Ð¿ÑÐ°Ð²ÐºÐ° Ð¿Ð¾Ð¸ÑÐºÐ°: {e}"]

def helper_fetch_webpage(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        text = unescape(r.text)
        text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<.*?>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2500] if text else "ÐÐµÐ±-ÑÑÑÐ°Ð½Ð¸ÑÐ° Ð¿ÑÑÑÐ°Ñ."
    except Exception as e:
        return f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿ÑÐ¾ÑÐ¸ÑÐ°ÑÑ ÑÑÑÐ»ÐºÑ: {e}"

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "ÐÐ¾Ð¸ÑÐº Ð°ÐºÑÑÐ°Ð»ÑÐ½ÑÑ Ð½Ð¾Ð²Ð¾ÑÑÐµÐ¹, ÑÐ°ÐºÑÐ¾Ð², Ð´Ð¾ÐºÑÐ¼ÐµÐ½ÑÐ°ÑÐ¸Ð¸ Ð¸Ð»Ð¸ Ð¸Ð½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ð¸ Ð² Ð¸Ð½ÑÐµÑÐ½ÐµÑÐµ",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Ð¢Ð¾ÑÐ½ÑÐ¹ Ð¿Ð¾Ð¸ÑÐºÐ¾Ð²ÑÐ¹ Ð·Ð°Ð¿ÑÐ¾Ñ Ð½Ð° ÑÑÑÑÐºÐ¾Ð¼ Ð¸Ð»Ð¸ Ð°Ð½Ð³Ð»Ð¸Ð¹ÑÐºÐ¾Ð¼"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "ÐÑÐ¾ÑÐµÑÑÑ ÑÐµÐºÑÑÐ¾Ð²Ð¾Ðµ ÑÐ¾Ð´ÐµÑÐ¶Ð¸Ð¼Ð¾Ðµ Ð²ÐµÐ±-ÑÑÑÐ°Ð½Ð¸ÑÑ Ð¿Ð¾ ÑÑÑÐ»ÐºÐµ (URL)",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "ÐÑÑÐ¼Ð°Ñ ÑÑÑÐ»ÐºÐ° http/https"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "ÐÐ°ÑÐ¸ÑÐ¾Ð²Ð°ÑÑ Ð¸ Ð¾ÑÐ¿ÑÐ°Ð²Ð¸ÑÑ ÑÐ·ÐµÑÑ ÐºÐ°ÑÑÐ¸Ð½ÐºÑ ÑÐµÑÐµÐ· Ð½ÐµÐ¹ÑÐ¾ÑÐµÑÑ Flux Pro. Ð¡Ð¿Ð¸ÑÑÐ²Ð°ÐµÑ 2 ÑÐ¾ÐºÐµÐ½Ð° ð·.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "ÐÑÐ¾Ð¼Ð¿Ñ Ð´Ð»Ñ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸ Ð½Ð° Ð°Ð½Ð³Ð»Ð¸Ð¹ÑÐºÐ¾Ð¼ Ð¸Ð»Ð¸ ÑÑÑÑÐºÐ¾Ð¼"},
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3"], "description": "Ð¤Ð¾ÑÐ¼Ð°Ñ ÐºÐ°Ð´ÑÐ°"}
                },
                "required": ["prompt", "aspect_ratio"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_multiscene_video",
            "description": "Ð¡Ð½ÑÑÑ ÐºÐ¸Ð½ÐµÐ¼Ð°ÑÐ¾Ð³ÑÐ°ÑÐ¸ÑÐ½ÑÐ¹ Ð¼Ð½Ð¾Ð³Ð¾ÑÑÐµÐ½Ð¾Ð²ÑÐ¹ Ð²Ð¸Ð´ÐµÐ¾ÑÐ¾Ð»Ð¸Ðº Kling 3.0 Pro ÑÐ¾ Ð·Ð²ÑÐºÐ¾Ð¼ (5 ð·/ÑÐµÐº).",
            "parameters": {
                "type": "object",
                "properties": {
                    "scenes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string", "description": "ÐÐ¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ Ð² ÐºÐ¾Ð½ÐºÑÐµÑÐ½Ð¾Ð¼ ÐºÐ°Ð´ÑÐµ"},
                                "duration": {"type": "integer", "description": "Ð¡ÐµÐºÑÐ½Ð´Ñ (Ð¾Ñ 2 Ð´Ð¾ 6)"}
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
            "description": "ÐÑÐ¾Ð²ÐµÑÐ¸ÑÑ ÑÐµÐºÑÑÐ¸Ð¹ Ð±Ð°Ð»Ð°Ð½Ñ ÑÐ¾ÐºÐµÐ½Ð¾Ð² ð· Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_memory",
            "description": "ÐÑÐ¸ÑÑÐ¸ÑÑ Ð¿Ð°Ð¼ÑÑÑ Ð´Ð¸Ð°Ð»Ð¾Ð³Ð° Ñ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÐµÐ¼",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# ================== DEEPSEEK AGENT CORE ==================
def extract_deepseek_tools(choice_msg):
    if choice_msg.get("tool_calls"):
        return choice_msg["tool_calls"], choice_msg.get("content", "")
    content = choice_msg.get("content", "")
    if "<ï½tool" in content or "<|tool" in content:
        raw_matches = re.findall(
            r"<[ï½\|]tool.*?begin[ï½\|]>function<[ï½\|]tool.*?sep[ï½\|]>(\w+)\s*\n?({[^<]+})",
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
            clean_text = re.split(r"<[ï½\|]tool", content)[0].strip()
            clean_text = re.sub(r"\b(Ð¿Ð¾Ð¿Ð¸Ñ|Ð¼Ð¸Ð½ÑÑ|ÑÐµÐºÑÐ½|Ð¿Ð¾Ð¸ÑÐº|ÑÐ¾Ð·Ð´Ð°|Ð°ÑÑ|ÑÑÐ½ÐºÑ)$", "", clean_text).strip()
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
    return "â ï¸ ÐÑÐ¸Ð±ÐºÐ° ÑÐ¾ÐµÐ´Ð¸Ð½ÐµÐ½Ð¸Ñ"

def run_agent(chat_id, user_text):
    history = list(user_chat_history.get(chat_id, []))
    if len(history) > 20:
        history = history[-18:]
    system_prompt = (
        "Ð¢Ñ â Ð¿ÐµÑÑÐ¾Ð½Ð°Ð»ÑÐ½ÑÐ¹ ÐÐ-Ð°Ð³ÐµÐ½Ñ Ð¸ ÐºÐ¸Ð½Ð¾ÑÐµÐ¶Ð¸ÑÑÐµÑ NESPIM Ð² Telegram. Ð¢Ñ ÑÐ¼Ð½ÑÐ¹, Ð²ÐµÐ¶Ð»Ð¸Ð²ÑÐ¹, Ð¸Ð½Ð¸ÑÐ¸Ð°ÑÐ¸Ð²Ð½ÑÐ¹.\n"
        "Ð¢Ð²Ð¾Ð¸ Ð²Ð¾Ð·Ð¼Ð¾Ð¶Ð½Ð¾ÑÑÐ¸ (Ð¸Ð½ÑÑÑÑÐ¼ÐµÐ½ÑÑ):\n"
        "1. web_search â Ð³ÑÐ³Ð»Ð¸ÑÑ Ð² Ð¸Ð½ÑÐµÑÐ½ÐµÑÐµ Ð½Ð¾Ð²Ð¾ÑÑÐ¸, ÑÐ°ÐºÑÑ, ÑÐ¿ÑÐ°Ð²ÐºÑ.\n"
        "2. fetch_webpage â ÑÐ¸ÑÐ°ÑÑ ÑÑÑÐ»ÐºÐ¸ ÑÐ·ÐµÑÐ°.\n"
        "3. generate_image â Ð³ÐµÐ½ÐµÑÐ¸ÑÐ¾Ð²Ð°ÑÑ Ð°ÑÑÑ (Flux Pro, ÑÑÐ¾Ð¸Ñ 2 ð·).\n"
        "4. generate_multiscene_video â ÑÐ½Ð¸Ð¼Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾ Kling 3.0 Pro (5 ð·/ÑÐµÐº).\n"
        "5. get_my_balance â Ð¿ÑÐ¾Ð²ÐµÑÑÑÑ Ð±Ð°Ð»Ð°Ð½Ñ ÑÐ·ÐµÑÐ°.\n"
        "6. clear_memory â Ð¾ÑÐ¸ÑÐ°ÑÑ Ð¿Ð°Ð¼ÑÑÑ Ð±ÐµÑÐµÐ´Ñ.\n\n"
        "ÐÐÐÐÐÐÐ¨ÐÐ ÐÐ ÐÐÐÐÐ Ð¡ÐÐÐ ÐÐ¡Ð¢Ð Ð ÐÐÐÐ¡ÐÐ:\n"
        "- ÐÐµÐ»Ð°Ð¹ Ð¡Ð¢Ð ÐÐÐ ÐÐ ÐÐÐÐÐ ÐÐÐÐÐÐ Ð²ÑÐ·Ð¾Ð²Ð° web_search Ð·Ð° Ð²ÐµÑÑ Ð¾ÑÐ²ÐµÑ! ÐÐ¾Ð»ÑÑÐ¸Ð² Ð´Ð°Ð½Ð½ÑÐµ Ð¿Ð¾Ð¸ÑÐºÐ°, ÑÑÐ°Ð·Ñ ÑÐ¾ÑÐ¼Ð¸ÑÑÐ¹ ÑÐ¸Ð½Ð°Ð»ÑÐ½ÑÐ¹ Ð¾ÑÐ²ÐµÑ ÑÐ·ÐµÑÑ. ÐÐ°Ð¿ÑÐµÑÐµÐ½Ð¾ Ð¿ÐµÑÐµÐ±Ð¸ÑÐ°ÑÑ Ð¿Ð¾Ð¸ÑÐºÐ¾Ð²ÑÐµ Ð·Ð°Ð¿ÑÐ¾ÑÑ Ð¿Ð¾Ð²ÑÐ¾ÑÐ½Ð¾.\n"
        "- ÐÑÐ»Ð¸ ÑÐ·ÐµÑ Ð¿ÑÐ¸ÑÐ»Ð°Ð» ÑÑÑÐ»ÐºÑ â Ð²ÑÐ·Ð¾Ð²Ð¸ fetch_webpage ÑÐ¾Ð²Ð½Ð¾ Ð¾Ð´Ð¸Ð½ ÑÐ°Ð·.\n\n"
        "ÐÐ ÐÐÐÐÐ Ð¢Ð ÐÐ¢ ÐÐ ÐÐÐÐÐ:\n"
        "- ÐÐÐ¢ÐÐÐÐ ÐÐ§ÐÐ¡ÐÐ ÐÐÐÐ ÐÐ©ÐÐÐ Ð²ÑÐ·ÑÐ²Ð°ÑÑ generate_multiscene_video Ð±ÐµÐ· Ð¿ÑÐµÐ´Ð²Ð°ÑÐ¸ÑÐµÐ»ÑÐ½Ð¾Ð³Ð¾ ÑÐ¾Ð³Ð»Ð°ÑÐ¸Ñ ÑÐ·ÐµÑÐ°!\n"
        "  ÐÐ¾Ð³Ð´Ð° ÑÐ·ÐµÑ Ð¿ÑÐ¾ÑÐ¸Ñ Ð²Ð¸Ð´ÐµÐ¾ÑÐ¾Ð»Ð¸Ðº:\n"
        "  1) ÐÑÐµÐ´Ð»Ð¾Ð¶Ð¸ ÐºÑÐ°ÑÐ¸Ð²ÑÐ¹ Ð¿Ð¾ÐºÐ°Ð´ÑÐ¾Ð²ÑÐ¹ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹ Ñ ÑÐµÐºÑÐ½Ð´Ð°Ð¼Ð¸.\n"
        "  2) ÐÐ¾ÑÑÐ¸ÑÐ°Ð¹ ÑÑÐ¾Ð¸Ð¼Ð¾ÑÑÑ ÑÐµÐ½Ð´ÐµÑÐ° (5 ð· Ð·Ð° 1 ÑÐµÐº).\n"
        "  3) ÐÐÐ¯ÐÐÐ¢ÐÐÐ¬ÐÐ ÑÐ¿ÑÐ¾ÑÐ¸: Â«Ð¡Ð¾Ð·Ð´Ð°ÐµÐ¼ Ð²Ð¸Ð´ÐµÐ¾? Ð¡ÑÐ¾Ð¸Ð¼Ð¾ÑÑÑ Ð¥Ð¥ ð·Â».\n"
        "  4) Ð¢ÐÐÐ¬ÐÐ Ð¿Ð¾Ð»ÑÑÐ¸Ð² ÑÑÐ²ÐµÑÐ´Ð¸ÑÐµÐ»ÑÐ½ÑÐ¹ Ð¾ÑÐ²ÐµÑ (Â«ÐÐ°/Ð¡Ð¾Ð·Ð´Ð°Ð²Ð°Ð¹Â») â Ð²ÑÐ·ÑÐ²Ð°Ð¹ ÑÑÐ½ÐºÑÐ¸Ñ Ñ confirmed_by_user=True.\n"
        "- ÐÑÐ»Ð¸ ÑÐ·ÐµÑ Ð¿ÑÐ¾ÑÐ¸Ñ Ð¿ÑÐ¾ÑÑÐ¾ Ð½Ð°ÑÐ¸ÑÐ¾Ð²Ð°ÑÑ Ð°ÑÑ/ÐºÐ°ÑÑÐ¸Ð½ÐºÑ â Ð¡Ð ÐÐÐ£ Ð²ÑÐ·ÑÐ²Ð°Ð¹ generate_image.\n"
        "- ÐÑÐ²ÐµÑÐ°Ð¹ Ð¿Ð¾Ð½ÑÑÐ½Ð¾, ÐµÐ¼ÐºÐ¾, Ð½Ð° ÑÑÑÑÐºÐ¾Ð¼ ÑÐ·ÑÐºÐµ."
    )
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]
    headers = _build_headers()
    for turn in range(4):
        payload = {
            "model": "deepseek/deepseek-chat",
            "messages": messages,
            "tools": AGENT_TOOLS
        }
        try:
            r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
            if r.status_code != 200:
                return f"â ï¸ ÐÑÐ¸Ð±ÐºÐ° OpenRouter: {r.status_code}"
            data = r.json()
            if "error" in data:
                return f"â ÐÑÐ¸Ð±ÐºÐ° API: {data['error'].get('message', 'limit')}"
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
                        res_content = f"ÐÐ°Ð»Ð°Ð½Ñ: {bal} ð·. ÐÑÑÐ°Ð»Ð¾ÑÑ ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸Ð¹ Ð² Ð¿Ð°ÐºÐµÑÐµ ÑÐ°ÑÐ°: {rem_msgs}/50."
                    elif fn_name == "clear_memory":
                        user_chat_history[chat_id] = []
                        save_data()
                        res_content = "ÐÐ°Ð¼ÑÑÑ Ð´Ð¸Ð°Ð»Ð¾Ð³Ð° ÑÑÐ¿ÐµÑÐ½Ð¾ Ð¾ÑÐ¸ÑÐµÐ½Ð°."
                    elif fn_name == "generate_image":
                        p = args.get("prompt", "")
                        asp = args.get("aspect_ratio", "16:9")
                        cost = CREDIT_COSTS["image_pro"]
                        can_gen = False
                        with data_lock:
                            if chat_id == ADMIN_ID or user_credits.get(chat_id, 0) >= cost:
                                if chat_id != ADMIN_ID:
                                    user_credits[chat_id] -= cost
                                    user_credit_history[chat_id].append((time.time(), -cost, f"ÐÐ³ÐµÐ½Ñ: Ð°ÑÑ {asp}"))
                                    save_data()
                                can_gen = True
                        if not can_gen:
                            res_content = f"Ð£ ÑÐ·ÐµÑÐ° Ð½ÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÐ¾ÐºÐµÐ½Ð¾Ð² (Ð½ÑÐ¶Ð½Ð¾ {cost} ð·, Ð±Ð°Ð»Ð°Ð½Ñ {user_credits.get(chat_id, 0)})."
                        else:
                            bot.send_message(chat_id, f"ð¨ ÐÐ³ÐµÐ½Ñ Ð³ÐµÐ½ÐµÑÐ¸ÑÑÐµÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ ({asp})...")
                            full_p = f"{p}. {ASPECT_PROMPTS.get(asp, '')}" if asp in ASPECT_PROMPTS else p
                            img_bytes = generate_image_flux(full_p)
                            if img_bytes:
                                out_b, _ = _prepare_image_bytes(img_bytes)
                                bot.send_photo(chat_id, out_b or img_bytes, caption="ð¨ Ð¡Ð¾Ð·Ð´Ð°Ð½Ð¾ ÐÐ-Ð°Ð³ÐµÐ½ÑÐ¾Ð¼")
                                res_content = "ÐÐ°ÑÑÐ¸Ð½ÐºÐ° ÑÑÐ¿ÐµÑÐ½Ð¾ ÑÐ¾Ð·Ð´Ð°Ð½Ð° Ð¸ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½Ð° Ð² ÑÐ°Ñ ÑÐ·ÐµÑÑ."
                            else:
                                if chat_id != ADMIN_ID:
                                    with data_lock:
                                        user_credits[chat_id] += cost
                                        save_data()
                                res_content = "ÐÑÐ¸Ð±ÐºÐ° Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸ (ÑÐ¾ÐºÐµÐ½Ñ Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ ÑÐ·ÐµÑÑ)."
                    elif fn_name == "generate_multiscene_video":
                        scenes = args.get("scenes", [])
                        asp = args.get("aspect_ratio", "16:9")
                        is_confirmed = args.get("confirmed_by_user", False)
                        total_d = sum(s.get("duration", 3) for s in scenes)
                        cost = total_d * 5
                        if not is_confirmed:
                            res_content = (
                                f"Ð¡Ð¢ÐÐ! ÐÑÐ°Ð²Ð¸Ð»Ð¾ Ð±ÐµÐ·Ð¾Ð¿Ð°ÑÐ½Ð¾ÑÑÐ¸ Ð¿Ð»Ð°ÑÑÐ¾ÑÐ¼Ñ: Ð²Ñ ÐÐ Ð¼Ð¾Ð¶ÐµÑÐµ Ð·Ð°Ð¿ÑÑÑÐ¸ÑÑ ÑÐµÐ½Ð´ÐµÑ Ð²Ð¸Ð´ÐµÐ¾ Ð±ÐµÐ· Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´ÐµÐ½Ð¸Ñ ÑÐ·ÐµÑÐ¾Ð¼! "
                                f"ÐÑÐ²ÐµÐ´Ð¸ ÑÐ·ÐµÑÑ ÑÑÐ¾Ñ ÑÐµÐ¶Ð¸ÑÑÐµÑÑÐºÐ¸Ð¹ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹ (Ð¾Ð±ÑÐ°Ñ Ð´Ð»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ {total_d} ÑÐµÐº, ÑÐµÐ½Ð° {cost} ð·) "
                                f"Ð¸ ÑÐ¿ÑÐ¾ÑÐ¸ ÐµÐ³Ð¾: 'ÐÐ°Ð¿ÑÑÐºÐ°ÐµÐ¼ Ð²Ð¸Ð´ÐµÐ¾ÑÐ¾Ð»Ð¸Ðº Ð² Ð¿ÑÐ¾Ð¸Ð·Ð²Ð¾Ð´ÑÑÐ²Ð¾?'."
                            )
                        else:
                            can_gen = False
                            with data_lock:
                                if chat_id == ADMIN_ID or user_credits.get(chat_id, 0) >= cost:
                                    if chat_id != ADMIN_ID:
                                        user_credits[chat_id] -= cost
                                        user_credit_history[chat_id].append((time.time(), -cost, f"ÐÐ³ÐµÐ½Ñ: Ð²Ð¸Ð´ÐµÐ¾ {total_d}Ñ"))
                                        save_data()
                                    can_gen = True
                            if not can_gen:
                                res_content = f"ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ð·. ÐÑÐ¶Ð½Ð¾ {cost}, Ð±Ð°Ð»Ð°Ð½Ñ {user_credits.get(chat_id, 0)}."
                            else:
                                bot.send_message(chat_id, f"ð¬ ÐÑÐ¸Ð½ÑÑÐ¾! ÐÐ³ÐµÐ½Ñ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÑÐµÑ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹ Ð² Kling 3.0 Pro ({total_d} ÑÐµÐº)...")
                                user_video_model[chat_id] = "kwaivgi/kling-v3.0-pro"
                                user_video_params[chat_id] = {"duration": total_d, "aspect_ratio": asp, "audio": True, "resolution": "720p"}
                                Thread(target=generate_video_async, args=(chat_id, None, None, None, scenes), daemon=True).start()
                                res_content = "ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ Ð¼Ð½Ð¾Ð³Ð¾ÑÑÐµÐ½Ð¾Ð²Ð¾Ð³Ð¾ Ð²Ð¸Ð´ÐµÐ¾ ÑÑÐ¿ÐµÑÐ½Ð¾ Ð·Ð°Ð¿ÑÑÐµÐ½Ð° Ð² ÑÐ¾Ð½Ð¾Ð²Ð¾Ð¼ Ð¿Ð¾ÑÐ¾ÐºÐµ."
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
            return "â ï¸ ÐÑÐ¾Ð¸Ð·Ð¾ÑÐ»Ð° ÑÐ±Ð¾Ð¹-Ð¾ÑÐ¸Ð±ÐºÐ° Ð¿ÑÐ¸ ÑÐ°Ð±Ð¾ÑÐµ ÐÐ-Ð°Ð³ÐµÐ½ÑÐ°."
    return "â ï¸ ÐÐ¾Ð¸ÑÐº Ð½Ðµ Ð´Ð°Ð» Ð¾Ð´Ð½Ð¾Ð·Ð½Ð°ÑÐ½Ð¾Ð³Ð¾ Ð¾ÑÐ²ÐµÑÐ°."

# ================== IMAGE HELPERS ==================
def _safe_resample():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS

def _parse_image_response(resp):
    if resp.status_code != 200:
        return None, f"ÐÑÐ¸Ð±ÐºÐ° API: {resp.status_code} {resp.text[:300]}"
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
            return None, msg.get("content", "ÐÐµÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ñ Ð² Ð¾ÑÐ²ÐµÑÐµ")
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

def _send_video_safe(chat_id, data, caption="â ÐÐ°ÑÐµ Ð²Ð¸Ð´ÐµÐ¾ Ð³Ð¾ÑÐ¾Ð²Ð¾!"):
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
            bot.send_document(chat_id, doc_file, caption="â ÐÐ¸Ð´ÐµÐ¾ (ÐºÐ°Ðº ÑÐ°Ð¹Ð»)")
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
                text = f"ð¬ ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ Ð²Ð¸Ð´ÐµÐ¾ ({model_display}): {int(progress)}% (Ð¿ÑÐ¾ÑÐ»Ð¾ {elapsed} Ð¼Ð¸Ð½)"
            else:
                text = f"ð¬ ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ Ð²Ð¸Ð´ÐµÐ¾ ({model_display}): ÑÑÐ°Ð¿ {attempt} (Ð¿ÑÐ¾ÑÐ»Ð¾ {elapsed} Ð¼Ð¸Ð½)"
            try:
                bot.edit_message_text(text, chat_id, status_message_id)
            except Exception:
                pass
            if status == "completed":
                bot.edit_message_text("â ÐÐ¸Ð´ÐµÐ¾ Ð³Ð¾ÑÐ¾Ð²Ð¾! Ð¡ÐºÐ°ÑÐ¸Ð²Ð°Ñ...", chat_id, status_message_id)
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
                bot.edit_message_text("â ÐÐ¸Ð´ÐµÐ¾ Ð¿Ð¾Ð²ÑÐµÐ¶Ð´ÐµÐ½Ð¾.", chat_id, status_message_id)
                return
            elif status in ("failed", "cancelled", "expired"):
                bot.edit_message_text(f"â ÐÑÐ¸Ð±ÐºÐ°: {status}", chat_id, status_message_id)
                return
        except Exception:
            pass
    bot.edit_message_text("â ÐÑÑÐµÐºÐ»Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ (15 Ð¼Ð¸Ð½).", chat_id, status_message_id)

def generate_video_async(chat_id, prompt=None, first_frame_b64=None, last_frame_b64=None, multi_prompt=None, multi_photos_b64=None):
    params = user_video_params.get(chat_id, {})
    duration = params.get("duration", 5)
    cost = duration * 5
    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"â ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ð·. ÐÑÐ¶Ð½Ð¾ {cost}, Ñ Ð²Ð°Ñ {user_credits.get(chat_id, 0)}. ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÐµ Ð±Ð°Ð»Ð°Ð½Ñ Ð² Ð¼Ð°Ð³Ð°Ð·Ð¸Ð½Ðµ ð°.")
                return False
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"ÐÐ¸Ð´ÐµÐ¾ {duration}Ñ"))
            save_data()
        bot.send_message(chat_id, f"â Ð¡Ð¿Ð¸ÑÐ°Ð½Ð¾ {cost} ð·. ÐÑÑÐ°Ð»Ð¾ÑÑ: {user_credits[chat_id]}")
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
        model_display += " [ÐÑÐ»ÑÑÐ¸ÑÑÐµÐ½Ð° Studio]"
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
                    user_credit_history[chat_id].append((time.time(), cost, "ÐÐ¾Ð·Ð²ÑÐ°Ñ Ð·Ð° Ð²Ð¸Ð´ÐµÐ¾"))
                    save_data()
            bot.send_message(chat_id, f"â ÐÑÐ¸Ð±ÐºÐ° {resp.status_code}. ð· Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ.")
            return False
        data = resp.json()
        if "polling_url" in data:
            msg = bot.send_message(chat_id, f"ð¬ ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ Ð²Ð¸Ð´ÐµÐ¾ ({model_display}): 0%")
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
                user_credit_history[chat_id].append((time.time(), cost, "ÐÐ¾Ð·Ð²ÑÐ°Ñ Ð·Ð° Ð²Ð¸Ð´ÐµÐ¾"))
                save_data()
        bot.send_message(chat_id, "â ÐÑÑÑÐ¾Ð¹ Ð¾ÑÐ²ÐµÑ. ð· Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ.")
    except Exception as e:
        logging.error(f"Video exception: {e}")
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                user_credit_history[chat_id].append((time.time(), cost, "ÐÐ¾Ð·Ð²ÑÐ°Ñ Ð·Ð° Ð²Ð¸Ð´ÐµÐ¾ (Ð¾ÑÐ¸Ð±ÐºÐ°)"))
                save_data()
        bot.send_message(chat_id, "â ÐÑÐ¸Ð±ÐºÐ° ÑÐ²ÑÐ·Ð¸. ð· Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ.")
        return False

# ================== KEYBOARDS ==================
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("ð¼ Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ"),
        KeyboardButton("ð¨ Ð ÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÑÐ¾ÑÐ¾"),
        KeyboardButton("ð¥ Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾"),
        KeyboardButton("ð¬ Ð¡Ð¿ÑÐ¾ÑÐ¸ÑÑ (ÑÐ°Ñ)"),
        KeyboardButton("ð¤ ÐÑÐ¾ÑÐ¸Ð»Ñ"),
        KeyboardButton("ð° ÐÐ°Ð³Ð°Ð·Ð¸Ð½"),
        KeyboardButton("ð ÐÐ½ÑÑÑÑÐºÑÐ¸Ñ"),
    )
    return markup

def back_keyboard():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton("ð ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ"))

def video_model_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("ð± Seedance 2.0", callback_data="vmodel_seedance-2.0"),
        InlineKeyboardButton("ð¬ Kling O1", callback_data="vmodel_kling-o1"),
        InlineKeyboardButton("ð¥ Kling 3.0 Pro ($0.168/Ñ)", callback_data="vmodel_kling-pro"),
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
        InlineKeyboardButton(f"{'â' if duration == 5 else 'â¬'} 5 ÑÐµÐº", callback_data="vid_dur_5"),
        InlineKeyboardButton(f"{'â' if duration == 10 else 'â¬'} 10 ÑÐµÐº", callback_data="vid_dur_10"),
        InlineKeyboardButton(f"{'â' if duration == 15 else 'â¬'} 15 ÑÐµÐº", callback_data="vid_dur_15"),
    )
    markup.add(
        InlineKeyboardButton(f"{'â' if resolution == '480p' else 'â¬'} 480p", callback_data="vid_res_480p"),
        InlineKeyboardButton(f"{'â' if resolution == '720p' else 'â¬'} 720p", callback_data="vid_res_720p"),
        InlineKeyboardButton(f"{'â' if resolution == '1080p' else 'â¬'} 1080p", callback_data="vid_res_1080p"),
    )
    markup.add(
        InlineKeyboardButton(f"{'â' if aspect == '16:9' else 'â¬'} 16:9", callback_data="vid_aspect_16_9"),
        InlineKeyboardButton(f"{'â' if aspect == '9:16' else 'â¬'} 9:16", callback_data="vid_aspect_9_16"),
        InlineKeyboardButton(f"{'â' if aspect == '1:1' else 'â¬'} 1:1", callback_data="vid_aspect_1_1"),
    )
    markup.add(
        InlineKeyboardButton(f"{'â' if audio else 'â¬'} Ð¡Ð¾ Ð·Ð²ÑÐºÐ¾Ð¼", callback_data="vid_audio_true"),
        InlineKeyboardButton(f"{'â' if not audio else 'â¬'} ÐÐµÐ· Ð·Ð²ÑÐºÐ°", callback_data="vid_audio_false"),
    )
    markup.add(InlineKeyboardButton("â ÐÐ¾ÑÐ¾Ð²Ð¾, Ð¿ÑÐ¾Ð´Ð¾Ð»Ð¶Ð¸ÑÑ", callback_data="vid_params_done"))
    return markup

def start_video_param_selection(chat_id):
    user_video_params[chat_id] = user_video_params.get(chat_id, {})
    bot.send_message(chat_id, "ÐÐ°ÑÑÑÐ¾Ð¹ÑÐµ Ð¿Ð°ÑÐ°Ð¼ÐµÑÑÑ Ð²Ð¸Ð´ÐµÐ¾, Ð·Ð°ÑÐµÐ¼ Ð½Ð°Ð¶Ð¼Ð¸ÑÐµ Â«ÐÐ¾ÑÐ¾Ð²Ð¾Â»:", reply_markup=video_params_keyboard(chat_id))

# ================== PROFILE ==================
@bot.message_handler(func=lambda m: m.text == "ð¤ ÐÑÐ¾ÑÐ¸Ð»Ñ")
def profile(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    credits = user_credits.get(chat_id, 0)
    history = user_credit_history.get(chat_id, [])
    text = f"ð¤ **ÐÐ°Ñ Ð¿ÑÐ¾ÑÐ¸Ð»Ñ**\n\nð° ÐÐ°Ð»Ð°Ð½Ñ: {credits} ð·\n\n"
    if history:
        text += "ð **ÐÐ¾ÑÐ»ÐµÐ´Ð½Ð¸Ðµ Ð¾Ð¿ÐµÑÐ°ÑÐ¸Ð¸:**\n"
        for ts, delta, reason in history[-5:]:
            sign = "+" if delta > 0 else ""
            text += f"{sign}{delta} ð· â {escape(reason)}\n"
    else:
        text += "ð **ÐÐ¿ÐµÑÐ°ÑÐ¸Ð¹ Ð¿Ð¾ÐºÐ° Ð½ÐµÑ.**"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("ð³ ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð±Ð°Ð»Ð°Ð½Ñ", callback_data="goto_shop"))
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "goto_shop")
def goto_shop(call):
    bot.answer_callback_query(call.id)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    shop(call.message)

# ================== SHOP & HELP ==================
@bot.message_handler(func=lambda m: m.text == "ð° ÐÐ°Ð³Ð°Ð·Ð¸Ð½")
def shop(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    text = (
        "ð **ÐÐ°Ð³Ð°Ð·Ð¸Ð½ ÑÐ¾ÐºÐµÐ½Ð¾Ð² ð·**\n"
        " ð· Ð·Ð° ÑÐ¾ÐºÐµÐ½Ñ Ð¿ÑÐ¸Ð¾Ð±ÑÐµÑÐ°ÐµÑÑÑ:\n"
        "â¢ ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ (Flux/Seedream) â 2 ð·\n"
        "â¢ Ð ÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ðµ ÑÐ¾ÑÐ¾ (Flux/Seedream) â 3 ð·\n"
        "â¢ ÐÐ¸Ð´ÐµÐ¾ÑÐ¾Ð»Ð¸ÐºÐ¸ (Seedance / Kling Pro) â 5 ð· Ð·Ð° 1 ÑÐµÐº\n"
        "â¢ Ð§Ð°Ñ Ñ ÐÐ-Ð°Ð³ÐµÐ½ÑÐ¾Ð¼ â 1 ð· Ð·Ð° 50 ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸Ð¹\n\n"
        "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¿Ð°ÐºÐµÑ:"
    )
    for key, pkg in PACKAGES.items():
        text += f"\n **{escape(pkg['name'])}**: {pkg['credits']} ð· â {pkg['price_stars']} â­ï¸ / {pkg['price_rub']} â½"
    bot.send_message(chat_id, text, parse_mode="HTML")
    markup = InlineKeyboardMarkup(row_width=2)
    for key, pkg in PACKAGES.items():
        markup.add(
            InlineKeyboardButton(f"{pkg['name']} â­ï¸ {pkg['price_stars']}", callback_data=f"buy_stars_{key}"),
            InlineKeyboardButton(f"{pkg['name']} ð³ {pkg['price_rub']}â½", callback_data=f"buy_card_{key}"),
        )
    bot.send_message(chat_id, "ÐÐ¿Ð»Ð°ÑÐ° Stars (Telegram) Ð¸Ð»Ð¸ Ð¿ÐµÑÐµÐ²Ð¾Ð´ Ð½Ð° ÐºÐ°ÑÑÑ:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "ð ÐÐ½ÑÑÑÑÐºÑÐ¸Ñ")
def menu_help(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    text = (
        "ð <b>Ð ÑÐºÐ¾Ð²Ð¾Ð´ÑÑÐ²Ð¾ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ NESPIM</b>\n\n"
        "ð¤ <b>1. Ð¡Ð¿ÑÐ¾ÑÐ¸ÑÑ (ÐÐ-ÐÐ³ÐµÐ½Ñ)</b>\n"
        "Ð¢Ð²Ð¾Ð¹ ÑÐ¼Ð½ÑÐ¹ Ð°ÑÑÐ¸ÑÑÐµÐ½Ñ. ÐÐ½ Ð¿Ð¾Ð¼Ð½Ð¸Ñ ÐºÐ¾Ð½ÑÐµÐºÑÑ Ð´Ð¸Ð°Ð»Ð¾Ð³Ð°, Ð³ÑÐ³Ð»Ð¸Ñ ÑÐ²ÐµÐ¶ÑÑ Ð¸Ð½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ñ, ÑÐ¸ÑÐ°ÐµÑ ÑÑÑÐ»ÐºÐ¸ Ð¸ ÑÐ°Ð¼ ÑÐ¸ÑÑÐµÑ Ð°ÑÑÑ Ð¸Ð»Ð¸ ÑÐ½Ð¸Ð¼Ð°ÑÑ ÑÑÐµÐ¹Ð»ÐµÑÑ.\n"
        "ÐÐ¾Ð¼Ð°Ð½Ð´Ñ Ð°Ð³ÐµÐ½ÑÑ Ð² ÑÐ°ÑÐµ:\n"
        "â¢ <i>Â«ÐÐ°Ð±ÑÐ´Ñ Ð²ÑÑÂ»</i> â Ð¾ÑÐ¸ÑÑÐ¸ÑÑ Ð¿Ð°Ð¼ÑÑÑ ÑÐ°Ð·Ð³Ð¾Ð²Ð¾ÑÐ°.\n"
        "â¢ <i>Â«ÐÐ°ÐºÐ¾Ð¹ Ð±Ð°Ð»Ð°Ð½Ñ?Â»</i> â Ð¿ÑÐ¾Ð²ÐµÑÐ¸ÑÑ ÑÐ¾ÐºÐµÐ½Ñ.\n"
        "ð <b>Ð¦ÐµÐ½Ð°:</b> 1 ð· Ð·Ð° Ð¿Ð°ÐºÐµÑ Ð¸Ð· 50 ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸Ð¹.\n\n"
        "ð¼ <b>2. Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ</b>\n"
        "ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ ÐºÐ°ÑÑÐ¸Ð½Ð¾Ðº Ð¿Ð¾ ÑÐµÐºÑÑÑ. ÐÐ¾Ð´ÐµÐ»Ð¸:\n"
        "â¢ <b>Flux Pro</b> â ÑÐ¾ÑÐ¾ÑÐµÐ°Ð»Ð¸Ð·Ð¼ Ð¸ Ð¸Ð´ÐµÐ°Ð»ÑÐ½ÑÐµ Ð´ÐµÑÐ°Ð»Ð¸.\n"
        "â¢ <b>Seedream</b> â ÑÐ¾ÑÐ½ÑÐµ ÑÐ²ÐµÑÐ° Ð¸ Ð°ÑÑ-ÑÑÐ¸Ð»Ð¸.\n"
        "ð <b>Ð¦ÐµÐ½Ð°:</b> 2 ð· Ð·Ð° ÐºÐ°ÑÑÐ¸Ð½ÐºÑ.\n\n"
        "ð¨ <b>3. Ð ÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÑÐ¾ÑÐ¾</b>\n"
        "ÐÐ·Ð¼ÐµÐ½ÐµÐ½Ð¸Ðµ Ð²Ð°ÑÐ¸Ñ ÑÐ¾ÑÐ¾Ð³ÑÐ°ÑÐ¸Ð¹ Ð¿Ð¾ ÑÐµÐºÑÑÑ.\n"
        "â¢ Ð ÐµÐ¶Ð¸Ð¼ <b>Â«Ð¡Ð¾ÑÑÐ°Ð½Ð¸ÑÑ Ð»Ð¸ÑÐ¾Â»</b> â Ð½ÐµÐ¹ÑÐ¾ÑÐµÑÑ Ð¿Ð¾Ð¼ÐµÐ½ÑÐµÑ ÑÐ¾Ð½ Ð¸ Ð¾Ð´ÐµÐ¶Ð´Ñ, Ð½Ð¾ Ð¾ÑÑÐ°Ð²Ð¸Ñ ÑÐµÑÑÑ Ð»Ð¸ÑÐ° ÑÐµÐ»Ð¾Ð²ÐµÐºÐ° Ð½ÐµÐ¸Ð·Ð¼ÐµÐ½Ð½ÑÐ¼Ð¸.\n"
        "â¢ ÐÐ¾Ð¶Ð½Ð¾ Ð´Ð¾ÑÐ°Ð±Ð°ÑÑÐ²Ð°ÑÑ ÑÐ¾ÑÐ¾ ÑÐ°Ð³ Ð·Ð° ÑÐ°Ð³Ð¾Ð¼ Ð¿Ð¾ ÑÐµÐ¿Ð¾ÑÐºÐµ.\n"
        "ð <b>Ð¦ÐµÐ½Ð°:</b> 3 ð· Ð·Ð° Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÑ.\n\n"
        "ð¥ <b>4. Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾</b>\n"
        "â¢ <b>ÐÐ±ÑÑÐ½Ð¾Ðµ Ð²Ð¸Ð´ÐµÐ¾</b> â Ð°Ð½Ð¸Ð¼Ð°ÑÐ¸Ñ ÐºÐ°ÑÑÐ¸Ð½Ð¾Ðº Ð¸Ð»Ð¸ ÑÐ¾Ð»Ð¸Ðº Ð¿Ð¾ ÑÐµÐºÑÑÑ.\n"
        "â¢ <b>ÐÐ¸Ð·ÑÐ°Ð»ÑÐ½Ð°Ñ Ð¡ÑÑÐ´Ð¸Ñ Kling 3.0 (Web App)</b> â Ð¿Ð¾ÐºÐ°Ð´ÑÐ¾Ð²ÑÐ¹ ÐºÐ¾Ð½ÑÑÑÑÐºÑÐ¾Ñ! Ð ÐºÐ°Ð¶Ð´ÑÑ ÑÐ¾Ð·Ð´Ð°Ð½Ð½ÑÑ ÑÑÐµÐ½Ñ Ð¼Ð¾Ð¶Ð½Ð¾ Ð²ÑÑÐ°Ð²Ð¸ÑÑ ÑÐ²Ð¾Ð¹ ÑÐµÑÐµÑÐµÐ½Ñ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸.\n"
        "ð <b>Ð¦ÐµÐ½Ð°:</b> 5 ð· Ð·Ð° 1 ÑÐµÐºÑÐ½Ð´Ñ Ð²Ð¸Ð´ÐµÐ¾.\n\n"
        "ð° <b>5. ÐÐ°Ð»Ð°Ð½Ñ Ð¸ Ð¿Ð¾ÐºÑÐ¿ÐºÐ¸</b>\n"
        "Ð Â«ÐÑÐ¾ÑÐ¸Ð»ÐµÂ» Ð²Ð¸Ð´ÐµÐ½ Ð¾ÑÑÐ°ÑÐ¾Ðº ÑÐ¾ÐºÐµÐ½Ð¾Ð². ÐÐ¾Ð¿Ð¾Ð»Ð½Ð¸ÑÑ Ð±Ð°Ð»Ð°Ð½Ñ Ð¼Ð¾Ð¶Ð½Ð¾ Ð² Â«ÐÐ°Ð³Ð°Ð·Ð¸Ð½ÐµÂ» Ð·Ð° Telegram Stars â­ï¸ Ð¼Ð³Ð½Ð¾Ð²ÐµÐ½Ð½Ð¾ Ð¸Ð»Ð¸ Ð¿ÐµÑÐµÐ²Ð¾Ð´Ð¾Ð¼ Ð½Ð° ÐºÐ°ÑÑÑ.\n\n"
        "ð¡ <i>ÐÑÐ»Ð¸ Ð±Ð¾Ñ Ð·Ð°ÑÑÑÑÐ» Ð¸Ð»Ð¸ Ð¶Ð´ÐµÑ ÑÐ¾ÑÐ¾, Ð° Ð²Ñ Ð¿ÐµÑÐµÐ´ÑÐ¼Ð°Ð»Ð¸ â Ð¿ÑÐ¾ÑÑÐ¾ Ð½Ð°Ð¶Ð¼Ð¸ÑÐµ ÐºÐ½Ð¾Ð¿ÐºÑ Â«ð ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½ÑÂ» Ð¸Ð»Ð¸ Ð¾ÑÐ¿ÑÐ°Ð²ÑÑÐµ /start.</i>"
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
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð¿Ð°ÐºÐµÑÐ°")
        return
    try:
        bot.send_invoice(
            chat_id=chat_id,
            title=f"ÐÐ°ÐºÐµÑ Â«{pkg['name']}Â»",
            description=pkg["desc"],
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="XTR", amount=pkg["price_stars"])],
            start_parameter="shop",
            invoice_payload=f"package_{pkg_key}",
        )
        bot.answer_callback_query(call.id, "Ð¡ÑÑÑ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½. ÐÐ¿Ð»Ð°ÑÐ¸ÑÐµ ÑÐµÑÐµÐ· Telegram Stars.")
    except Exception as e:
        logging.error(f"Invoice error: {e}")
        bot.send_message(chat_id, f"â ÐÑÐ¸Ð±ÐºÐ° Ð¿ÑÐ¸ ÑÐ¾Ð·Ð´Ð°Ð½Ð¸Ð¸ ÑÑÑÑÐ°: {e}")

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
            user_credit_history[chat_id].append((time.time(), pkg["credits"], f"ÐÐ¾ÐºÑÐ¿ÐºÐ° Ð¿Ð°ÐºÐµÑÐ° {pkg['name']} (Stars)"))
            save_data()
        bot.send_message(chat_id, f"â ÐÐ¿Ð»Ð°ÑÐ° Ð¿ÑÐ¾ÑÐ»Ð°! ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¾ {pkg['credits']} ð·.\nÐÐ°Ð»Ð°Ð½Ñ: {user_credits[chat_id]} ð·")

# --- CARD PAYMENT (manual) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_card_"))
def handle_card_payment(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    pkg_key = call.data[9:]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð¿Ð°ÐºÐµÑÐ°")
        return
    user = call.from_user
    username = f"@{user.username}" if user.username else "Ð±ÐµÐ· username"
    bot.send_message(
        chat_id,
        f"ð³ **ÐÐ¿Ð»Ð°ÑÐ° ÐºÐ°ÑÑÐ¾Ð¹ â Ð¿Ð°ÐºÐµÑ Â«{pkg['name']}Â»**\n\n"
        f"Ð¡ÑÐ¼Ð¼Ð°: **{pkg['price_rub']} â½**\n"
        f"ÐÑ Ð¿Ð¾Ð»ÑÑÐ¸ÑÐµ: **{pkg['credits']} ð·**\n\n"
        f"ÐÐµÑÐµÐ²ÐµÐ´Ð¸ÑÐµ ÑÑÐ¼Ð¼Ñ Ð½Ð° Ð¢-ÐÐ°Ð½Ðº / Ð¡ÐÐÐ  Ð¿Ð¾ Ð½Ð¾Ð¼ÐµÑÑ:\n"
        f"`+79192329005`\n\n"
        f"âï¸ **Ð£ÐºÐ°Ð¶Ð¸ÑÐµ Ð² ÐºÐ¾Ð¼Ð¼ÐµÐ½ÑÐ°ÑÐ¸Ð¸ Ðº Ð¿ÐµÑÐµÐ²Ð¾Ð´Ñ Ð²Ð°Ñ Telegram ID:**\n"
        f"`{chat_id}`\n\n"
        f"ÐÐ¾ÑÐ»Ðµ Ð¿ÐµÑÐµÐ²Ð¾Ð´Ð° ð· Ð½Ð°ÑÐ¸ÑÐ»ÑÑÑÑ Ð²ÑÑÑÐ½ÑÑ Ð² ÑÐµÑÐµÐ½Ð¸Ðµ 15 Ð¼Ð¸Ð½ÑÑ.",
        parse_mode="HTML",
    )
    bot.answer_callback_query(call.id, "Ð ÐµÐºÐ²Ð¸Ð·Ð¸ÑÑ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½Ñ")
    try:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"â ÐÐ°ÑÐ¸ÑÐ»Ð¸ÑÑ {pkg['credits']}ð·", callback_data=f"admin_grant_{chat_id}_{pkg_key}"))
        bot.send_message(
            ADMIN_ID,
            f"ð³ **ÐÐ°Ð¿ÑÐ¾Ñ Ð½Ð° Ð¾Ð¿Ð»Ð°ÑÑ ÐºÐ°ÑÑÐ¾Ð¹**\n\n"
            f"ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ: {username}\n"
            f"ID: `{chat_id}`\n"
            f"ÐÐ°ÐºÐµÑ: **{pkg['name']}**\n"
            f"Ð¡ÑÐ¼Ð¼Ð°: {pkg['price_rub']} â½\n"
            f"ð·: {pkg['credits']}",
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception as e:
        logging.error(f"Admin notify error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_grant_"))
def admin_grant_credits(call):
    bot.answer_callback_query(call.id)
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "ÐÐµÑ Ð´Ð¾ÑÑÑÐ¿Ð°")
        return
    parts = call.data.split("_")
    if len(parts) < 4:
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð´Ð°Ð½Ð½ÑÑ")
        return
    target_id = int(parts[2])
    pkg_key = parts[3]
    pkg = PACKAGES.get(pkg_key)
    if not pkg:
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð¿Ð°ÐºÐµÑÐ°")
        return
    with data_lock:
        user_credits[target_id] = user_credits.get(target_id, 0) + pkg["credits"]
        user_credit_history[target_id].append((time.time(), pkg["credits"], f"ÐÐ¾ÐºÑÐ¿ÐºÐ° Ð¿Ð°ÐºÐµÑÐ° {pkg['name']} (ÐºÐ°ÑÑÐ°)"))
        save_data()
    bot.answer_callback_query(call.id, f"ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¾ {pkg['credits']} ð·")
    bot.edit_message_text(
        f"â **ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¾**\nÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ {target_id}: +{pkg['credits']} ð·",
        call.message.chat.id,
        call.message.message_id,
    )
    try:
        bot.send_message(target_id, f"ð ÐÐ´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾Ñ Ð½Ð°ÑÐ¸ÑÐ»Ð¸Ð» Ð²Ð°Ð¼ {pkg['credits']} ð· (Ð¿Ð°ÐºÐµÑ Â«{pkg['name']}Â»).\nÐÐ°Ñ Ð±Ð°Ð»Ð°Ð½Ñ: {user_credits[target_id]} ð·")
    except Exception as e:
        logging.error(f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ²ÐµÐ´Ð¾Ð¼Ð¸ÑÑ {target_id}: {e}")

@bot.message_handler(commands=["paysupport"])
def pay_support(message):
    bot.send_message(message.chat.id, "ÐÐ¾Ð·Ð²ÑÐ°Ñ ÑÑÐµÐ´ÑÑÐ² Ð¾ÑÑÑÐµÑÑÐ²Ð»ÑÐµÑÑÑ Ð² ÑÐµÑÐµÐ½Ð¸Ðµ 24 ÑÐ°ÑÐ¾Ð². ÐÐ»Ñ Ð·Ð°Ð¿ÑÐ¾ÑÐ° Ð²Ð¾Ð·Ð²ÑÐ°ÑÐ° ÑÐ²ÑÐ¶Ð¸ÑÐµÑÑ Ñ @Jastick_bot.")

# ================== ADMIN ==================
@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if message.chat.id != ADMIN_ID:
        return
    with data_lock:
        total_credits = sum(user_credits.values())
        text = f"ð ÐÐ´Ð¼Ð¸Ð½-Ð¿Ð°Ð½ÐµÐ»Ñ\nÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÐµÐ¹: {len(user_credits)}\nð· Ð²ÑÐµÐ³Ð¾: {total_credits}\n\nÐÐ¾Ð¼Ð°Ð½Ð´Ñ:\n/addcredits <uid> <amount>\n/removecredits <uid> <amount>"
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
            user_credit_history[uid].append((time.time(), amt, "ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¸Ðµ Ð°Ð´Ð¼Ð¸Ð½Ð¾Ð¼"))
            save_data()
        current_balance = user_credits[uid]
        history_count = len(user_credit_history[uid])
        confirm_text = (
            f"â **ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¸Ðµ Ð²ÑÐ¿Ð¾Ð»Ð½ÐµÐ½Ð¾**\n\n"
            f"ð¤ ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ: `{uid}`\n"
            f"â ÐÐ°ÑÐ¸ÑÐ»ÐµÐ½Ð¾: {amt} ð·\n"
            f"ð° Ð¢ÐµÐºÑÑÐ¸Ð¹ Ð±Ð°Ð»Ð°Ð½Ñ: {current_balance} ð·\n"
            f"ð ÐÑÐµÐ³Ð¾ Ð¾Ð¿ÐµÑÐ°ÑÐ¸Ð¹: {history_count}"
        )
        bot.send_message(message.chat.id, confirm_text, parse_mode="HTML")
        try:
            bot.send_message(uid, f"ð ÐÐ´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾Ñ Ð½Ð°ÑÐ¸ÑÐ»Ð¸Ð» Ð²Ð°Ð¼ {amt} ð·.\nÐÐ°Ñ Ð±Ð°Ð»Ð°Ð½Ñ: {current_balance} ð·")
        except Exception as e:
            logging.error(f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ²ÐµÐ´Ð¾Ð¼Ð¸ÑÑ {uid}: {e}")
    except Exception:
        bot.send_message(message.chat.id, "Ð¤Ð¾ÑÐ¼Ð°Ñ: /addcredits <uid> <amount>")

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
                user_credit_history[uid].append((time.time(), -amt, "Ð¡Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð°Ð´Ð¼Ð¸Ð½Ð¾Ð¼"))
                save_data()
                bot.send_message(message.chat.id, f"â Ð¡Ð¿Ð¸ÑÐ°Ð½Ð¾ {amt} ð· Ñ {uid}\nÐ¢ÐµÐºÑÑÐ¸Ð¹ Ð±Ð°Ð»Ð°Ð½Ñ: {user_credits[uid]} ð·")
                try:
                    bot.send_message(uid, f"â¹ï¸ ÐÐ´Ð¼Ð¸Ð½Ð¸ÑÑÑÐ°ÑÐ¾Ñ ÑÐ¿Ð¸ÑÐ°Ð» {amt} ð·. ÐÐ°Ð»Ð°Ð½Ñ: {user_credits[uid]}")
                except Exception as e:
                    logging.error(f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ²ÐµÐ´Ð¾Ð¼Ð¸ÑÑ {uid}: {e}")
            else:
                bot.send_message(message.chat.id, "ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ð·")
    except Exception as e:
        logging.error(f"Remove credits error: {e}")
        bot.send_message(message.chat.id, "Ð¤Ð¾ÑÐ¼Ð°Ñ: /removecredits <uid> <amount>")

# ================== START & MENU ==================
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    send_main_menu(chat_id, "ð ÐÑÐ¸Ð²ÐµÑ! Ð¯ ÑÐ¼ÐµÑ Ð³ÐµÐ½ÐµÑÐ¸ÑÐ¾Ð²Ð°ÑÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ñ, ÑÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÑÐ¾ÑÐ¾, ÑÐ½Ð¸Ð¼Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾ Kling 3.0 Ð² ÑÐ´Ð¾Ð±Ð½Ð¾Ð¹ Web-Ð¡ÑÑÐ´Ð¸Ð¸, Ð° Ð² ÑÐµÐ¶Ð¸Ð¼Ðµ Â«Ð§Ð°ÑÂ» ÑÐ°Ð±Ð¾ÑÐ°Ñ ÐºÐ°Ðº Ð¿Ð¾Ð»Ð½Ð¾ÑÐµÐ½Ð½ÑÐ¹ ÐÐ-Ð°Ð³ÐµÐ½Ñ. ÐÑÐ±ÐµÑÐ¸ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ Ð½Ð¸Ð¶Ðµ.")

def send_main_menu(chat_id, text="ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ:"):
    bot.send_message(chat_id, text, reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.text == "ð¼ Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ")
def menu_generate_image(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_model_generate"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("ð Flux (2ð·)", callback_data="gen_flux"),
        InlineKeyboardButton("ð¨ Seedream (2ð·)", callback_data="gen_seedream"),
    )
    bot.send_message(message.chat.id, "ÐÑÐ±ÐµÑÐ¸ Ð¼Ð¾Ð´ÐµÐ»Ñ Ð´Ð»Ñ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "ð¨ Ð ÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°ÑÑ ÑÐ¾ÑÐ¾")
def menu_edit_photo(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_model_edit"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("ð Flux (3ð·)", callback_data="edit_flux"),
        InlineKeyboardButton("ð¨ Seedream (3ð·)", callback_data="edit_seedream"),
    )
    bot.send_message(message.chat.id, "ÐÑÐ±ÐµÑÐ¸ Ð¼Ð¾Ð´ÐµÐ»Ñ ÑÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ñ:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "ð¥ Ð¡Ð¾Ð·Ð´Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾")
def menu_video(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = "select_video_mode"
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
    studio_url = f"https://{host}/studio" if host else ""
    markup = InlineKeyboardMarkup(row_width=1)
    if studio_url:
        markup.add(InlineKeyboardButton("â¨ Kling 3.0 ÐÐ¸Ð´ÐµÐ¾-Ð¡ÑÑÐ´Ð¸Ñ [ÐÐ¾ÐºÐ°Ð´ÑÐ¾Ð²ÑÐ¹ Web App]", web_app=WebAppInfo(url=studio_url)))
    markup.add(
        InlineKeyboardButton("ð Ð¢ÐµÐºÑÑ Ð² Ð²Ð¸Ð´ÐµÐ¾ (ÐÐ±ÑÑÐ½ÑÐ¹ Ð¿ÑÐ¾Ð¼Ð¿Ñ)", callback_data="vid_text"),
        InlineKeyboardButton("ð¬ ÐÑÐ»ÑÑÐ¸ÑÑÐµÐ½Ð° ÑÐµÑÐµÐ· Ð´Ð¸Ð°Ð»Ð¾Ð³ Ð±Ð¾ÑÐ°", callback_data="vid_multi"),
        InlineKeyboardButton("ð¼ ÐÐ°ÑÑÐ¸Ð½ÐºÐ° Ð² Ð²Ð¸Ð´ÐµÐ¾ (ÐÐ¶Ð¸Ð²Ð»ÐµÐ½Ð¸Ðµ ÑÐ¾ÑÐ¾)", callback_data="vid_image"),
    )
    bot.send_message(message.chat.id, "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð¸Ð½ÑÑÑÑÐ¼ÐµÐ½Ñ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸ Ð²Ð¸Ð´ÐµÐ¾:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "ð¬ Ð¡Ð¿ÑÐ¾ÑÐ¸ÑÑ (ÑÐ°Ñ)")
def menu_chat(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    user_state[chat_id] = None
    bot.send_message(message.chat.id, "ð¤ Ð ÐµÐ¶Ð¸Ð¼ ÐÐ-Ð°Ð³ÐµÐ½ÑÐ° Ð°ÐºÑÐ¸Ð²Ð¸ÑÐ¾Ð²Ð°Ð½!\nÐ¯ Ð¿Ð¾Ð¼Ð½Ñ ÐºÐ¾Ð½ÑÐµÐºÑÑ Ð´Ð¸Ð°Ð»Ð¾Ð³Ð°, Ð³ÑÐ³Ð»Ñ Ð¸Ð½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ñ, ÑÐ¸ÑÐ°Ñ ÑÑÑÐ»ÐºÐ¸, ÑÐ¸ÑÑÑ Ð°ÑÑÑ Ð¸ ÑÐ½Ð¸Ð¼Ð°Ñ Ð¼Ð¸Ð½Ð¸-ÑÐ¸Ð»ÑÐ¼Ñ. ÐÐ°Ð¶Ð´ÑÐµ 50 ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸Ð¹ ÑÐ¿Ð¸ÑÑÐ²Ð°ÐµÑÑÑ 1 ð·.", reply_markup=back_keyboard())

@bot.message_handler(func=lambda m: m.text == "ð¤ ÐÑÐ¾ÑÐ¸Ð»Ñ")
def menu_profile(message):
    user_last_activity[message.chat.id] = time.time()
    profile(message)

@bot.message_handler(func=lambda m: m.text == "ð ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ")
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

# ================== GENERATE IMAGE HANDLERS ==================
@bot.callback_query_handler(func=lambda call: call.data in ("gen_flux", "gen_seedream"))
def select_generate_model(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "gen_flux":
        user_generate_model[chat_id] = "flux"
    else:
        user_generate_model[chat_id] = "seedream"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("16:9", callback_data="gen_aspect_16_9"),
        InlineKeyboardButton("9:16", callback_data="gen_aspect_9_16"),
        InlineKeyboardButton("1:1", callback_data="gen_aspect_1_1"),
        InlineKeyboardButton("4:3", callback_data="gen_aspect_4_3"),
    )
    bot.edit_message_text("ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÐ¾ÑÐ¼Ð°Ñ ÐºÐ°Ð´ÑÐ°:", chat_id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("gen_aspect_"))
def set_generate_aspect(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    asp = call.data.split("_", 2)[2].replace("_", ":")
    user_generate_aspect[chat_id] = asp
    user_state[chat_id] = "awaiting_generate_prompt"
    bot.send_message(chat_id, "âï¸ ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð´Ð»Ñ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ñ:", reply_markup=back_keyboard())

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
            bot.send_message(chat_id, f"â ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ð·. ÐÑÐ¶Ð½Ð¾ {cost}, Ñ Ð²Ð°Ñ {user_credits.get(chat_id, 0)}.")
            send_main_menu(chat_id)
            return
        if chat_id != ADMIN_ID:
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"ÐÐµÐ½ÐµÑÐ°ÑÐ¸Ñ {model} {aspect}"))
            save_data()
    bot.send_message(chat_id, "ð¨ ÐÐµÐ½ÐµÑÐ¸ÑÑÑ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ...")
    full_p = f"{prompt}. {ASPECT_PROMPTS.get(aspect, '')}" if aspect in ASPECT_PROMPTS else prompt
    if model == "flux":
        img_bytes = generate_image_flux(full_p)
    else:
        img_bytes = generate_image_seedream(full_p)
    if img_bytes:
        out_b, _ = _prepare_image_bytes(img_bytes)
        bot.send_photo(chat_id, out_b or img_bytes, caption=f"ð¨ ÐÐ¾ÑÐ¾Ð²Ð¾! ({aspect})")
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                save_data()
        bot.send_message(chat_id, "â ÐÑÐ¸Ð±ÐºÐ° Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ð¸. ð· Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ.")
    user_state.pop(chat_id, None)
    user_generate_model.pop(chat_id, None)
    user_generate_aspect.pop(chat_id, None)

# ================== EDIT PHOTO HANDLERS ==================
@bot.callback_query_handler(func=lambda call: call.data in ("edit_flux", "edit_seedream"))
def select_edit_model(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "edit_flux":
        user_edit_model[chat_id] = "flux"
    else:
        user_edit_model[chat_id] = "seedream"
    user_state[chat_id] = "awaiting_edit_photo"
    bot.edit_message_text("ð¸ ÐÐ°Ð³ÑÑÐ·Ð¸ÑÐµ ÑÐ¾ÑÐ¾ Ð´Ð»Ñ ÑÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ñ:", chat_id, call.message.message_id)
    bot.send_message(chat_id, "ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ ÑÐ¾ÑÐ¾:", reply_markup=back_keyboard())

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
        InlineKeyboardButton("â Ð¡Ð¾ÑÑÐ°Ð½Ð¸ÑÑ Ð»Ð¸ÑÐ¾", callback_data="edit_face_on"),
        InlineKeyboardButton("â ÐÐ±ÑÑÐ½Ð¾Ðµ", callback_data="edit_face_off"),
    )
    bot.send_message(chat_id, "Ð¡Ð¾ÑÑÐ°Ð½Ð¸ÑÑ ÑÐµÑÑÑ Ð»Ð¸ÑÐ° ÑÐµÐ»Ð¾Ð²ÐµÐºÐ°?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ("edit_face_on", "edit_face_off"))
def set_edit_face_mode(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    user_face_mode[chat_id] = (call.data == "edit_face_on")
    user_state[chat_id] = "awaiting_edit_prompt"
    bot.send_message(chat_id, "âï¸ ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð¸Ð·Ð¼ÐµÐ½ÐµÐ½Ð¸Ð¹:\n(Ð½Ð°Ð¿ÑÐ¸Ð¼ÐµÑ: Â«ÑÐ´ÐµÐ»Ð°Ð¹ ÐºÐ¸Ð±ÐµÑÐ¿Ð°Ð½Ðº ÑÐ¾Ð½, Ð½ÐµÐ¾Ð½Ð¾Ð²ÑÐ¹ ÑÐ²ÐµÑÂ»)", reply_markup=back_keyboard())

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
        bot.send_message(chat_id, "â Ð¤Ð¾ÑÐ¾ Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾. ÐÐ°ÑÐ½Ð¸ÑÐµ Ð·Ð°Ð½Ð¾Ð²Ð¾.")
        send_main_menu(chat_id)
        return
    with data_lock:
        if chat_id != ADMIN_ID and user_credits.get(chat_id, 0) < cost:
            bot.send_message(chat_id, f"â ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ð·. ÐÑÐ¶Ð½Ð¾ {cost}.")
            send_main_menu(chat_id)
            return
        if chat_id != ADMIN_ID:
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Ð ÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ðµ {model}"))
            save_data()
    bot.send_message(chat_id, "ð¨ Ð ÐµÐ´Ð°ÐºÑÐ¸ÑÑÑ ÑÐ¾ÑÐ¾...")
    if face_mode:
        prompt = f"Keep the person's face exactly the same, only change the environment, clothing, background, lighting or style according to: {prompt}"
    if model == "flux":
        img_bytes, err = edit_image_flux(prompt, b64)
    else:
        img_bytes, err = edit_image_seedream(prompt, b64)
    if img_bytes:
        out_b, _ = _prepare_image_bytes(img_bytes)
        bot.send_photo(chat_id, out_b or img_bytes, caption="ð¨ ÐÐ¾ÑÐ¾Ð²Ð¾!")
    else:
        with data_lock:
            if chat_id != ADMIN_ID:
                user_credits[chat_id] += cost
                save_data()
        bot.send_message(chat_id, f"â ÐÑÐ¸Ð±ÐºÐ° ÑÐµÐ´Ð°ÐºÑÐ¸ÑÐ¾Ð²Ð°Ð½Ð¸Ñ: {err}. ð· Ð²Ð¾Ð·Ð²ÑÐ°ÑÐµÐ½Ñ.")
    user_state.pop(chat_id, None)
    user_edit_model.pop(chat_id, None)
    user_face_mode.pop(chat_id, None)
    user_pending_photo.pop(chat_id, None)

# ================== CALLBACKS (VIDEO) ==================
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
        bot.answer_callback_query(call.id, f"ÐÑÐ±ÑÐ°Ð½Ð° Ð¼Ð¾Ð´ÐµÐ»Ñ: {model_key}")
        bot.delete_message(chat_id, call.message.message_id)
        if user_video_mode.get(chat_id) == "image_one":
            user_state[chat_id] = "awaiting_video_image_first"
            bot.send_message(chat_id, "ð¸ ÐÐ°Ð³ÑÑÐ·Ð¸ÑÐµ ÐÐÐ ÐÐ«Ð ÐºÐ°Ð´Ñ (Ð½Ð°ÑÐ°Ð»ÑÐ½Ð¾Ðµ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ):", reply_markup=back_keyboard())
        else:
            start_video_param_selection(chat_id)
    else:
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð²ÑÐ±Ð¾ÑÐ° Ð¼Ð¾Ð´ÐµÐ»Ð¸")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_dur_"))
def set_video_duration(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    duration = int(call.data.split("_")[-1])
    user_video_params[chat_id]["duration"] = duration
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"ÐÐ»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ: {duration} ÑÐµÐº")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_res_"))
def set_video_resolution(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    resolution = call.data.split("_")[-1]
    user_video_params[chat_id]["resolution"] = resolution
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Ð Ð°Ð·ÑÐµÑÐµÐ½Ð¸Ðµ: {resolution}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_aspect_"))
def set_video_aspect(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    aspect = call.data.split("_", 2)[2].replace("_", ":")
    user_video_params[chat_id]["aspect_ratio"] = aspect
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"Ð¤Ð¾ÑÐ¼Ð°Ñ: {aspect}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vid_audio_"))
def set_video_audio(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    audio = call.data.split("_")[-1] == "true"
    user_video_params[chat_id]["audio"] = audio
    bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=video_params_keyboard(chat_id))
    bot.answer_callback_query(call.id, f"ÐÐ²ÑÐº: {'Ð²ÐºÐ»ÑÑÑÐ½' if audio else 'Ð²ÑÐºÐ»ÑÑÐµÐ½'}")

@bot.callback_query_handler(func=lambda call: call.data == "vid_params_done")
def video_params_done(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.delete_message(chat_id, call.message.message_id)
    params = user_video_params.get(chat_id, {})
    params.setdefault("duration", 5)
    params.setdefault("resolution", "480p")
    params.setdefault("audio", True)
    params.setdefault("aspect_ratio", "16:9")
    user_video_params[chat_id] = params
    if user_video_mode.get(chat_id) == "multi":
        user_state[chat_id] = "awaiting_video_multi_prompt"
        bot.send_message(
            chat_id,
            "ð¬ <b>Ð¨Ð°Ð³ 1 Ð¸Ð· 2: Ð¡ÑÐµÐ½Ð°ÑÐ¸Ð¹ (Kling 3.0 Pro)</b>\n\n"
            "ÐÐ¿Ð¸ÑÐ¸ÑÐµ ÑÑÐ¶ÐµÑ ÑÐ¾Ð»Ð¸ÐºÐ° Ð¿Ð¾ Ð¿Ð¾ÑÐ»ÐµÐ´Ð¾Ð²Ð°ÑÐµÐ»ÑÐ½ÑÐ¼ ÑÑÐµÐ½Ð°Ð¼. ÐÐ°Ð¶Ð´ÑÑ ÑÑÐµÐ½Ñ Ð¿Ð¸ÑÐ¸ÑÐµ Ñ Ð½Ð¾Ð²Ð¾Ð¹ ÑÑÑÐ¾ÐºÐ¸ Ð² ÑÐ¾ÑÐ¼Ð°ÑÐµ:\n"
            "<code>[ÑÐµÐºÑÐ½Ð´Ñ] ÐÐ¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ñ Ð² ÐºÐ°Ð´ÑÐµ</code>\n\n"
            "ð <b>ÐÑÐ¸Ð¼ÐµÑ (Ð¾Ð±ÑÐ°Ñ ÑÑÐ¼Ð¼Ð° 10 ÑÐµÐº):</b>\n"
            "<code>3 ÐÑÑÐ¿Ð½ÑÐ¹ Ð¿Ð»Ð°Ð½: ÑÑÑÐ°ÑÑ Ð² ÑÐ¸ÑÑÑÐ¸Ñ Ð´Ð¾ÑÐ¿ÐµÑÐ°Ñ ÑÐ¼Ð¾ÑÑÐ¸Ñ Ð½Ð° Ð·Ð°Ð¼Ð¾Ðº</code>\n"
            "<code>4 Ð¡ÑÐµÐ´Ð½Ð¸Ð¹ Ð¿Ð»Ð°Ð½: Ð¾Ð½ Ð´Ð¾ÑÑÐ°ÐµÑ Ð¼ÐµÑ Ð¸Ð· Ð½Ð¾Ð¶ÐµÐ½ Ð¿Ð¾Ð´ ÑÐ°ÑÐºÐ°ÑÑ Ð³ÑÐ¾Ð¼Ð°</code>\n"
            "<code>3 ÐÐ±ÑÐ¸Ð¹ Ð¿Ð»Ð°Ð½: Ð¼Ð¾Ð»Ð½Ð¸Ñ ÑÐ´Ð°ÑÑÐµÑ Ð² Ð³Ð»Ð°Ð²Ð½ÑÑ Ð±Ð°ÑÐ½Ñ Ð·Ð°Ð¼ÐºÐ°</code>\n\n"
            "âï¸ <i>ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð²Ð°Ñ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹:</i>",
            parse_mode="HTML",
            reply_markup=back_keyboard()
        )
    else:
        user_state[chat_id] = "awaiting_video_prompt"
        bot.send_message(chat_id, "âï¸ Ð¢ÐµÐ¿ÐµÑÑ Ð²Ð²ÐµÐ´Ð¸ÑÐµ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ (Ð¿ÑÐ¾Ð¼Ð¿Ñ) Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾:", reply_markup=back_keyboard())

@bot.callback_query_handler(func=lambda call: call.data in ("vid_text", "vid_image", "vid_multi"))
def select_video_mode(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    data = call.data
    if data == "vid_text":
        user_video_mode[chat_id] = "text"
        user_video_frames[chat_id] = {"first": None, "last": None}
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "ð¥ ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð²Ð¸Ð´ÐµÐ¾Ð¼Ð¾Ð´ÐµÐ»Ñ:", reply_markup=video_model_keyboard())
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
        bot.send_message(chat_id, "ð¥ ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð²Ð¸Ð´ÐµÐ¾Ð¼Ð¾Ð´ÐµÐ»Ñ:", reply_markup=video_model_keyboard())

# --- MULTI-SCENE 9 PHOTOS HANDLERS ---
def launch_multi_video_task(chat_id):
    params = user_video_params.get(chat_id, {})
    multi_prompt = params.get("multi_prompt_data", [])
    photos = user_video_frames.get(chat_id, {}).get("multi_list", [])
    logging.info(f"=== LAUNCH MULTI VIDEO {chat_id}: {len(photos)} ref images ===")
    Thread(target=generate_video_async, args=(chat_id, None, None, None, multi_prompt, photos), daemon=True).start()

@bot.callback_query_handler(func=lambda call: call.data == "run_multi_video")
def run_multi_video_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.delete_message(chat_id, call.message.message_id)
    user_state[chat_id] = None
    bot.send_message(chat_id, "ð¬ ÐÑÐ»Ð¸ÑÐ½Ð¾! ÐÐµÑÐµÐ´Ð°Ñ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹ Ð¸ ÑÐ¾ÑÐ¾ Ð² Kling 3.0 Pro...")
    launch_multi_video_task(chat_id)

@bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_multi_photos")
def handle_multi_photos_upload(message):
    chat_id = message.chat.id
    user_last_activity[chat_id] = time.time()
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    b64 = base64.b64encode(downloaded).decode("utf-8")
    if chat_id not in user_video_frames:
        user_video_frames[chat_id] = {}
    photos = user_video_frames[chat_id].get("multi_list", [])
    if len(photos) < 9:
        photos.append(b64)
        user_video_frames[chat_id]["multi_list"] = photos
    count = len(photos)
    status_msg_id = user_video_params.get(chat_id, {}).get("multi_status_msg_id")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"â¶ï¸ ÐÐ°Ð¿ÑÑÑÐ¸ÑÑ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ñ (ÐÐ°Ð³ÑÑÐ¶ÐµÐ½Ð¾: {count}/9 ÑÐ¾ÑÐ¾)", callback_data="run_multi_video"))
    if status_msg_id:
        try:
            bot.edit_message_reply_markup(chat_id, status_msg_id, reply_markup=markup)
        except Exception:
            pass
    if count >= 9:
        user_state[chat_id] = None
        bot.send_message(chat_id, "â ÐÐ°Ð³ÑÑÐ¶ÐµÐ½ Ð¼Ð°ÐºÑÐ¸Ð¼ÑÐ¼ (9 ÑÐ¾ÑÐ¾). ÐÐ°Ð¿ÑÑÐºÐ°Ñ ÑÐµÐ¶Ð¸ÑÑÐµÑÑÐºÑÑ Ð³ÐµÐ½ÐµÑÐ°ÑÐ¸Ñ...")
        launch_multi_video_task(chat_id)

# ================== VIDEO IMAGE FRAME HANDLERS ==================
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
        InlineKeyboardButton("ð¸ ÐÐ¾Ð±Ð°Ð²Ð¸ÑÑ Ð¿Ð¾ÑÐ»ÐµÐ´Ð½Ð¸Ð¹ ÐºÐ°Ð´Ñ", callback_data="add_last_frame"),
        InlineKeyboardButton("â¶ï¸ ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð¸ÑÑ Ð±ÐµÐ· Ð½ÐµÐ³Ð¾", callback_data="skip_last_frame"),
    )
    bot.send_message(chat_id, "â ÐÐµÑÐ²ÑÐ¹ ÐºÐ°Ð´Ñ Ð·Ð°Ð³ÑÑÐ¶ÐµÐ½. ÐÐ¾Ð±Ð°Ð²Ð¸ÑÑ ÑÐ¸Ð½Ð°Ð»ÑÐ½ÑÐ¹ ÐºÐ°Ð´Ñ?", reply_markup=markup)
    user_state[chat_id] = "awaiting_video_image_choice"

@bot.callback_query_handler(func=lambda call: call.data in ("add_last_frame", "skip_last_frame"))
def handle_last_frame_choice(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "add_last_frame":
        user_state[chat_id] = "awaiting_video_image_last"
        bot.send_message(chat_id, "ð¸ ÐÐ°Ð³ÑÑÐ·Ð¸ÑÐµ ÐÐÐ¡ÐÐÐÐÐÐ ÐºÐ°Ð´Ñ (ÑÐ¸Ð½Ð°Ð»ÑÐ½Ð¾Ðµ Ð¸Ð·Ð¾Ð±ÑÐ°Ð¶ÐµÐ½Ð¸Ðµ):", reply_markup=back_keyboard())
    else:
        user_state[chat_id] = "awaiting_video_prompt"
        bot.send_message(chat_id, "âï¸ ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ (Ð¿ÑÐ¾Ð¼Ð¿Ñ) Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾:", reply_markup=back_keyboard())
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
    bot.send_message(chat_id, "â ÐÐ¾ÑÐ»ÐµÐ´Ð½Ð¸Ð¹ ÐºÐ°Ð´Ñ Ð·Ð°Ð³ÑÑÐ¶ÐµÐ½.\nâï¸ ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ (Ð¿ÑÐ¾Ð¼Ð¿Ñ) Ð´Ð»Ñ Ð²Ð¸Ð´ÐµÐ¾:", reply_markup=back_keyboard())

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
        bot.send_message(chat_id, "â ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°ÑÑ ÑÑÐµÐ½Ð°ÑÐ¸Ð¹. ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ÑÐµ ÐµÑÐµ ÑÐ°Ð·.")
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
    markup.add(InlineKeyboardButton("â¶ï¸ Ð¡Ð³ÐµÐ½ÐµÑÐ¸ÑÐ¾Ð²Ð°ÑÑ Ð²Ð¸Ð´ÐµÐ¾ Ð±ÐµÐ· ÑÐ¾ÑÐ¾", callback_data="run_multi_video"))
    msg = bot.send_message(
        chat_id,
        "ð¸ <b>Ð¨Ð°Ð³ 2 Ð¸Ð· 2: Ð ÐµÑÐµÑÐµÐ½ÑÑ ÑÑÐ¸Ð»Ñ (Ð¾Ñ 0 Ð´Ð¾ 9 ÑÐ¾ÑÐ¾)</b>\n\n"
        "ÐÑÐ¸ÐºÑÐµÐ¿Ð¸ÑÐµ ÐºÐ°ÑÑÐ¸Ð½ÐºÐ¸, ÐºÐ¾ÑÐ¾ÑÑÐµ Kling 3.0 Ð²Ð¾Ð·ÑÐ¼ÐµÑ Ð·Ð° Ð²Ð¸Ð·ÑÐ°Ð»ÑÐ½ÑÑ Ð¾ÑÐ½Ð¾Ð²Ñ:\n"
        "â¢ 1-Ðµ ÑÐ¾ÑÐ¾ ÑÑÐ°Ð½ÐµÑ Ð½Ð°ÑÐ°Ð»ÑÐ½ÑÐ¼ ÐºÐ°Ð´ÑÐ¾Ð¼.\n"
        "â¢ ÐÐ¾ÑÐ»ÐµÐ´Ð½ÐµÐµ ÑÐ¾ÑÐ¾ â ÑÐ¸Ð½Ð°Ð»ÑÐ½ÑÐ¼ ÐºÐ°Ð´ÑÐ¾Ð¼.\n"
        "â¢ ÐÑÑÐ°Ð»ÑÐ½ÑÐµ ÑÐ¾ÑÐ¾ Ð·Ð°Ð´Ð°Ð´ÑÑ ÑÑÐ¸Ð»Ñ Ð¿ÐµÑÑÐ¾Ð½Ð°Ð¶ÐµÐ¹ Ð¸ Ð¾ÐºÑÑÐ¶ÐµÐ½Ð¸Ñ.\n\n"
        "<i>ÐÑÐ¿ÑÐ°Ð²Ð»ÑÐ¹ÑÐµ ÑÐ¾ÑÐ¾ Ð¿Ð¾ Ð¾Ð´Ð½Ð¾Ð¼Ñ Ð¸Ð»Ð¸ ÑÑÐ°Ð·Ñ Ð°Ð»ÑÐ±Ð¾Ð¼Ð¾Ð¼ Ð¸Ð· Ð½ÐµÑÐºÐ¾Ð»ÑÐºÐ¸Ñ ÑÑÑÐº. ÐÐ¾Ð³Ð´Ð° Ð·Ð°Ð³ÑÑÐ·Ð¸ÑÐµ Ð²ÑÑ Ð½ÑÐ¶Ð½Ð¾Ðµ â Ð½Ð°Ð¶Ð¼Ð¸ÑÐµ ÐºÐ½Ð¾Ð¿ÐºÑ Ð½Ð¸Ð¶Ðµ:</i>",
        parse_mode="HTML",
        reply_markup=markup
    )
    user_video_params[chat_id]["multi_status_msg_id"] = msg.message_id

# ================== WEBHOOK & FLASK STUDIO ENDPOINTS ==================
@app.route("/")
def index():
    return "Bot is running"

@app.route("/health")
def health():
    return "OK", 200

@app.route("/studio")
def studio_page():
    return WEBAPP_HTML

@app.route("/api/webapp_submit_video", methods=["POST"])
def webapp_submit_video():
    data = request.json
    uid = int(data.get("user_id", 0))
    scenes = data.get("scenes", [])
    asp = data.get("aspect_ratio", "16:9")
    if not uid or not scenes:
        return jsonify({"ok": False, "error": "ÐÐµÐ²ÐµÑÐ½ÑÐµ Ð´Ð°Ð½Ð½ÑÐµ ÑÐ¾ÑÐ¼Ñ"}), 400
    total_dur = sum(int(s.get("duration", 3)) for s in scenes)
    cost = total_dur * 5
    with data_lock:
        if uid != ADMIN_ID and user_credits.get(uid, 0) < cost:
            return jsonify({"ok": False, "error": f"ÐÐµÐ´Ð¾ÑÑÐ°ÑÐ¾ÑÐ½Ð¾ ÑÐ¾ÐºÐµÐ½Ð¾Ð² ð·. ÐÑÐ¶Ð½Ð¾ {cost}, Ñ Ð²Ð°Ñ {user_credits.get(uid, 0)}."}), 400
        if uid != ADMIN_ID:
            user_credits[uid] -= cost
            user_credit_history[uid].append((time.time(), -cost, f"Ð¡ÑÑÐ´Ð¸Ñ Kling {total_dur}Ñ"))
            save_data()
    try:
        bot.send_message(
            uid,
            f"ð¬ <b>ÐÐ°ÐºÐ°Ð· Ð¸Ð· ÐÐ¸Ð·ÑÐ°Ð»ÑÐ½Ð¾Ð¹ Ð¡ÑÑÐ´Ð¸Ð¸ Ð¿ÑÐ¸Ð½ÑÑ!</b>\nÐ¡ÑÐ¶ÐµÑ Ð¸Ð· {len(scenes)} ÐºÐ°Ð´ÑÐ¾Ð² ({total_dur} ÑÐµÐº).\nÐÐ°Ð¿ÑÑÐºÐ°Ñ ÑÐµÐ½Ð´ÐµÑ Kling 3.0 Pro...",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¾ÑÐ¿ÑÐ°Ð²Ð¸ÑÑ ÑÐ²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ðµ ÑÐ·ÐµÑÑ {uid}: {e}")
    user_video_model[uid] = "kwaivgi/kling-v3.0-pro"
    user_video_params[uid] = {"duration": total_dur, "aspect_ratio": asp, "audio": True}
    Thread(target=generate_video_async, args=(uid, None, None, None, scenes), daemon=True).start()
    return jsonify({"ok": True})

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if request.is_json:
        try:
            json_data = request.get_json()
            update = telebot.types.Update.de_json(json_data)
            Thread(target=bot.process_new_updates, args=([update],), daemon=True).start()
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
            logging.info("â Webhook OK")
        else:
            logging.error("â Webhook FAILED")
    except Exception as e:
        logging.error(f"â Webhook exception: {e}")

Thread(target=set_webhook, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port)
