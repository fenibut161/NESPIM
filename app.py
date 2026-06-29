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

# --- WEB APP HTML (полноценная видео-студия: storyboard + refs до 9) ---
WEBAPP_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <title>Moon Web Studio</title>
    <style>
        :root { --bg-color: var(--tg-theme-bg-color, #101014); --text-color: var(--tg-theme-text-color, #ffffff); --hint-color: var(--tg-theme-hint-color, #9ca3af); --btn-color: var(--tg-theme-button-color, #3b82f6); --btn-text: var(--tg-theme-button-text-color, #ffffff); --sec-bg: var(--tg-theme-secondary-bg-color, #1f1f27); --danger:#ef4444; --ok:#22c55e; }
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-color); color: var(--text-color); margin: 0; padding: 16px; padding-bottom: 104px; }
        .header { text-align: center; margin-bottom: 18px; }
        .header h1 { font-size: 22px; margin: 0; font-weight: 800; }
        .header p { font-size: 13px; color: var(--hint-color); margin: 6px 0 0 0; line-height: 1.35; }
        .card { background: var(--sec-bg); border-radius: 16px; padding: 16px; margin-bottom: 16px; }
        .card-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; display: flex; justify-content: space-between; gap: 8px; align-items: center; }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
        .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
        .btn { background: rgba(255,255,255,0.06); border: 2px solid transparent; color: var(--text-color); padding: 10px 8px; border-radius: 12px; text-align: center; font-size: 13px; font-weight: 650; cursor: pointer; transition: all 0.2s; }
        .btn.active { border-color: var(--btn-color); background: rgba(59, 130, 246, 0.18); }
        textarea { width: 100%; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; color: var(--text-color); padding: 12px; font-size: 14px; resize: vertical; min-height: 110px; outline: none; }
        textarea:focus { border-color: var(--btn-color); }
        .hint { color: var(--hint-color); font-size: 12px; line-height: 1.35; margin-top: 8px; }
        .story-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .slot { position: relative; border: 1px dashed rgba(255,255,255,0.24); border-radius: 14px; min-height: 112px; background: rgba(255,255,255,0.03); display: flex; align-items: center; justify-content: center; overflow: hidden; cursor: pointer; }
        .slot img { width: 100%; height: 112px; object-fit: cover; display:block; }
        .slot .ph { text-align: center; padding: 8px; color: var(--hint-color); font-size: 12px; line-height: 1.25; }
        .badge { position: absolute; left: 6px; top: 6px; background: rgba(0,0,0,0.7); color:#fff; border-radius: 999px; padding: 3px 7px; font-size: 11px; font-weight: 800; }
        .del { position: absolute; right: 6px; top: 6px; background: rgba(239,68,68,0.95); color:#fff; width: 22px; height: 22px; border-radius: 50%; display:flex; align-items:center; justify-content:center; font-size: 12px; font-weight: 900; }
        .row { display:flex; align-items:center; justify-content:space-between; gap: 10px; color: var(--hint-color); font-size: 13px; }
        input[type="range"] { width: 62%; accent-color: var(--btn-color); }
        .main-btn { position: fixed; bottom: 16px; left: 16px; right: 16px; background: var(--btn-color); color: var(--btn-text); border: none; padding: 16px; border-radius: 14px; font-size: 15px; font-weight: 800; box-shadow: 0 10px 20px rgba(0,0,0,0.4); cursor: pointer; text-align: center; }
        .main-btn:disabled { background: #52525b; color: #9ca3af; cursor: not-allowed; }
    </style>
</head>
<body>
<div class="header"><h1>🌙 Moon Web Studio</h1><p>Один промпт + сториборд. Seedance/HappyHorse — до 9 референсов. Kling 3.0 Pro — стабильный first/last-frame режим.</p></div>

<div class="card">
    <div class="card-title">Модель</div>
    <div class="grid">
        <div class="btn active" onclick="setModel('bytedance/seedance-2.0', this)">🌱 Seedance 2.0</div>
        <div class="btn" onclick="setModel('alibaba/happyhorse-1.1', this)">🐎 HappyHorse 1.1</div>
        <div class="btn" onclick="setModel('kwaivgi/kling-v3.0-pro', this)">🎥 Kling 3.0 Pro</div>
    </div>
    <div class="hint" id="modelHint">Seedance: до 9 image references + first/last frame. Hero reference будет добавлен как главный референс внешности.</div>
</div>

<div class="card">
    <div class="card-title">Один промпт на всю историю</div>
    <textarea id="globalPrompt" placeholder="Опишите полную историю: персонажи, действие, настроение, монтаж, камеру. Например: Используй Image 1 как героя, Images 2-4 как ключевые сцены сториборда..."></textarea>
    <div class="hint">Совет: явно ссылайтесь на кадры: Image 1, Image 2... Что сохранить: лицо, одежду, локацию, стиль, продукт.</div>
</div>

<div class="card" id="heroCard">
    <div class="card-title"><span>Герой / лицо / внешность</span><span id="heroStatus">не задан</span></div>
    <div class="slot" id="heroSlot" onclick="pickHero()"><div class="ph">＋<br>Загрузить отдельный референс героя<br>лицо, одежда, внешность</div></div>
    <div class="hint">Для Seedance и HappyHorse этот кадр передаётся первым reference image и в промпт добавляется требование сохранять героя во всех кадрах. Для Kling это поле не используется.</div>
</div>

<div class="card">
    <div class="card-title"><span>Сториборд / референсы</span><span id="imgCount">0/9</span></div>
    <div class="story-grid" id="storyGrid"></div>
    <div class="hint" id="storyHint">Загрузите storyboard-кадры. Для Seedance/HappyHorse общий лимит — 9 references вместе с героем. Для Kling используются первый и последний кадры.</div>
</div>

<div class="card">
    <div class="card-title">Формат кадра</div>
    <div class="grid3">
        <div class="btn active" onclick="setAspect('16:9', this)">🖥 16:9</div>
        <div class="btn" onclick="setAspect('9:16', this)">📱 9:16</div>
        <div class="btn" onclick="setAspect('1:1', this)">⬜ 1:1</div>
        <div class="btn" onclick="setAspect('4:3', this)">▭ 4:3</div>
        <div class="btn" onclick="setAspect('3:4', this)">▯ 3:4</div>
        <div class="btn" onclick="setAspect('21:9', this)">🎞 21:9</div>
    </div>
</div>

<div class="card">
    <div class="card-title">Разрешение</div>
    <div class="grid3" id="resGrid">
        <div class="btn active" onclick="setRes('720p', this)">720p</div>
        <div class="btn" onclick="setRes('1080p', this)">1080p</div>
        <div class="btn" onclick="setRes('480p', this)">480p</div>
    </div>
    <div class="hint">Если выбранное разрешение или формат не поддерживается моделью OpenRouter, сервер вернёт ошибку без списания.</div>
</div>

<div class="card">
    <div class="card-title">Длительность <span id="durText">8с</span></div>
    <div class="row"><span>4с</span><input id="dur" type="range" min="4" max="15" value="8" oninput="updateSummary()"><span>15с</span></div>
</div>

<input type="file" id="hiddenFile" accept="image/*" style="display:none">
<button class="main-btn" id="submitBtn" onclick="submitStudio()">🚀 Запустить рендер (40 🔷)</button>

<script>
    const tg = window.Telegram.WebApp; tg.ready(); tg.expand();
    let currentModel = 'bytedance/seedance-2.0';
    let currentAspect = '16:9', currentRes = '720p', uploadIdx = null, uploadTarget = 'story';
    let frames = Array(9).fill(null);
    let heroRef = null;

    function setActive(el, selector) { document.querySelectorAll(selector).forEach(b => b.classList.remove('active')); el.classList.add('active'); }
    function setModel(model, el) {
        currentModel = model; setActive(el, '.card:nth-of-type(1) .btn');
        const hint = document.getElementById('modelHint');
        const heroCard = document.getElementById('heroCard');
        const storyHint = document.getElementById('storyHint');
        if (model.includes('happyhorse')) {
            hint.innerText = 'HappyHorse 1.1: до 9 image references, 720p/1080p, 3–15 сек. Hero reference фиксирует лицо/внешность как главный ordered reference.';
            heroCard.style.opacity = '1'; storyHint.innerText = 'HappyHorse: hero + storyboard суммарно до 9 references. Last frame идёт как reference, не exact anchor.';
            if (currentRes === '480p') { currentRes = '720p'; document.querySelectorAll('#resGrid .btn').forEach(b => b.classList.remove('active')); document.querySelector('#resGrid .btn').classList.add('active'); }
        } else if (model.includes('kling')) {
            hint.innerText = 'Kling 3.0 Pro: рабочий режим первого и последнего кадра. Референсы героя не поддерживаются OpenRouter для Kling и будут проигнорированы.';
            heroCard.style.opacity = '0.45'; storyHint.innerText = 'Kling: загрузите минимум первый кадр, можно последний. Остальные storyboard images не отправляются как references.';
            if (currentRes !== '720p') { currentRes = '720p'; document.querySelectorAll('#resGrid .btn').forEach(b => b.classList.remove('active')); document.querySelectorAll('#resGrid .btn')[0].classList.add('active'); }
        } else {
            hint.innerText = 'Seedance 2.0: до 9 image references + first/last frame. Hero reference будет главным референсом внешности во всей истории.';
            heroCard.style.opacity = '1'; storyHint.innerText = 'Seedance: hero + storyboard суммарно до 9 references. Первый/последний storyboard кадры также идут как anchors.';
        }
        renderGrid(); renderHero();
    }
    function setAspect(asp, el) { currentAspect = asp; el.parentElement.querySelectorAll('.btn').forEach(b => b.classList.remove('active')); el.classList.add('active'); }
    function setRes(res, el) { currentRes = res; el.parentElement.querySelectorAll('.btn').forEach(b => b.classList.remove('active')); el.classList.add('active'); }

    function renderGrid() {
        const grid = document.getElementById('storyGrid'); grid.innerHTML = '';
        frames.forEach((f, i) => {
            const label = i === 0 ? 'START' : (i === lastFilledIndex() && f ? 'END' : `IMG ${i+1}`);
            grid.innerHTML += `<div class="slot" onclick="pick(${i})">${f ? `<img src="data:image/jpeg;base64,${f}"><div class="badge">${label}</div><div class="del" onclick="event.stopPropagation(); removeFrame(${i})">×</div>` : `<div class="ph">＋<br>Image ${i+1}${i===0?'<br>начальный кадр':''}</div>`}</div>`;
        });
        const count = frames.filter(Boolean).length;
        const totalRefs = count + (heroRef && !currentModel.includes('kling') ? 1 : 0);
        document.getElementById('imgCount').innerText = currentModel.includes('kling') ? `${count} кадр.` : `${totalRefs}/9 refs`;
        updateSummary();
    }
    function lastFilledIndex() { let idx = -1; frames.forEach((f,i)=>{ if(f) idx=i; }); return idx; }
    function pick(i) { uploadTarget = 'story'; uploadIdx = i; document.getElementById('hiddenFile').click(); }
    function pickHero() { if (currentModel.includes('kling')) { tg.showAlert('Kling 3.0 Pro не поддерживает отдельный hero reference через OpenRouter. Используйте первый кадр storyboard.'); return; } uploadTarget = 'hero'; uploadIdx = null; document.getElementById('hiddenFile').click(); }
    function removeFrame(i) { frames[i] = null; renderGrid(); }
    function removeHero() { heroRef = null; renderHero(); renderGrid(); }
    function renderHero() {
        const slot = document.getElementById('heroSlot'); const status = document.getElementById('heroStatus');
        if (!slot) return;
        if (heroRef) { slot.innerHTML = `<img src="data:image/jpeg;base64,${heroRef}"><div class="badge">HERO</div><div class="del" onclick="event.stopPropagation(); removeHero()">×</div>`; status.innerText = 'задан'; }
        else { slot.innerHTML = `<div class="ph">＋<br>Загрузить отдельный референс героя<br>лицо, одежда, внешность</div>`; status.innerText = 'не задан'; }
    }
    document.getElementById('hiddenFile').addEventListener('change', async e => {
        if (e.target.files && e.target.files[0]) {
            const img = await compressImg(e.target.files[0]);
            if (uploadTarget === 'hero') { heroRef = img; renderHero(); renderGrid(); }
            else if (uploadIdx !== null) { frames[uploadIdx] = img; renderGrid(); }
        }
        e.target.value = '';
    });
    function compressImg(file) { return new Promise(res => { const r = new FileReader(); r.onload = e => { const img = new Image(); img.onload = () => { const cvs = document.createElement('canvas'); let w = img.width, h = img.height, max = 1280; if (w > h && w > max) { h = Math.round(h * max / w); w = max; } else if (h > max) { w = Math.round(w * max / h); h = max; } cvs.width = w; cvs.height = h; cvs.getContext('2d').drawImage(img, 0, 0, w, h); res(cvs.toDataURL('image/jpeg', 0.86).split(',')[1]); }; img.src = e.target.result; }; r.readAsDataURL(file); }); }
    function updateSummary() {
        const dur = parseInt(document.getElementById('dur').value); document.getElementById('durText').innerText = dur + 'с';
        const cost = dur * 5; const btn = document.getElementById('submitBtn');
        const totalRefs = frames.filter(Boolean).length + (heroRef && !currentModel.includes('kling') ? 1 : 0);
        btn.innerText = `🚀 Запустить рендер (${cost} 🔷)`;
        btn.disabled = totalRefs > 9;
        if (totalRefs > 9) btn.innerText = '⚠️ Лимит 9 references: удалите часть кадров';
    }
    async function submitStudio() {
        const prompt = document.getElementById('globalPrompt').value.trim();
        const used = frames.filter(Boolean);
        if (!prompt) { tg.showAlert('Введите один общий промпт для истории.'); return; }
        if (used.length < 1) { tg.showAlert('Загрузите хотя бы 1 storyboard-кадр.'); return; }
        if (!currentModel.includes('kling') && used.length + (heroRef ? 1 : 0) > 9) { tg.showAlert('Seedance/HappyHorse принимают максимум 9 references суммарно: hero + storyboard.'); return; }
        const btn = document.getElementById('submitBtn'); btn.disabled = true; btn.innerText = '⏳ Передача в студию...';
        const payload = { user_id: tg.initDataUnsafe?.user?.id || 0, model: currentModel, prompt, hero_ref: currentModel.includes('kling') ? null : heroRef, frames: used, aspect_ratio: currentAspect, resolution: currentRes, duration: parseInt(document.getElementById('dur').value) };
        try {
            const r = await fetch('/api/webapp_submit_video', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const res = await r.json(); if (res.ok) tg.close(); else { tg.showAlert('Ошибка: ' + res.error); btn.disabled = false; updateSummary(); }
        } catch(e) { tg.showAlert('Ошибка связи с сервером бота'); btn.disabled = false; updateSummary(); }
    }
    renderGrid(); renderHero();
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
    # OpenRouter /api/v1/videos. input_references = visual references, frame_images = exact anchors.
    "bytedance/seedance-2.0": {"audio": True, "resolution": True, "references": True, "max_image_refs": 9},
    "bytedance/seedance-2.0-fast": {"audio": True, "resolution": True, "references": True, "max_image_refs": 9},
    "alibaba/happyhorse-1.1": {"audio": False, "resolution": True, "references": True, "max_image_refs": 9},
    # Kling 3.0 Pro stays in Moon Web Studio as a stable first/last-frame workflow.
    "kwaivgi/kling-v3.0-pro": {"audio": True, "resolution": True, "references": False, "max_image_refs": 0},
}

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
    res = params.get("resolution")
    asp = params.get("aspect_ratio")
    if dur is not None and caps.get("supported_durations"):
        if int(dur) not in caps["supported_durations"]:
            errors.append(f"Длительность {dur}с не поддерживается. Доступно: {caps.get('supported_durations')}")
    if res and caps.get("supported_resolutions"):
        if res not in caps["supported_resolutions"]:
            errors.append(f"Разрешение {res} не поддерживается. Доступно: {caps.get('supported_resolutions')}")
    if asp and caps.get("supported_aspect_ratios"):
        if asp not in caps["supported_aspect_ratios"]:
            errors.append(f"Формат {asp} не поддерживается. Доступно: {caps.get('supported_aspect_ratios')}")
    requested_frames = params.get("frame_types") or []
    supported_frames = caps.get("supported_frame_images") or []
    for ft in requested_frames:
        if ft not in supported_frames:
            errors.append(f"{ft} не поддерживается этой моделью")
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
            "description": "Снять кинематографичный многосценовый видеоролик через Seedance 2.0 (5 🔷/сек).",
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
        "Ты — персональный ИИ-агент и кинорежиссер Moon Web Studio в Telegram. Ты умный, вежливый, инициативный.\n"
        "Твои возможности (инструменты):\n"
        "1. web_search — гуглить в интернете новости, факты, справку.\n"
        "2. fetch_webpage — читать ссылки юзера.\n"
        "3. generate_image — генерировать арты (Flux Pro, стоит 2 🔷).\n"
        "4. generate_multiscene_video — снимать видео через Seedance 2.0 / Video Studio (5 🔷/сек).\n"
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
                            if chat_id != ADMIN_ID and user_credits.get(chat_id, 0) < cost:
                                res_content = f"Недостаточно 🔷. Нужно {cost}."
                            else:
                                bot.send_message(chat_id, f"🎬 Принято! Агент отправляет сценарий в Seedance 2.0 ({total_d} сек)...")
                                user_video_model[chat_id] = "bytedance/seedance-2.0"
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

def refund_video_credits(chat_id, amount, reason="Возврат за видео"):
    if not amount or chat_id == ADMIN_ID:
        return
    with data_lock:
        user_credits[chat_id] += int(amount)
        user_credit_history[chat_id].append((time.time(), int(amount), reason))
        save_data()

def image_b64_to_openrouter_url(chat_id, b64_str, label="ref"):
    """OpenRouter video providers are most reliable with public HTTPS image URLs.
    On Render/WEBHOOK_HOST we save images to /static/uploads and pass that URL.
    If no public host exists, fallback to data URI (works for some providers, but less reliable).
    """
    try:
        clean_b64 = compress_image_if_needed(b64_str, max_size=(1280, 1280), quality=86)
        raw = base64.b64decode(clean_b64)
        prepared, _ = _prepare_image_bytes(raw, quality=88, max_size_mb=8)
        raw = prepared or raw
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
        if host:
            os.makedirs("static/uploads", exist_ok=True)
            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "", str(label))[:24] or "ref"
            fname = f"{chat_id}_{int(time.time()*1000)}_{safe_label}.jpg"
            path = os.path.join("static", "uploads", fname)
            with open(path, "wb") as f:
                f.write(raw)
            return f"https://{host}/static/uploads/{fname}"
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    except Exception as e:
        logging.warning(f"[IMG URL] fallback data-uri: {e}")
        return f"data:image/jpeg;base64,{b64_str}"

def download_completed_video(job, headers):
    """Return (bytes, fallback_link). Tries unsigned URLs first, then authenticated content endpoints."""
    urls = []
    for u in (job.get("unsigned_urls") or []):
        if u and u not in urls:
            urls.append(u)
    job_id = job.get("id") or job.get("generation_id")
    if job_id:
        urls.append(f"https://openrouter.ai/api/v1/videos/{job_id}/content?index=0")
        urls.append(f"https://openrouter.ai/api/v1/videos/{job_id}/content")
    fallback_link = (job.get("unsigned_urls") or [None])[0]
    for u in urls:
        try:
            use_auth = u.startswith("https://openrouter.ai/api/")
            vr = requests.get(u, headers=headers if use_auth else None, timeout=180, allow_redirects=True)
            ctype = (vr.headers.get("content-type") or "").lower()
            if vr.status_code == 200 and len(vr.content) > 500 and (b"ftyp" in vr.content[:256] or "video" in ctype or "octet-stream" in ctype):
                return vr.content, fallback_link
            logging.warning(f"[VIDEO DOWNLOAD] bad response {vr.status_code} {ctype} {len(vr.content)} from {u}")
        except Exception as e:
            logging.warning(f"[VIDEO DOWNLOAD] {e} from {u}")
    return None, fallback_link

def poll_video_task(polling_url, headers, chat_id, status_message_id, model_display="", refund_cost=0):
    """Poll OpenRouter job. If there is no delivered video/link at the end, refunds local bot credits."""
    start_time = time.time()
    last_edit = 0
    last_job = {}
    for attempt in range(1, 181):
        time.sleep(8)
        try:
            resp = requests.get(polling_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                logging.warning(f"[POLL] HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            data = resp.json()
            last_job = data
            status = data.get("status", "unknown")
            progress = data.get("progress")
            elapsed = int(time.time() - start_time)
            mins = elapsed // 60
            text = ""
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
                try: bot.edit_message_text("✅ Генерация завершена, скачиваю видео...", chat_id, status_message_id)
                except: pass
                video_bytes, fallback_link = download_completed_video(data, headers)
                if video_bytes:
                    sent = send_video_safe(chat_id, video_bytes, f"✅ Готово! {model_display}")
                    if sent:
                        try: bot.edit_message_text("✅ Видео отправлено в чат.", chat_id, status_message_id)
                        except: pass
                        return
                if fallback_link:
                    try:
                        bot.send_message(chat_id, f"✅ Видео готово, но Telegram не принял файл. Ссылка для скачивания:\n{fallback_link}")
                        return
                    except Exception:
                        pass
                refund_video_credits(chat_id, refund_cost, "Возврат: видео не удалось скачать/отправить")
                try: bot.edit_message_text("⚠️ Видео сгенерировано, но файл не удалось скачать или отправить. 🔷 возвращены.", chat_id, status_message_id)
                except: bot.send_message(chat_id, "⚠️ Видео сгенерировано, но файл не удалось скачать или отправить. 🔷 возвращены.")
                return
            elif status in ("failed", "cancelled", "expired"):
                err = data.get("error", status)
                refund_video_credits(chat_id, refund_cost, f"Возврат: видео {status}")
                try: bot.edit_message_text(f"❌ Ошибка генерации: {err}\n🔷 возвращены.", chat_id, status_message_id)
                except: pass
                return
            now = time.time()
            if text and now - last_edit > 11:
                try: bot.edit_message_text(text, chat_id, status_message_id, parse_mode="HTML"); last_edit = now
                except: pass
        except Exception as e:
            logging.warning(f"[POLL] {e}")
    refund_video_credits(chat_id, refund_cost, "Возврат: истекло ожидание видео")
    try: bot.edit_message_text("⏰ Время ожидания вышло. Видео не доставлено, 🔷 возвращены.", chat_id, status_message_id)
    except: pass

def generate_video_async(chat_id, prompt=None, first=None, last=None, multi_prompt=None, references=None):
    params = user_video_params.get(chat_id, {})
    dur = int(params.get("duration", 5))
    cost = dur * 5
    model = user_video_model.get(chat_id, "bytedance/seedance-2.0")
    model_name = {
        "bytedance/seedance-2.0": "Seedance 2.0",
        "bytedance/seedance-2.0-fast": "Seedance 2.0 Fast",
        "alibaba/happyhorse-1.1": "HappyHorse 1.1",
        "kwaivgi/kling-v3.0-pro": "Kling 3.0 Pro",
    }.get(model, model)
    asp = params.get("aspect_ratio", "16:9")
    res = params.get("resolution", "720p")
    aud = bool(params.get("audio", True))
    headers = _build_headers()

    # Build text + references
    if multi_prompt:
        scenes_text = []
        refs = []
        for i, s in enumerate(multi_prompt, 1):
            scene_dur = int(s.get("duration", s.get("dur", 3)))
            scenes_text.append(f"Scene {i} ({scene_dur}s): {s.get('prompt', '')}")
            if s.get("photo"):
                refs.append(s["photo"])
        prompt = "\n\n".join(scenes_text)
        if refs:
            first = refs[0]
            last = refs[-1] if len(refs) > 1 else None
            references = refs
        model_name += " [Studio]"

    references = list(references or [])
    if first and first not in references:
        references.insert(0, first)
    if last and last not in references:
        references.append(last)

    feats = VIDEO_MODEL_FEATURES.get(model, {})
    max_refs = int(feats.get("max_image_refs", 9))
    if len(references) > max_refs:
        references = references[:max_refs]

    if not prompt:
        bot.send_message(chat_id, "❌ Нет промпта для видео.")
        return False

    payload = {"model": model, "prompt": prompt, "duration": dur, "aspect_ratio": asp}
    if feats.get("resolution"):
        payload["resolution"] = res
    if feats.get("audio"):
        payload["generate_audio"] = aud

    # Ask live OpenRouter capabilities and send only supported exact frame anchors.
    caps = get_video_models_capabilities().get(model, {})
    supported_frames = caps.get("supported_frame_images") or []
    frame_types = []
    frames_payload = []
    if first and "first_frame" in supported_frames:
        frames_payload.append({"type": "image_url", "image_url": {"url": image_b64_to_openrouter_url(chat_id, first, "first")}, "frame_type": "first_frame"})
        frame_types.append("first_frame")
    if last and "last_frame" in supported_frames:
        frames_payload.append({"type": "image_url", "image_url": {"url": image_b64_to_openrouter_url(chat_id, last, "last")}, "frame_type": "last_frame"})
        frame_types.append("last_frame")
    elif last and model == "alibaba/happyhorse-1.1":
        try:
            bot.send_message(chat_id, "ℹ️ HappyHorse 1.1 на OpenRouter не заявляет exact last_frame. Финальный кадр будет передан как reference image.")
        except: pass
    if frames_payload:
        payload["frame_images"] = frames_payload

    # Reference-to-video: up to 9 visual references.
    if feats.get("references") and references:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": image_b64_to_openrouter_url(chat_id, b64, f"ref{i+1}")}}
            for i, b64 in enumerate(references[:max_refs])
        ]
        # Make references explicit in prompt for better adherence.
        if "Image 1" not in payload["prompt"] and "@Image1" not in payload["prompt"]:
            payload["prompt"] += "\n\nUse the uploaded references as ordered visual references. If a HERO reference is present, treat the first reference as the fixed character identity and preserve the same face, appearance and outfit identity in every shot. Use the storyboard references for scene, style, composition and final visual direction. Preserve character, product, outfit, location and style consistency across the full story."

    is_valid, error_msg = validate_video_request(model, {
        "duration": dur, "resolution": res, "aspect_ratio": asp,
        "frame_types": frame_types,
    })
    if not is_valid:
        bot.send_message(chat_id, f"❌ Модель не поддерживает выбранные параметры: {error_msg}\n🔷 не списаны.")
        return False

    with data_lock:
        if chat_id != ADMIN_ID:
            if user_credits.get(chat_id, 0) < cost:
                bot.send_message(chat_id, f"❌ Нужно {cost} 🔷")
                return False
            user_credits[chat_id] -= cost
            user_credit_history[chat_id].append((time.time(), -cost, f"Видео {model_name} {dur}с {asp} {res}"))
            save_data()
        bot.send_message(chat_id, f"✅ Списано {cost} 🔷")

    log_payload = dict(payload)
    for key in ("frame_images", "input_references"):
        if key in log_payload:
            log_payload[key] = f"{len(payload[key])} item(s)"
    logging.info(f"[VIDEO PAYLOAD] {json.dumps(log_payload, ensure_ascii=False)[:2000]}")

    try:
        r = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
        logging.info(f"[VIDEO] status={r.status_code} body={r.text[:600]}")
        if r.status_code not in (200, 202):
            refund_video_credits(chat_id, cost, f"Возврат: OpenRouter HTTP {r.status_code}")
            bot.send_message(chat_id, f"❌ Ошибка OpenRouter {r.status_code}: {r.text[:300]}\n🔷 возвращены.")
            return False

        j = r.json()
        logging.info(f"[VIDEO] RESPONSE JSON: {json.dumps(j, ensure_ascii=False)[:2000]}")

        if "error" in j or j.get("status") in ("failed", "cancelled", "expired"):
            err_msg = j.get("error", j.get("status", "unknown error"))
            refund_video_credits(chat_id, cost, "Возврат: ошибка API видео")
            bot.send_message(chat_id, f"❌ Ошибка генерации: {err_msg}\n🔷 возвращены.")
            return False

        if "polling_url" in j:
            m = bot.send_message(chat_id, f"🎬 <b>Генерация {model_name}</b>\n\n✅ Запрос принят. Ждём файл от OpenRouter...", parse_mode="HTML")
            Thread(target=poll_video_task, args=(j["polling_url"], headers, chat_id, m.message_id, model_name, cost), daemon=True).start()
            return True

        if j.get("status") == "completed" or j.get("unsigned_urls"):
            video_bytes, fallback_link = download_completed_video(j, headers)
            if video_bytes and send_video_safe(chat_id, video_bytes, f"✅ Готово! {model_name}"):
                return True
            if fallback_link:
                bot.send_message(chat_id, f"✅ Видео готово. Ссылка для скачивания:\n{fallback_link}")
                return True
            refund_video_credits(chat_id, cost, "Возврат: нет файла видео")
            bot.send_message(chat_id, "❌ Видео не удалось получить от провайдера. 🔷 возвращены.")
            return False

        refund_video_credits(chat_id, cost, "Возврат: неожиданный ответ видео")
        bot.send_message(chat_id, "❌ Неожиданный ответ от провайдера. 🔷 возвращены.")
        return False

    except Exception as e:
        logging.error(f"VIDEO EXC: {e}")
        refund_video_credits(chat_id, cost, "Возврат: ошибка связи видео")
        bot.send_message(chat_id, "❌ Ошибка связи с OpenRouter. 🔷 возвращены.")
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
    mk.add(
        InlineKeyboardButton("🌱 Seedance 2.0", callback_data="vmodel_seedance-2.0"),
        InlineKeyboardButton("🐎 HappyHorse 1.1", callback_data="vmodel_happyhorse-1.1"),
        InlineKeyboardButton("🎥 Kling 3.0 Pro", callback_data="vmodel_kling-pro"),
    )
    return mk

def video_params_keyboard(chat_id):
    p = user_video_params.get(chat_id, {})
    model = user_video_model.get(chat_id, "bytedance/seedance-2.0")
    caps = get_video_models_capabilities().get(model, {})
    d = int(p.get("duration", 8))
    r = p.get("resolution", "720p")
    a = p.get("audio", True)
    asp = p.get("aspect_ratio", "16:9")
    mk = InlineKeyboardMarkup(row_width=4)

    dur_options = [x for x in [4, 8, 12, 15] if not caps.get("supported_durations") or x in caps.get("supported_durations", [])]
    if not dur_options:
        dur_options = [5, 10, 15]
    mk.add(*[InlineKeyboardButton(f"{'✅' if d==x else '⬜'} {x}с", callback_data=f"vid_dur_{x}") for x in dur_options])

    res_options = caps.get("supported_resolutions") or ["720p", "1080p"]
    preferred = [x for x in ["480p", "720p", "1080p", "4K"] if x in res_options]
    if not preferred: preferred = res_options[:4]
    mk.add(*[InlineKeyboardButton(f"{'✅' if r==x else '⬜'} {x}", callback_data=f"vid_res_{x}") for x in preferred[:4]])

    asp_options = caps.get("supported_aspect_ratios") or ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"]
    preferred_asp = [x for x in ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"] if x in asp_options]
    for i in range(0, len(preferred_asp), 3):
        mk.add(*[InlineKeyboardButton(f"{'✅' if asp==x else '⬜'} {x}", callback_data=f"vid_aspect_{x.replace(':', '_')}") for x in preferred_asp[i:i+3]])

    if VIDEO_MODEL_FEATURES.get(model, {}).get("audio"):
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
        mk.add(InlineKeyboardButton("🌙 Moon Web Studio [Storyboard + refs]", web_app=WebAppInfo(url=studio_url)))
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
        "happyhorse-1.1": "alibaba/happyhorse-1.1",
        "kling-pro": "kwaivgi/kling-v3.0-pro",
    }
    if model_key in model_map:
        user_video_model[chat] = model_map[model_key]
        bot.delete_message(chat, call.message.message_id)
        mk = InlineKeyboardMarkup()
        mk.add(InlineKeyboardButton("⚙️ Настроить параметры", callback_data="setup_video_params"),
               InlineKeyboardButton("▶️ Пропустить (по умолчанию)", callback_data="skip_video_params"))
        bot.send_message(chat, "Желаете настроить длительность, разрешение, звук?\n(по умолчанию: 8 сек, 720p, звук вкл. если модель поддерживает)", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data in ("setup_video_params", "skip_video_params"))
def video_params_choice(call):
    chat = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.delete_message(chat, call.message.message_id)
    if call.data == "setup_video_params":
        user_video_params[chat] = {"duration": 8, "resolution": "720p", "audio": True, "aspect_ratio": "16:9"}
        bot.send_message(chat, "Настройте параметры видео:", reply_markup=video_params_keyboard(chat))
        user_state[chat] = "setting_video_params"
    else:
        user_video_params[chat] = {"duration": 8, "resolution": "720p", "audio": True, "aspect_ratio": "16:9"}
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
    model = data.get("model", "bytedance/seedance-2.0")
    if model not in VIDEO_MODEL_FEATURES:
        return jsonify({"ok": False, "error": "Эта модель недоступна в студии"}), 400

    asp = data.get("aspect_ratio", "16:9")
    res = data.get("resolution", "720p")
    duration = int(data.get("duration", 8))
    prompt = (data.get("prompt") or "").strip()
    hero_ref = data.get("hero_ref")
    frames = [x for x in (data.get("frames") or []) if x]

    # Backward compatibility with old scene-based payload.
    scenes = data.get("scenes", [])
    if scenes and not frames:
        for sc in scenes:
            sc["duration"] = int(sc.get("dur", sc.get("duration", 3)))
            if sc.get("photo"):
                frames.append(sc["photo"])
        duration = sum(sc.get("duration", 3) for sc in scenes)
        prompt = "\n\n".join([f"Scene {i+1} ({sc.get('duration', 3)}s): {sc.get('prompt', '')}" for i, sc in enumerate(scenes)])

    if not uid or not prompt:
        return jsonify({"ok": False, "error": "Нужен user_id и промпт"}), 400
    max_refs = int(VIDEO_MODEL_FEATURES.get(model, {}).get("max_image_refs", 9))
    if len(frames) < 1:
        return jsonify({"ok": False, "error": "Загрузите хотя бы 1 storyboard-кадр"}), 400
    if VIDEO_MODEL_FEATURES.get(model, {}).get("references"):
        refs_count = len(frames) + (1 if hero_ref else 0)
        if refs_count > max_refs:
            return jsonify({"ok": False, "error": f"Максимум {max_refs} референсов суммарно: hero + storyboard"}), 400
    else:
        refs_count = 0

    is_valid, error_msg = validate_video_request(model, {"duration": duration, "resolution": res, "aspect_ratio": asp, "frame_types": []})
    if not is_valid:
        return jsonify({"ok": False, "error": error_msg}), 400

    cost = duration * 5
    with data_lock:
        if uid != ADMIN_ID and user_credits.get(uid, 0) < cost:
            return jsonify({"ok": False, "error": f"Недостаточно 🔷. Нужно {cost}"}), 400

    model_name = {"bytedance/seedance-2.0": "Seedance 2.0", "alibaba/happyhorse-1.1": "HappyHorse 1.1", "kwaivgi/kling-v3.0-pro": "Kling 3.0 Pro"}.get(model, model)
    try:
        ref_label = f", {refs_count} refs" if VIDEO_MODEL_FEATURES.get(model, {}).get("references") else ", first/last frame"
        bot.send_message(uid, f"🎬 Студия: {model_name}{ref_label}, {duration} сек, {asp}, {res}. Запускаю...", parse_mode="HTML")
    except: pass

    user_video_model[uid] = model
    user_video_params[uid] = {"duration": duration, "aspect_ratio": asp, "resolution": res, "audio": True}
    first = frames[0] if frames else None
    last = frames[-1] if len(frames) > 1 else None
    references = ([hero_ref] if hero_ref and VIDEO_MODEL_FEATURES.get(model, {}).get("references") else []) + frames
    if hero_ref and VIDEO_MODEL_FEATURES.get(model, {}).get("references"):
        prompt = "Keep the person/character from the HERO reference image consistent in every shot: same face, hairstyle, body type, outfit identity and overall appearance. Do not change identity across cuts.\n\n" + prompt
    Thread(target=generate_video_async, args=(uid, prompt, first, last, None, references), daemon=True).start()
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
