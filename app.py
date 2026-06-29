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
import tempfile
import subprocess
import shutil

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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", stream=sys.stdout)

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

# ================== VIDEO SIZE LOCK ==================
# Финальный файл принудительно приводится к этим размерам через ffmpeg.
VIDEO_SIZE_MAP = {
    "16:9": {
        "480p": (854, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
    },
    "9:16": {
        "480p": (480, 854),
        "720p": (720, 1280),
        "1080p": (1080, 1920),
    },
    "1:1": {
        "480p": (480, 480),
        "720p": (720, 720),
        "1080p": (1080, 1080),
    },
}

VIDEO_FORMATS = list(VIDEO_SIZE_MAP.keys())
VIDEO_RESOLUTIONS = ["480p", "720p", "1080p"]

# --- WEB APP HTML ---
WEBAPP_HTML = r'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <title>Moon Web Studio</title>
    <style>
        :root {
            --bg-color: var(--tg-theme-bg-color, #101014);
            --text-color: var(--tg-theme-text-color, #ffffff);
            --hint-color: var(--tg-theme-hint-color, #9ca3af);
            --btn-color: var(--tg-theme-button-color, #3b82f6);
            --btn-text: var(--tg-theme-button-text-color, #ffffff);
            --sec-bg: var(--tg-theme-secondary-bg-color, #1f1f27);
            --danger:#ef4444;
            --ok:#22c55e;
            --border: rgba(255,255,255,0.12);
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 16px;
            padding-bottom: 108px;
        }
        .header { text-align: center; margin-bottom: 18px; }
        .header h1 { font-size: 22px; margin: 0; font-weight: 900; }
        .header p { font-size: 13px; color: var(--hint-color); margin: 6px 0 0 0; line-height: 1.35; }
        .card { background: var(--sec-bg); border-radius: 16px; padding: 16px; margin-bottom: 16px; border:1px solid rgba(255,255,255,0.05); }
        .card-title { font-size: 15px; font-weight: 800; margin-bottom: 12px; display: flex; justify-content: space-between; gap: 8px; align-items: center; }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
        .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
        .btn {
            background: rgba(255,255,255,0.06);
            border: 2px solid transparent;
            color: var(--text-color);
            padding: 11px 8px;
            border-radius: 12px;
            text-align: center;
            font-size: 13px;
            font-weight: 750;
            cursor: pointer;
            transition: all 0.15s ease;
            user-select:none;
        }
        .btn.active { border-color: var(--btn-color); background: rgba(59, 130, 246, 0.20); }
        .btn.disabled { opacity:.45; pointer-events:none; }
        textarea {
            width: 100%; background: rgba(255,255,255,0.06); border: 1px solid var(--border);
            border-radius: 12px; color: var(--text-color); padding: 12px; font-size: 14px;
            resize: vertical; min-height: 118px; outline: none; line-height:1.35;
        }
        textarea:focus { border-color: var(--btn-color); }
        .hint { color: var(--hint-color); font-size: 12px; line-height: 1.35; margin-top: 8px; }
        .two { display:grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
        .refs-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .slot {
            position: relative; border: 1px dashed rgba(255,255,255,0.25); border-radius: 14px;
            min-height: 118px; background: rgba(255,255,255,0.035); display: flex; align-items: center;
            justify-content: center; overflow: hidden; cursor: pointer;
        }
        .slot.big { min-height: 156px; }
        .slot img { width: 100%; height: 118px; object-fit: cover; display:block; }
        .slot.big img { height: 156px; }
        .slot .ph { text-align: center; padding: 8px; color: var(--hint-color); font-size: 12px; line-height: 1.28; white-space:pre-line; }
        .badge { position: absolute; left: 6px; top: 6px; background: rgba(0,0,0,0.72); color:#fff; border-radius: 999px; padding: 3px 7px; font-size: 10px; font-weight: 900; letter-spacing:.2px; }
        .del { position: absolute; right: 6px; top: 6px; background: rgba(239,68,68,0.95); color:#fff; width: 24px; height: 24px; border-radius: 50%; display:flex; align-items:center; justify-content:center; font-size: 13px; font-weight: 900; }
        .row { display:flex; align-items:center; justify-content:space-between; gap: 10px; color: var(--hint-color); font-size: 13px; }
        input[type="range"] { width: 62%; accent-color: var(--btn-color); }
        .main-btn {
            position: fixed; bottom: 16px; left: 16px; right: 16px; background: var(--btn-color);
            color: var(--btn-text); border: none; padding: 16px; border-radius: 14px; font-size: 15px;
            font-weight: 900; box-shadow: 0 10px 20px rgba(0,0,0,0.4); cursor: pointer; text-align: center;
        }
        .main-btn:disabled { background: #52525b; color: #9ca3af; cursor: not-allowed; }
        .pill { font-size:11px; color:var(--hint-color); font-weight:700; }
    </style>
</head>
<body>
<div class="header">
    <h1>🌙 Moon Web Studio</h1>
    <p>Отдельно: начальный кадр, конечный кадр, референсы, внешность героя. Итоговый MP4 приводится к выбранному размеру.</p>
</div>

<div class="card">
    <div class="card-title">Модель</div>
    <div class="grid">
        <div class="btn active" data-model="bytedance/seedance-2.0">🌱 Seedance 2.0</div>
        <div class="btn" data-model="alibaba/happyhorse-1.1">🐎 HappyHorse 1.1</div>
        <div class="btn" data-model="kwaivgi/kling-v3.0-pro">🎥 Kling 3.0 Pro</div>
    </div>
    <div class="hint" id="modelHint">Seedance 2.0: start/end кадры отдельно, hero + reference images отдельно, до 9 input references суммарно.</div>
</div>

<div class="card">
    <div class="card-title">Один промпт на всю историю</div>
    <textarea id="globalPrompt" placeholder="Опишите историю, движение камеры, действия, настроение. Например: Используй начальный кадр как старт сцены, конечный как финальный кадр. HERO сохранять неизменным. Storyboard references использовать для сцен и стиля..."></textarea>
    <div class="hint">Сейчас можно тестировать Seedance 2.0 даже с одним storyboard/start кадром: загрузите начальный кадр и промпт.</div>
</div>

<div class="card">
    <div class="card-title"><span>Начальный и конечный кадры</span><span class="pill">отдельные anchors</span></div>
    <div class="two">
        <div class="slot big" id="startSlot" data-pick="start"><div class="ph">＋
Начальный кадр
START / first_frame</div></div>
        <div class="slot big" id="endSlot" data-pick="end"><div class="ph">＋
Конечный кадр
END / last_frame
необязательно</div></div>
    </div>
    <div class="hint" id="anchorHint">Для Kling это главный режим: первый и последний кадр. Для Seedance/HappyHorse они передаются как frame_images, если модель заявляет поддержку.</div>
</div>

<div class="card" id="heroCard">
    <div class="card-title"><span>Внешность персонажа / HERO</span><span id="heroStatus">не задан</span></div>
    <div class="slot big" id="heroSlot" data-pick="hero"><div class="ph">＋
Отдельный референс героя
лицо, одежда, внешность</div></div>
    <div class="hint">Для Seedance/HappyHorse отправляется первым input reference и усиливается промптом. Для Kling поле отключается и не отправляется.</div>
</div>

<div class="card" id="refsCard">
    <div class="card-title"><span>Storyboard / reference images</span><span id="refsCount">0/9 refs</span></div>
    <div class="refs-grid" id="refsGrid"></div>
    <div class="hint" id="refsHint">Это НЕ начальный/конечный кадр. Это отдельные референсы стиля, сцен, продукта, локации. Лимит: hero + references до 9.</div>
</div>

<div class="card">
    <div class="card-title">Стороны кадра</div>
    <div class="grid3" id="aspectGrid">
        <div class="btn active" data-aspect="16:9">🖥 16:9</div>
        <div class="btn" data-aspect="9:16">📱 9:16</div>
        <div class="btn" data-aspect="1:1">⬜ 1:1</div>
    </div>
</div>

<div class="card">
    <div class="card-title">Разрешение</div>
    <div class="grid3" id="resGrid">
        <div class="btn" data-res="480p">480p</div>
        <div class="btn active" data-res="720p">720p</div>
        <div class="btn" data-res="1080p">1080p</div>
    </div>
    <div class="hint" id="sizeHint">Итоговый размер: 1280x720</div>
</div>

<div class="card">
    <div class="card-title">Длительность <span id="durText">8с</span></div>
    <div class="row"><span>4с</span><input id="dur" type="range" min="4" max="15" value="8"><span>15с</span></div>
</div>

<input type="file" id="hiddenFile" accept="image/*" style="display:none">
<button type="button" class="main-btn" id="submitBtn">🚀 Запустить рендер (40 🔷)</button>

<script>
(function(){
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (tg) { tg.ready(); tg.expand(); }

    const SIZE_MAP = {
        '16:9': {'480p':[854,480], '720p':[1280,720], '1080p':[1920,1080]},
        '9:16': {'480p':[480,854], '720p':[720,1280], '1080p':[1080,1920]},
        '1:1': {'480p':[480,480], '720p':[720,720], '1080p':[1080,1080]}
    };

    let currentModel = 'bytedance/seedance-2.0';
    let currentAspect = '16:9';
    let currentRes = '720p';
    let uploadTarget = null;
    let uploadIdx = null;
    let startFrame = null;
    let endFrame = null;
    let heroRef = null;
    let referenceImages = Array(9).fill(null);

    const $ = (id) => document.getElementById(id);

    function alertUser(text) {
        if (tg && tg.showAlert) tg.showAlert(text);
        else alert(text);
    }

    function setGroupActive(container, clicked) {
        container.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
        clicked.classList.add('active');
    }

    function modelKind() {
        if (currentModel.includes('kling')) return 'kling';
        if (currentModel.includes('happyhorse')) return 'happyhorse';
        return 'seedance';
    }

    function renderAnchorSlot(id, b64, label, placeholder) {
        const el = $(id);
        if (!el) return;
        if (b64) {
            el.innerHTML = `<img src="data:image/jpeg;base64,${b64}"><div class="badge">${label}</div><div class="del" data-remove="${label.toLowerCase()}">×</div>`;
        } else {
            el.innerHTML = `<div class="ph">${placeholder}</div>`;
        }
    }

    function renderHero() {
        const slot = $('heroSlot');
        const status = $('heroStatus');
        if (!slot) return;
        if (heroRef) {
            slot.innerHTML = `<img src="data:image/jpeg;base64,${heroRef}"><div class="badge">HERO</div><div class="del" data-remove="hero">×</div>`;
            status.innerText = 'задан';
        } else {
            slot.innerHTML = `<div class="ph">＋
Отдельный референс героя
лицо, одежда, внешность</div>`;
            status.innerText = 'не задан';
        }
    }

    function renderRefs() {
        const grid = $('refsGrid');
        grid.innerHTML = '';
        referenceImages.forEach((f, i) => {
            const div = document.createElement('div');
            div.className = 'slot';
            div.dataset.pickRef = String(i);
            if (f) {
                div.innerHTML = `<img src="data:image/jpeg;base64,${f}"><div class="badge">REF ${i+1}</div><div class="del" data-remove-ref="${i}">×</div>`;
            } else {
                div.innerHTML = `<div class="ph">＋<br>Reference ${i+1}</div>`;
            }
            grid.appendChild(div);
        });

        const count = referenceImages.filter(Boolean).length;
        const total = count + (heroRef && modelKind() !== 'kling' ? 1 : 0);
        $('refsCount').innerText = modelKind() === 'kling' ? 'Kling: refs off' : `${total}/9 refs`;
        updateSummary();
    }

    function renderAll() {
        renderAnchorSlot('startSlot', startFrame, 'START', '＋\nНачальный кадр\nSTART / first_frame');
        renderAnchorSlot('endSlot', endFrame, 'END', '＋\nКонечный кадр\nEND / last_frame\nнеобязательно');
        renderHero();
        renderRefs();
        updateModelUI();
    }

    function updateModelUI() {
        const kind = modelKind();
        const modelHint = $('modelHint');
        const heroCard = $('heroCard');
        const refsCard = $('refsCard');
        const refsHint = $('refsHint');

        if (kind === 'kling') {
            modelHint.innerText = 'Kling 3.0 Pro: сохраняем режим first/last-frame. HERO и reference images не отправляются.';
            heroCard.style.opacity = '0.45';
            refsCard.style.opacity = '0.45';
            refsHint.innerText = 'Для Kling refs отключены: используйте отдельные начальный и конечный кадры.';
        } else if (kind === 'happyhorse') {
            modelHint.innerText = 'HappyHorse 1.1: start/end отдельно, hero + references отдельно. Если last_frame не поддержан, финал пойдет как reference только при ручной поддержке провайдера.';
            heroCard.style.opacity = '1';
            refsCard.style.opacity = '1';
            refsHint.innerText = 'Hero + reference images до 9 input references. Start/end не считаются refs.';
        } else {
            modelHint.innerText = 'Seedance 2.0: можно тестировать с одним start/storyboard кадром. Start/end отдельно, hero + references отдельно.';
            heroCard.style.opacity = '1';
            refsCard.style.opacity = '1';
            refsHint.innerText = 'Hero + storyboard/reference images до 9 input references. Start/end не считаются refs.';
        }
        updateSummary();
    }

    function updateSizeHint() {
        const s = SIZE_MAP[currentAspect][currentRes];
        $('sizeHint').innerText = `Итоговый размер: ${s[0]}x${s[1]}`;
    }

    function updateSummary() {
        const dur = parseInt($('dur').value || '8', 10);
        $('durText').innerText = dur + 'с';
        updateSizeHint();

        const btn = $('submitBtn');
        const refsTotal = referenceImages.filter(Boolean).length + (heroRef && modelKind() !== 'kling' ? 1 : 0);
        const cost = dur * 5;
        btn.disabled = false;
        btn.innerText = `🚀 Запустить рендер (${cost} 🔷)`;
        if (modelKind() !== 'kling' && refsTotal > 9) {
            btn.disabled = true;
            btn.innerText = '⚠️ Лимит 9 refs: удалите часть кадров';
        }
    }

    function pick(target, idx=null) {
        if (modelKind() === 'kling' && (target === 'hero' || target === 'ref')) {
            alertUser('Kling 3.0 Pro использует только отдельные START и END кадры. HERO и refs не отправляются.');
            return;
        }
        uploadTarget = target;
        uploadIdx = idx;
        $('hiddenFile').click();
    }

    function compressImg(file) {
        return new Promise((resolve, reject) => {
            const r = new FileReader();
            r.onload = e => {
                const img = new Image();
                img.onload = () => {
                    const cvs = document.createElement('canvas');
                    let w = img.width, h = img.height, max = 1280;
                    if (w > h && w > max) { h = Math.round(h * max / w); w = max; }
                    else if (h > max) { w = Math.round(w * max / h); h = max; }
                    cvs.width = w; cvs.height = h;
                    cvs.getContext('2d').drawImage(img, 0, 0, w, h);
                    resolve(cvs.toDataURL('image/jpeg', 0.86).split(',')[1]);
                };
                img.onerror = reject;
                img.src = e.target.result;
            };
            r.onerror = reject;
            r.readAsDataURL(file);
        });
    }

    async function submitStudio() {
        const prompt = $('globalPrompt').value.trim();
        if (!prompt) { alertUser('Введите общий промпт для истории.'); return; }

        const refsTotal = referenceImages.filter(Boolean).length + (heroRef && modelKind() !== 'kling' ? 1 : 0);

        if (modelKind() === 'kling' && !startFrame) {
            alertUser('Для Kling 3.0 Pro нужен отдельный начальный кадр START.');
            return;
        }

        if (modelKind() !== 'kling' && !startFrame && refsTotal < 1) {
            alertUser('Для Seedance/HappyHorse загрузите START или хотя бы один HERO/reference storyboard кадр.');
            return;
        }

        if (modelKind() !== 'kling' && refsTotal > 9) {
            alertUser('Seedance/HappyHorse принимают максимум 9 input references суммарно: HERO + reference images. START/END отдельно.');
            return;
        }

        const btn = $('submitBtn');
        btn.disabled = true;
        btn.innerText = '⏳ Передача в студию...';

        const userId = tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : 0;
        const payload = {
            user_id: userId,
            model: currentModel,
            prompt: prompt,
            start_frame: startFrame,
            end_frame: endFrame,
            hero_ref: modelKind() === 'kling' ? null : heroRef,
            reference_images: modelKind() === 'kling' ? [] : referenceImages.filter(Boolean),
            aspect_ratio: currentAspect,
            resolution: currentRes,
            duration: parseInt($('dur').value || '8', 10)
        };

        try {
            const r = await fetch('/api/webapp_submit_video', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const res = await r.json();
            if (res.ok) {
                if (tg) tg.close();
                else alert('Запущено');
            } else {
                alertUser('Ошибка: ' + res.error);
                btn.disabled = false;
                updateSummary();
            }
        } catch(e) {
            alertUser('Ошибка связи с сервером бота');
            btn.disabled = false;
            updateSummary();
        }
    }

    document.addEventListener('click', (e) => {
        const modelBtn = e.target.closest('[data-model]');
        if (modelBtn) {
            currentModel = modelBtn.dataset.model;
            setGroupActive(modelBtn.parentElement, modelBtn);
            renderAll();
            return;
        }
        const aspBtn = e.target.closest('[data-aspect]');
        if (aspBtn) {
            currentAspect = aspBtn.dataset.aspect;
            setGroupActive(aspBtn.parentElement, aspBtn);
            updateSummary();
            return;
        }
        const resBtn = e.target.closest('[data-res]');
        if (resBtn) {
            currentRes = resBtn.dataset.res;
            setGroupActive(resBtn.parentElement, resBtn);
            updateSummary();
            return;
        }
        const remove = e.target.closest('[data-remove]');
        if (remove) {
            e.stopPropagation();
            const v = remove.dataset.remove;
            if (v === 'start') startFrame = null;
            if (v === 'end') endFrame = null;
            if (v === 'hero') heroRef = null;
            renderAll();
            return;
        }
        const removeRef = e.target.closest('[data-remove-ref]');
        if (removeRef) {
            e.stopPropagation();
            referenceImages[parseInt(removeRef.dataset.removeRef, 10)] = null;
            renderRefs();
            return;
        }
        const pickRef = e.target.closest('[data-pick-ref]');
        if (pickRef) {
            pick('ref', parseInt(pickRef.dataset.pickRef, 10));
            return;
        }
        const pickSlot = e.target.closest('[data-pick]');
        if (pickSlot) {
            pick(pickSlot.dataset.pick);
            return;
        }
        if (e.target.id === 'submitBtn') submitStudio();
    });

    $('dur').addEventListener('input', updateSummary);
    $('hiddenFile').addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        try {
            const img = await compressImg(file);
            if (uploadTarget === 'start') startFrame = img;
            else if (uploadTarget === 'end') endFrame = img;
            else if (uploadTarget === 'hero') heroRef = img;
            else if (uploadTarget === 'ref' && uploadIdx !== null) referenceImages[uploadIdx] = img;
            renderAll();
        } catch(err) {
            alertUser('Не удалось обработать изображение');
        } finally {
            e.target.value = '';
        }
    });

    renderAll();
})();
</script>
</body>
</html>'''

# ================== GIST SYNC ==================
def load_data():
    global user_credits, user_credit_history, user_message_count, user_last_activity, user_chat_history
    data = None

    if GIST_ID and GITHUB_TOKEN:
        try:
            r = requests.get(
                f"https://api.github.com/gists/{GIST_ID}",
                headers={"Authorization": f"token {GITHUB_TOKEN}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = json.loads(r.json()["files"]["bot_data.json"]["content"])
        except Exception as e:
            logging.warning(f"[LOAD GIST] {e}")

    if not data:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    user_credits = defaultdict(int, {int(k): v for k, v in data.get("credits", {}).items()})
    user_credit_history = defaultdict(list, {int(k): v for k, v in data.get("history", {}).items()})
    user_message_count = defaultdict(int, {int(k): v for k, v in data.get("messages", {}).items()})
    user_last_activity = defaultdict(float, {int(k): v for k, v in data.get("last_activity", {}).items()})
    user_chat_history = defaultdict(list, {int(k): v for k, v in data.get("chat_history", {}).items()})
    logging.info(f"[LOAD] {sum(user_credits.values())} credits")


def save_data():
    with data_lock:
        snap = {
            "credits": dict(user_credits),
            "history": dict(user_credit_history),
            "messages": dict(user_message_count),
            "last_activity": dict(user_last_activity),
            "chat_history": dict(user_chat_history),
        }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"[SAVE FILE] {e}")

    if GIST_ID and GITHUB_TOKEN:
        def _g():
            try:
                requests.patch(
                    f"https://api.github.com/gists/{GIST_ID}",
                    json={"files": {"bot_data.json": {"content": json.dumps(snap, ensure_ascii=False)}}},
                    headers={"Authorization": f"token {GITHUB_TOKEN}"},
                    timeout=20,
                )
            except Exception as e:
                logging.warning(f"[SAVE GIST] {e}")
        Thread(target=_g, daemon=True).start()


load_data()

if not TELEGRAM_TOKEN:
    logging.warning("TELEGRAM_TOKEN is not set")
if not OPENROUTER_API_KEY:
    logging.warning("OPENROUTER_API_KEY is not set")

bot = telebot.TeleBot(TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None
if bot:
    bot.request_timeout = 120

app = Flask(__name__)
os.makedirs("static", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)

VIDEO_MODEL_FEATURES = {
    "bytedance/seedance-2.0": {"audio": True, "resolution": True, "references": True, "max_image_refs": 9},
    "bytedance/seedance-2.0-fast": {"audio": True, "resolution": True, "references": True, "max_image_refs": 9},
    "alibaba/happyhorse-1.1": {"audio": False, "resolution": True, "references": True, "max_image_refs": 9},
    "kwaivgi/kling-v3.0-pro": {"audio": True, "resolution": True, "references": False, "max_image_refs": 0},
}

VIDEO_MODELS_CACHE = {}
VIDEO_MODELS_CACHE_TIME = 0


def _build_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/Jastick_bot",
        "X-Title": "TelegramBot",
    }


def get_target_video_size(aspect_ratio, resolution):
    return VIDEO_SIZE_MAP.get(aspect_ratio, {}).get(resolution)


def get_video_models_capabilities(force_refresh=False):
    global VIDEO_MODELS_CACHE, VIDEO_MODELS_CACHE_TIME
    now = time.time()
    if not force_refresh and VIDEO_MODELS_CACHE and (now - VIDEO_MODELS_CACHE_TIME < 3600):
        return VIDEO_MODELS_CACHE
    try:
        resp = requests.get("https://openrouter.ai/api/v1/videos/models", headers=_build_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            VIDEO_MODELS_CACHE = {m["id"]: m for m in data if "id" in m}
            VIDEO_MODELS_CACHE_TIME = now
            return VIDEO_MODELS_CACHE
        logging.warning(f"[VIDEO MODELS] HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        logging.warning(f"[VIDEO MODELS] {e}")
    return VIDEO_MODELS_CACHE


def validate_video_request(model_id, params):
    # Бот локально разрешает только эти форматы/разрешения, чтобы итоговый файл был контролируемым.
    asp = params.get("aspect_ratio")
    res = params.get("resolution")
    if asp not in VIDEO_SIZE_MAP:
        return False, "Доступны только форматы 16:9, 9:16 и 1:1"
    if res not in VIDEO_SIZE_MAP[asp]:
        return False, "Доступны только разрешения 480p, 720p и 1080p"

    caps = get_video_models_capabilities().get(model_id)
    if not caps:
        return True, None

    errors = []
    dur = params.get("duration")

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

# ================== AI AGENT HELPERS ==================
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
                    if title:
                        items.append(f"Новость: {title}")
            except Exception:
                pass

        if len(items) < 3:
            url = "https://html.duckduckgo.com/html/"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            dr = requests.post(url, data={"q": query, "kl": "ru-ru"}, headers=headers, timeout=10)
            text = dr.text
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
            clean = [re.sub(r'<.*?>', '', s).strip() for s in snippets[:3]]
            items.extend([c for c in clean if c])

        return items if items else ["Актуальных данных по запросу не обнаружено."]
    except Exception as e:
        return [f"Справка поиска: {e}"]


def helper_fetch_webpage(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        text = unescape(r.text)
        text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
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
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Прочесть текстовое содержимое веб-страницы по ссылке URL",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Нарисовать и отправить юзеру картинку через нейросеть Flux Pro. Списывает 2 токена 🔷.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3"]},
                },
                "required": ["prompt", "aspect_ratio"],
            },
        },
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
                            "properties": {"prompt": {"type": "string"}, "duration": {"type": "integer"}},
                            "required": ["prompt", "duration"],
                        },
                    },
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1"]},
                    "confirmed_by_user": {"type": "boolean"},
                },
                "required": ["scenes", "aspect_ratio", "confirmed_by_user"],
            },
        },
    },
    {"type": "function", "function": {"name": "get_my_balance", "description": "Проверить текущий баланс токенов 🔷 пользователя", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "clear_memory", "description": "Очистить память диалога с пользователем", "parameters": {"type": "object", "properties": {}}}},
]


def extract_deepseek_tools(choice_msg):
    if choice_msg.get("tool_calls"):
        return choice_msg["tool_calls"], choice_msg.get("content", "")
    content = choice_msg.get("content", "") or ""
    if "<｜tool" in content or "<|tool" in content:
        raw_matches = re.findall(
            r"<[｜\|]tool.*?begin[｜\|]>function<[｜\|]tool.*?sep[｜\|]>(\w+)\s*\n?({[^<]+})",
            content,
        )
        t_calls = []
        for fn_name, arg_str in raw_matches:
            t_calls.append({
                "id": f"call_{int(time.time() * 1000)}",
                "type": "function",
                "function": {"name": fn_name.strip(), "arguments": arg_str.strip()},
            })
        if t_calls:
            clean_text = re.split(r"<[｜\|]tool", content)[0].strip()
            return t_calls, clean_text
    return None, content


def run_agent(chat_id, user_text):
    history = list(user_chat_history.get(chat_id, []))
    if len(history) > 20:
        history = history[-18:]

    system_prompt = (
        "Ты — персональный ИИ-агент и кинорежиссер Moon Web Studio в Telegram. Отвечай понятно на русском.\n"
        "Инструменты: web_search, fetch_webpage, generate_image, generate_multiscene_video, get_my_balance, clear_memory.\n"
        "Не делай больше одного web_search за ответ.\n"
        "Запрещено запускать generate_multiscene_video без явного подтверждения пользователя. Сначала сценарий, цена 5 🔷/сек, вопрос о подтверждении."
    )

    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_text}]
    headers = _build_headers()

    for _turn in range(4):
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

            if not tool_calls:
                final_text = choice_msg.get("content", "")
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": final_text})
                user_chat_history[chat_id] = history[-20:]
                save_data()
                return final_text

            choice_msg["content"] = clean_content
            choice_msg["tool_calls"] = tool_calls
            messages.append(choice_msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"].get("arguments", "{}")
                call_id = tc.get("id", f"call_{int(time.time()*1000)}")
                try:
                    args = json.loads(fn_args)
                except Exception:
                    args = {}

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
                            out_b, _ = prepare_image_bytes(img_bytes)
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
                    is_confirmed = bool(args.get("confirmed_by_user", False))
                    total_d = sum(int(s.get("duration", 3)) for s in scenes)
                    cost = total_d * 5
                    if not is_confirmed:
                        res_content = f"СТОП: нельзя запустить видео без подтверждения. Выведи сценарий ({total_d} сек, цена {cost} 🔷) и спроси подтверждение."
                    else:
                        if chat_id != ADMIN_ID and user_credits.get(chat_id, 0) < cost:
                            res_content = f"Недостаточно 🔷. Нужно {cost}."
                        else:
                            bot.send_message(chat_id, f"🎬 Принято! Агент отправляет сценарий в Seedance 2.0 ({total_d} сек)...")
                            user_video_model[chat_id] = "bytedance/seedance-2.0"
                            user_video_params[chat_id] = {"duration": total_d, "aspect_ratio": asp, "audio": True, "resolution": "720p"}
                            Thread(target=generate_video_async, args=(chat_id, None, None, None, scenes), daemon=True).start()
                            res_content = "Генерация многосценового видео запущена."

                messages.append({"role": "tool", "tool_call_id": call_id, "name": fn_name, "content": str(res_content)})
        except Exception as e:
            logging.error(f"[AGENT] {e}")
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
        elif (msg.get("content") or "").startswith("data:image/"):
            img_url = msg["content"]
        else:
            return None, msg.get("content", "Нет изображения в ответе")

        if img_url.startswith("data:image/"):
            return base64.b64decode(img_url.split(",", 1)[1]), None
        rr = requests.get(img_url, timeout=30)
        if rr.status_code == 200:
            return rr.content, None
        return None, f"Не удалось скачать изображение: HTTP {rr.status_code}"
    except Exception as e:
        return None, str(e)


def prepare_image_bytes(img_data, quality=95, max_size_mb=5):
    try:
        img = Image.open(io.BytesIO(img_data))
        if img.mode != "RGB":
            img = img.convert("RGB")
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
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ],
        }],
        "modalities": ["image"],
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
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            ],
        }],
        "modalities": ["image"],
    }
    try:
        resp = requests.post(OPENROUTER_URL, json=payload, headers=_build_headers(), timeout=120)
        return _parse_image_response(resp)
    except Exception as e:
        logging.error(f"Seedream edit error: {e}")
        return None, str(e)

# ================== VIDEO HELPERS ==================
def compress_image_if_needed(b64_str, max_size=(1280, 1280), quality=86):
    try:
        img = Image.open(io.BytesIO(base64.b64decode(b64_str)))
        img.thumbnail(max_size, _safe_resample())
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return b64_str


def is_valid_mp4(d):
    return bool(d and len(d) > 500 and b"ftyp" in d[:256])


def normalize_video_bytes(video_bytes, aspect_ratio, resolution):
    """Приводит MP4 к точному размеру: 480p/720p/1080p + 16:9/9:16/1:1."""
    target = get_target_video_size(aspect_ratio, resolution)
    if not target:
        return video_bytes, None

    width, height = target
    size_text = f"{width}x{height}"

    if not shutil.which("ffmpeg"):
        logging.warning("[FFMPEG] ffmpeg not found. Video was not normalized.")
        return video_bytes, f"{size_text} requested, ffmpeg not installed"

    src_path = None
    out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as src:
            src.write(video_bytes)
            src_path = src.name
        out_path = src_path + "_normalized.mp4"

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )
        cmd = [
            "ffmpeg", "-y", "-i", src_path,
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "18",
            "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            out_path,
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if p.returncode != 0:
            logging.warning(f"[FFMPEG] normalize failed: {p.stderr.decode(errors='ignore')[:1000]}")
            return video_bytes, f"{size_text} requested, normalize failed"

        with open(out_path, "rb") as f:
            normalized = f.read()
        if is_valid_mp4(normalized):
            return normalized, size_text
        return video_bytes, f"{size_text} requested, normalized file invalid"
    except Exception as e:
        logging.warning(f"[FFMPEG] normalize exception: {e}")
        return video_bytes, f"{size_text} requested, normalize exception"
    finally:
        for pth in (src_path, out_path):
            try:
                if pth and os.path.exists(pth):
                    os.remove(pth)
            except Exception:
                pass


def send_video_safe(chat_id, data, caption="✅ Ваше видео готово!"):
    try:
        params = user_video_params.get(chat_id, {})
        asp = params.get("aspect_ratio", "16:9")
        res = params.get("resolution", "720p")
        normalized_data, size_text = normalize_video_bytes(data, asp, res)
        if normalized_data:
            data = normalized_data
        if size_text:
            caption = f"{caption}\n📐 Формат: {asp}, {res}, {size_text}"

        f = io.BytesIO(data)
        f.name = "video.mp4"
        bot.send_video(chat_id, f, caption=caption, supports_streaming=True, timeout=120)
        return True
    except Exception as e:
        logging.warning(f"[SEND VIDEO] send_video failed: {e}")
        try:
            f = io.BytesIO(data)
            f.name = "video.mp4"
            bot.send_document(chat_id, f, caption=caption)
            return True
        except Exception as e2:
            logging.warning(f"[SEND VIDEO] send_document failed: {e2}")
            return False


def refund_video_credits(chat_id, amount, reason="Возврат за видео"):
    if not amount or chat_id == ADMIN_ID:
        return
    with data_lock:
        user_credits[chat_id] += int(amount)
        user_credit_history[chat_id].append((time.time(), int(amount), reason))
        save_data()


def image_b64_to_openrouter_url(chat_id, b64_str, label="ref"):
    """OpenRouter video providers надежнее работают с публичными HTTPS URL."""
    try:
        clean_b64 = compress_image_if_needed(b64_str, max_size=(1280, 1280), quality=86)
        raw = base64.b64decode(clean_b64)
        prepared, _ = prepare_image_bytes(raw, quality=88, max_size_mb=8)
        raw = prepared or raw

        host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
        if host:
            os.makedirs("static/uploads", exist_ok=True)
            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "", str(label))[:24] or "ref"
            fname = f"{chat_id}_{int(time.time() * 1000)}_{safe_label}.jpg"
            path = os.path.join("static", "uploads", fname)
            with open(path, "wb") as f:
                f.write(raw)
            return f"https://{host}/static/uploads/{fname}"
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    except Exception as e:
        logging.warning(f"[IMG URL] fallback data-uri: {e}")
        return f"data:image/jpeg;base64,{b64_str}"


def download_completed_video(job, headers):
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
    start_time = time.time()
    last_edit = 0

    for attempt in range(1, 181):
        time.sleep(8)
        try:
            resp = requests.get(polling_url, headers=headers, timeout=30)
            if resp.status_code != 200:
                logging.warning(f"[POLL] HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json()
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
                    if mins < 1:
                        stage = "Подготовка запроса"
                    elif mins < 2:
                        stage = "Анализ референсов"
                    elif mins < 4:
                        stage = "Генерация кадров"
                    elif mins < 7:
                        stage = "Рендеринг видео"
                    else:
                        stage = "Финализация и кодирование"
                    text = f"🎬 <b>{model_display}</b>\n⏳ {stage}...\n⏱ Прошло: {mins} мин\n🔄 Опрос #{attempt} (OpenRouter)"

            elif status == "completed":
                try:
                    bot.edit_message_text("✅ Генерация завершена, скачиваю и нормализую видео...", chat_id, status_message_id)
                except Exception:
                    pass
                video_bytes, fallback_link = download_completed_video(data, headers)
                if video_bytes:
                    sent = send_video_safe(chat_id, video_bytes, f"✅ Готово! {model_display}")
                    if sent:
                        try:
                            bot.edit_message_text("✅ Видео отправлено в чат.", chat_id, status_message_id)
                        except Exception:
                            pass
                        return
                if fallback_link:
                    try:
                        bot.send_message(chat_id, f"✅ Видео готово, но Telegram не принял файл. Ссылка для скачивания:\n{fallback_link}")
                        return
                    except Exception:
                        pass
                refund_video_credits(chat_id, refund_cost, "Возврат: видео не удалось скачать/отправить")
                try:
                    bot.edit_message_text("⚠️ Видео сгенерировано, но файл не удалось скачать или отправить. 🔷 возвращены.", chat_id, status_message_id)
                except Exception:
                    bot.send_message(chat_id, "⚠️ Видео сгенерировано, но файл не удалось скачать или отправить. 🔷 возвращены.")
                return

            elif status in ("failed", "cancelled", "expired"):
                err = data.get("error", status)
                refund_video_credits(chat_id, refund_cost, f"Возврат: видео {status}")
                try:
                    bot.edit_message_text(f"❌ Ошибка генерации: {err}\n🔷 возвращены.", chat_id, status_message_id)
                except Exception:
                    pass
                return

            now = time.time()
            if text and now - last_edit > 11:
                try:
                    bot.edit_message_text(text, chat_id, status_message_id, parse_mode="HTML")
                    last_edit = now
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"[POLL] {e}")

    refund_video_credits(chat_id, refund_cost, "Возврат: истекло ожидание видео")
    try:
        bot.edit_message_text("⏰ Время ожидания вышло. Видео не доставлено, 🔷 возвращены.", chat_id, status_message_id)
    except Exception:
        pass


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

    # Старый multi_prompt режим агента. Здесь сцены становятся текстом, фото — только anchors/references для совместимости.
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
            references = refs[:]
        model_name += " [Agent]"

    # ВАЖНО: start/end больше НЕ добавляются автоматически в input_references.
    references = list(references or [])

    feats = VIDEO_MODEL_FEATURES.get(model, {})
    max_refs = int(feats.get("max_image_refs", 9))
    if len(references) > max_refs:
        references = references[:max_refs]

    if not prompt:
        bot.send_message(chat_id, "❌ Нет промпта для видео.")
        return False

    is_valid, error_msg = validate_video_request(model, {
        "duration": dur,
        "resolution": res,
        "aspect_ratio": asp,
        "frame_types": [],
    })
    if not is_valid:
        bot.send_message(chat_id, f"❌ Модель не поддерживает выбранные параметры: {error_msg}\n🔷 не списаны.")
        return False

    payload = {"model": model, "prompt": prompt, "duration": dur, "aspect_ratio": asp}
    if feats.get("resolution"):
        payload["resolution"] = res
    if feats.get("audio"):
        payload["generate_audio"] = aud

    # Exact frame anchors: START/END отдельно от references.
    caps = get_video_models_capabilities().get(model, {})
    supported_frames = caps.get("supported_frame_images") or []
    frame_types = []
    frames_payload = []

    if first and "first_frame" in supported_frames:
        frames_payload.append({
            "type": "image_url",
            "image_url": {"url": image_b64_to_openrouter_url(chat_id, first, "first")},
            "frame_type": "first_frame",
        })
        frame_types.append("first_frame")
    elif first:
        logging.info(f"[VIDEO] {model} does not report first_frame support. Start frame not sent as frame_images.")

    if last and "last_frame" in supported_frames:
        frames_payload.append({
            "type": "image_url",
            "image_url": {"url": image_b64_to_openrouter_url(chat_id, last, "last")},
            "frame_type": "last_frame",
        })
        frame_types.append("last_frame")
    elif last:
        logging.info(f"[VIDEO] {model} does not report last_frame support. End frame not sent as frame_images.")

    if frames_payload:
        payload["frame_images"] = frames_payload

    # Reference-to-video: hero + reference_images, but NOT start/end.
    if feats.get("references") and references:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": image_b64_to_openrouter_url(chat_id, b64, f"ref{i+1}")}}
            for i, b64 in enumerate(references[:max_refs])
        ]
        if "ordered visual references" not in payload["prompt"]:
            payload["prompt"] += (
                "\n\nUse the uploaded input references as ordered visual references. "
                "If the first reference is a HERO/person reference, preserve the same face, appearance, outfit identity and character identity in every shot. "
                "Use the other references for storyboard, scene, style, product, location and composition consistency."
            )

    # После формирования anchors проверяем supported frame types.
    is_valid, error_msg = validate_video_request(model, {
        "duration": dur,
        "resolution": res,
        "aspect_ratio": asp,
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
    logging.info(f"[VIDEO PAYLOAD] {json.dumps(log_payload, ensure_ascii=False)[:2500]}")

    try:
        r = requests.post(OPENROUTER_VIDEO_URL, json=payload, headers=headers, timeout=60)
        logging.info(f"[VIDEO] status={r.status_code} body={r.text[:800]}")

        if r.status_code not in (200, 202):
            refund_video_credits(chat_id, cost, f"Возврат: OpenRouter HTTP {r.status_code}")
            bot.send_message(chat_id, f"❌ Ошибка OpenRouter {r.status_code}: {r.text[:500]}\n🔷 возвращены.")
            return False

        j = r.json()
        logging.info(f"[VIDEO] RESPONSE JSON: {json.dumps(j, ensure_ascii=False)[:2000]}")

        if "error" in j or j.get("status") in ("failed", "cancelled", "expired"):
            err_msg = j.get("error", j.get("status", "unknown error"))
            refund_video_credits(chat_id, cost, "Возврат: ошибка API видео")
            bot.send_message(chat_id, f"❌ Ошибка генерации: {err_msg}\n🔷 возвращены.")
            return False

        if "polling_url" in j:
            target = get_target_video_size(asp, res)
            target_text = f"\n📐 Итог будет нормализован: {asp}, {res}, {target[0]}x{target[1]}" if target else ""
            m = bot.send_message(
                chat_id,
                f"🎬 <b>Генерация {model_name}</b>\n\n✅ Запрос принят. Ждём файл от OpenRouter...{target_text}",
                parse_mode="HTML",
            )
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
    m.add(
        KeyboardButton("🖼 Создать изображение"), KeyboardButton("🎨 Редактировать фото"),
        KeyboardButton("🎥 Создать видео"), KeyboardButton("💬 Спросить (чат)"),
        KeyboardButton("👤 Профиль"), KeyboardButton("💰 Магазин"),
        KeyboardButton("📖 Инструкция"),
    )
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
    mk.add(*[InlineKeyboardButton(f"{'✅' if d == x else '⬜'} {x}с", callback_data=f"vid_dur_{x}") for x in dur_options])

    # Только нужные разрешения. Если OpenRouter отдает список — пересекаем.
    caps_res = caps.get("supported_resolutions") or VIDEO_RESOLUTIONS
    res_options = [x for x in VIDEO_RESOLUTIONS if x in caps_res] or VIDEO_RESOLUTIONS
    mk.add(*[InlineKeyboardButton(f"{'✅' if r == x else '⬜'} {x}", callback_data=f"vid_res_{x}") for x in res_options])

    caps_asp = caps.get("supported_aspect_ratios") or VIDEO_FORMATS
    asp_options = [x for x in VIDEO_FORMATS if x in caps_asp] or VIDEO_FORMATS
    mk.add(*[InlineKeyboardButton(f"{'✅' if asp == x else '⬜'} {x}", callback_data=f"vid_aspect_{x.replace(':', '_')}") for x in asp_options])

    if VIDEO_MODEL_FEATURES.get(model, {}).get("audio"):
        mk.add(
            InlineKeyboardButton(f"{'✅' if a else '⬜'} Со звуком", callback_data="vid_audio_true"),
            InlineKeyboardButton(f"{'✅' if not a else '⬜'} Без звука", callback_data="vid_audio_false"),
        )
    mk.add(InlineKeyboardButton("✅ Готово", callback_data="vid_params_done"))
    return mk

# ================== HANDLERS ==================
if bot:
    @bot.message_handler(commands=["start"])
    def start_cmd(m):
        chat = m.chat.id
        user_state[chat] = "main"
        bot.send_message(chat, "👋 Привет! Выберите действие:", reply_markup=main_menu_keyboard())

    # ---------- IMAGE GENERATION ----------
    @bot.message_handler(func=lambda m: m.text == "🖼 Создать изображение")
    def menu_generate_image(m):
        chat = m.chat.id
        user_state[chat] = "select_model_generate"
        mk = InlineKeyboardMarkup(row_width=2)
        mk.add(
            InlineKeyboardButton("🌊 Flux (2🔷)", callback_data="gen_flux"),
            InlineKeyboardButton("🎨 Seedream (2🔷)", callback_data="gen_seedream"),
        )
        bot.send_message(chat, "Выбери модель для генерации:", reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data in ("gen_flux", "gen_seedream"))
    def select_generate_model(call):
        chat = call.message.chat.id
        bot.answer_callback_query(call.id)
        user_generate_model[chat] = "flux" if call.data == "gen_flux" else "seedream"
        mk = InlineKeyboardMarkup(row_width=2)
        mk.add(
            InlineKeyboardButton("16:9", callback_data="gen_aspect_16_9"),
            InlineKeyboardButton("9:16", callback_data="gen_aspect_9_16"),
            InlineKeyboardButton("1:1", callback_data="gen_aspect_1_1"),
            InlineKeyboardButton("4:3", callback_data="gen_aspect_4_3"),
        )
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
            out_b, _ = prepare_image_bytes(img_bytes)
            bot.send_photo(chat, out_b or img_bytes, caption=f"🎨 Готово! ({aspect})")
        else:
            with data_lock:
                if chat != ADMIN_ID:
                    user_credits[chat] += cost
                    save_data()
            bot.send_message(chat, "❌ Ошибка генерации. Токены 🔷 возвращены.")
        user_state.pop(chat, None)

    # ---------- PHOTO EDIT ----------
    @bot.message_handler(func=lambda m: m.text == "🎨 Редактировать фото")
    def menu_edit_photo(m):
        chat = m.chat.id
        user_state[chat] = "select_model_edit"
        mk = InlineKeyboardMarkup(row_width=2)
        mk.add(
            InlineKeyboardButton("🌊 Flux (3🔷)", callback_data="edit_flux"),
            InlineKeyboardButton("🎨 Seedream (3🔷)", callback_data="edit_seedream"),
        )
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
        mk.add(
            InlineKeyboardButton("✅ Сохранить лицо", callback_data="edit_face_on"),
            InlineKeyboardButton("❌ Обычное", callback_data="edit_face_off"),
        )
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
            out_b, _ = prepare_image_bytes(img_bytes)
            bot.send_photo(chat, out_b or img_bytes, caption="🎨 Готово!")
        else:
            with data_lock:
                if chat != ADMIN_ID:
                    user_credits[chat] += cost
                    save_data()
            bot.send_message(chat, f"❌ Ошибка редактирования: {err}. Токены 🔷 возвращены.")
        user_state.pop(chat, None)

    # ---------- VIDEO ----------
    @bot.message_handler(func=lambda m: m.text == "🎥 Создать видео")
    def menu_video(m):
        chat = m.chat.id
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or os.getenv("WEBHOOK_HOST")
        studio_url = f"https://{host}/studio" if host else ""
        mk = InlineKeyboardMarkup(row_width=1)
        if studio_url:
            mk.add(InlineKeyboardButton("🌙 Moon Web Studio [START/END + refs + hero]", web_app=WebAppInfo(url=studio_url)))
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
        try:
            bot.delete_message(chat, call.message.message_id)
        except Exception:
            pass
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
            try:
                bot.delete_message(chat, call.message.message_id)
            except Exception:
                pass
            mk = InlineKeyboardMarkup()
            mk.add(
                InlineKeyboardButton("⚙️ Настроить параметры", callback_data="setup_video_params"),
                InlineKeyboardButton("▶️ Пропустить (8с, 720p, 16:9)", callback_data="skip_video_params"),
            )
            bot.send_message(chat, "Желаете настроить длительность, разрешение, стороны, звук?", reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data in ("setup_video_params", "skip_video_params"))
    def video_params_choice(call):
        chat = call.message.chat.id
        bot.answer_callback_query(call.id)
        try:
            bot.delete_message(chat, call.message.message_id)
        except Exception:
            pass

        user_video_params[chat] = {"duration": 8, "resolution": "720p", "audio": True, "aspect_ratio": "16:9"}
        if call.data == "setup_video_params":
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
            try:
                bot.edit_message_reply_markup(chat, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            user_state[chat] = None
            proceed_after_video_params(chat)
            return

        if data.startswith("vid_dur_"):
            params["duration"] = int(data.split("_")[-1])
        elif data.startswith("vid_res_"):
            params["resolution"] = data.split("_")[-1]
        elif data.startswith("vid_aspect_"):
            parts = data.replace("vid_aspect_", "").split("_")
            if len(parts) == 2:
                params["aspect_ratio"] = parts[0] + ":" + parts[1]
        elif data == "vid_audio_true":
            params["audio"] = True
        elif data == "vid_audio_false":
            params["audio"] = False

        try:
            bot.edit_message_reply_markup(chat, call.message.message_id, reply_markup=video_params_keyboard(chat))
        except Exception:
            pass

    @bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_first")
    def handle_video_first_frame(m):
        chat = m.chat.id
        file_info = bot.get_file(m.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        b64 = base64.b64encode(downloaded).decode()
        user_video_frames[chat] = {"first": b64}
        mk = InlineKeyboardMarkup()
        mk.add(
            InlineKeyboardButton("📸 Добавить последний кадр", callback_data="add_last_frame"),
            InlineKeyboardButton("▶️ Продолжить без него", callback_data="skip_last_frame"),
        )
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
        try:
            bot.delete_message(chat, call.message.message_id)
        except Exception:
            pass

    @bot.message_handler(content_types=["photo"], func=lambda m: user_state.get(m.chat.id) == "awaiting_video_image_last")
    def handle_video_last_frame(m):
        chat = m.chat.id
        file_info = bot.get_file(m.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        b64 = base64.b64encode(downloaded).decode()
        user_video_frames.setdefault(chat, {})["last"] = b64
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

    # ---------- PROFILE / SHOP / ADMIN / CHAT ----------
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
                text += f"{sign}{delta} 🔷 – {escape(str(reason))}\n"
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
            mk.add(
                InlineKeyboardButton(f"{pkg['name']} ⭐️", callback_data=f"buy_stars_{key}"),
                InlineKeyboardButton(f"{pkg['name']} 💳", callback_data=f"buy_card_{key}"),
            )
        bot.send_message(chat, "Оплата Stars (Telegram) или перевод на карту:", reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("buy_stars_"))
    def initiate_stars_payment(call):
        chat = call.message.chat.id
        pkg_key = call.data[10:]
        pkg = PACKAGES.get(pkg_key)
        if pkg:
            try:
                bot.send_invoice(
                    chat,
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
        if not pkg:
            return
        user = call.from_user
        username = f"@{user.username}" if user.username else "без username"
        bot.send_message(
            chat,
            f"💳 <b>Оплата картой — пакет «{pkg['name']}»</b>\n\n"
            f"Сумма: <b>{pkg['price_rub']} ₽</b>\n"
            f"Вы получите: <b>{pkg['credits']} 🔷</b>\n\n"
            f"Переведите сумму на Т-Банк / СБЕР:\n<code>+79192329005</code>\n\n"
            f"❗️ Укажите в комментарии ваш Telegram ID: <code>{chat}</code>\n\n"
            "После перевода 🔷 начислятся вручную.",
            parse_mode="HTML",
        )
        try:
            mk = InlineKeyboardMarkup()
            mk.add(InlineKeyboardButton(f"✅ Начислить {pkg['credits']}🔷", callback_data=f"admin_grant_{chat}_{pkg_key}"))
            bot.send_message(ADMIN_ID, f"Запрос оплаты от {username} (ID: {chat}) на {pkg['name']}", reply_markup=mk)
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_grant_"))
    def admin_grant_credits(call):
        if call.from_user.id != ADMIN_ID:
            return
        parts = call.data.split("_")
        target_id = int(parts[2])
        pkg_key = parts[3]
        pkg = PACKAGES.get(pkg_key)
        if not pkg:
            return
        with data_lock:
            user_credits[target_id] += pkg["credits"]
            user_credit_history[target_id].append((time.time(), pkg["credits"], f"Покупка {pkg['name']} (карта)"))
            save_data()
        bot.edit_message_text(f"✅ Начислено пользователю {target_id}: +{pkg['credits']} 🔷", call.message.chat.id, call.message.message_id)
        try:
            bot.send_message(target_id, f"🎉 Администратор начислил вам {pkg['credits']} 🔷")
        except Exception:
            pass

    @bot.message_handler(commands=["admin"])
    def admin_panel(m):
        if m.chat.id != ADMIN_ID:
            return
        total = sum(user_credits.values())
        bot.send_message(m.chat.id, f"👑 Админ-панель\nПользователей: {len(user_credits)}\n🔷 всего: {total}")

    @bot.message_handler(commands=["addcredits"])
    def add_credits(m):
        if m.chat.id != ADMIN_ID:
            return
        try:
            _, uid, amt = m.text.split()
            uid, amt = int(uid), int(amt)
            with data_lock:
                user_credits[uid] += amt
                user_credit_history[uid].append((time.time(), amt, "Начисление админом"))
                save_data()
            bot.send_message(m.chat.id, f"✅ Начислено {amt} 🔷 пользователю {uid}")
            try:
                bot.send_message(uid, f"🎉 Администратор начислил вам {amt} 🔷")
            except Exception:
                pass
        except Exception:
            bot.send_message(m.chat.id, "Формат: /addcredits <uid> <amount>")

    @bot.message_handler(commands=["videomodels"])
    def show_video_models(m):
        if m.chat.id != ADMIN_ID:
            return
        caps = get_video_models_capabilities(force_refresh=True)
        text = "🎥 <b>Видео-модели (OpenRouter)</b>\n\n"
        for mid, model_info in list(caps.items())[:12]:
            text += f"<b>{escape(model_info.get('name', mid))}</b>\n"
            text += f"  • id: <code>{escape(mid)}</code>\n"
            text += f"  • durations: {model_info.get('supported_durations', [])}\n"
            text += f"  • resolutions: {model_info.get('supported_resolutions', [])}\n"
            text += f"  • aspect: {model_info.get('supported_aspect_ratios', [])}\n"
            text += f"  • frame_images: {model_info.get('supported_frame_images', [])}\n\n"
        bot.send_message(m.chat.id, text[:3900], parse_mode="HTML")

    @bot.message_handler(func=lambda m: m.text == "📖 Инструкция")
    def instruction(m):
        bot.send_message(
            m.chat.id,
            "Инструкция: используйте кнопки меню.\n\n"
            "Видео: Moon Web Studio теперь разделяет START, END, HERO и reference images.\n"
            "Итоговый MP4 приводится к выбранному размеру: 480p/720p/1080p и 16:9/9:16/1:1."
        )

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

    if asp not in VIDEO_SIZE_MAP:
        return jsonify({"ok": False, "error": "Доступны только форматы 16:9, 9:16 и 1:1"}), 400
    if res not in VIDEO_SIZE_MAP[asp]:
        return jsonify({"ok": False, "error": "Доступны только разрешения 480p, 720p и 1080p"}), 400

    start_frame = data.get("start_frame")
    end_frame = data.get("end_frame")
    hero_ref = data.get("hero_ref")
    reference_images = [x for x in (data.get("reference_images") or []) if x]

    # Backward compatibility со старой студией: frames[0] = start, frames[-1] = end.
    old_frames = [x for x in (data.get("frames") or []) if x]
    if old_frames and not start_frame:
        start_frame = old_frames[0]
    if old_frames and not end_frame and len(old_frames) > 1:
        end_frame = old_frames[-1]

    # Backward compatibility со старым scene-based payload.
    scenes = data.get("scenes", [])
    if scenes and not start_frame:
        frames = []
        for sc in scenes:
            sc["duration"] = int(sc.get("dur", sc.get("duration", 3)))
            if sc.get("photo"):
                frames.append(sc["photo"])
        if frames:
            start_frame = frames[0]
            end_frame = frames[-1] if len(frames) > 1 else None
        duration = sum(int(sc.get("duration", 3)) for sc in scenes)
        prompt = "\n\n".join([f"Scene {i+1} ({sc.get('duration', 3)}s): {sc.get('prompt', '')}" for i, sc in enumerate(scenes)])

    if not uid or not prompt:
        return jsonify({"ok": False, "error": "Нужен user_id и промпт"}), 400

    max_refs = int(VIDEO_MODEL_FEATURES.get(model, {}).get("max_image_refs", 9))
    if VIDEO_MODEL_FEATURES.get(model, {}).get("references"):
        refs_count = len(reference_images) + (1 if hero_ref else 0)
        if refs_count > max_refs:
            return jsonify({"ok": False, "error": f"Максимум {max_refs} референсов суммарно: HERO + reference images"}), 400
        if not start_frame and refs_count < 1:
            return jsonify({"ok": False, "error": "Для Seedance/HappyHorse загрузите START или хотя бы один HERO/reference storyboard кадр"}), 400
    else:
        refs_count = 0
        hero_ref = None
        reference_images = []
        if not start_frame:
            return jsonify({"ok": False, "error": "Для Kling 3.0 Pro нужен отдельный начальный кадр START"}), 400

    caps = get_video_models_capabilities().get(model, {})
    supported_frames = caps.get("supported_frame_images") or []
    frame_types = []
    if start_frame and "first_frame" in supported_frames:
        frame_types.append("first_frame")
    if end_frame and "last_frame" in supported_frames:
        frame_types.append("last_frame")

    is_valid, error_msg = validate_video_request(model, {
        "duration": duration,
        "resolution": res,
        "aspect_ratio": asp,
        "frame_types": frame_types,
    })
    if not is_valid:
        return jsonify({"ok": False, "error": error_msg}), 400

    cost = duration * 5
    with data_lock:
        if uid != ADMIN_ID and user_credits.get(uid, 0) < cost:
            return jsonify({"ok": False, "error": f"Недостаточно 🔷. Нужно {cost}"}), 400

    model_name = {
        "bytedance/seedance-2.0": "Seedance 2.0",
        "alibaba/happyhorse-1.1": "HappyHorse 1.1",
        "kwaivgi/kling-v3.0-pro": "Kling 3.0 Pro",
    }.get(model, model)
    target_w, target_h = get_target_video_size(asp, res)

    try:
        if VIDEO_MODEL_FEATURES.get(model, {}).get("references"):
            ref_label = f", {refs_count} refs"
        else:
            ref_label = ", first/last frame"
        bot.send_message(
            uid,
            f"🎬 Студия: {model_name}{ref_label}, {duration} сек, {asp}, {res} — итоговый размер {target_w}x{target_h}. Запускаю...",
            parse_mode="HTML",
        )
    except Exception:
        pass

    user_video_model[uid] = model
    user_video_params[uid] = {"duration": duration, "aspect_ratio": asp, "resolution": res, "audio": True}

    references = []
    if VIDEO_MODEL_FEATURES.get(model, {}).get("references"):
        if hero_ref:
            references.append(hero_ref)
            prompt = (
                "Keep the person/character from the HERO reference image consistent in every shot: "
                "same face, hairstyle, body type, outfit identity and overall appearance. "
                "Do not change identity across cuts.\n\n" + prompt
            )
        references.extend(reference_images)

    # Для Seedance/HappyHorse разрешаем режим reference-only storyboard:
    # если START не загружен, storyboard из окна reference_images идёт только как input_references,
    # без требования first_frame. Для Kling START обязателен выше.
    Thread(target=generate_video_async, args=(uid, prompt, start_frame, end_frame, None, references), daemon=True).start()
    return jsonify({"ok": True})

# ================== FLASK ROUTES ==================
@app.route("/")
def index():
    return "Bot is running"


@app.route("/studio")
def studio():
    return WEBAPP_HTML


@app.route("/health")
def health():
    return "OK"


@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory("static/uploads", filename)


@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    if not bot:
        return "", 500
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
    if not bot or not TELEGRAM_TOKEN:
        return
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
