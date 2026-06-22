# Замените существующие load_data() и save_data() на эти:

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GIST_ID = os.getenv("GIST_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def load_data():
    global user_credits, user_credit_history, user_message_count
    if not GIST_ID or not GITHUB_TOKEN:
        logging.warning("GIST_ID или GITHUB_TOKEN не заданы. Использую локальный файл (может пропасть при перезапуске).")
        # fallback на локальный файл
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            user_credits = defaultdict(int, data.get('credits', {}))
            user_credit_history = defaultdict(list, data.get('history', {}))
            user_message_count = defaultdict(int, data.get('messages', {}))
        except:
            user_credits = defaultdict(int)
            user_credit_history = defaultdict(list)
            user_message_count = defaultdict(int)
        return

    # Загрузка из GitHub Gist
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            gist_data = r.json()
            content = gist_data['files']['bot_data.json']['content']
            data = json.loads(content)
            user_credits = defaultdict(int, data.get('credits', {}))
            user_credit_history = defaultdict(list, data.get('history', {}))
            user_message_count = defaultdict(int, data.get('messages', {}))
            logging.info("Данные успешно загружены из GitHub Gist")
        else:
            logging.error(f"Ошибка загрузки из Gist: {r.status_code}")
            # Используем локальный файл как fallback
            load_data_local()
    except:
        logging.error("Не удалось загрузить данные из Gist, использую локальный файл")
        load_data_local()

def load_data_local():
    global user_credits, user_credit_history, user_message_count
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        user_credits = defaultdict(int, data.get('credits', {}))
        user_credit_history = defaultdict(list, data.get('history', {}))
        user_message_count = defaultdict(int, data.get('messages', {}))
    except:
        user_credits = defaultdict(int)
        user_credit_history = defaultdict(list)
        user_message_count = defaultdict(int)

def save_data():
    # Сохраняем локально (резервная копия)
    with data_lock:
        data = {
            'credits': dict(user_credits),
            'history': {k: v for k, v in user_credit_history.items()},
            'messages': dict(user_message_count)
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Если настроен Gist, обновляем его
    if GIST_ID and GITHUB_TOKEN:
        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = {
            "files": {
                "bot_data.json": {
                    "content": json.dumps(data, ensure_ascii=False, indent=2)
                }
            }
        }
        try:
            r = requests.patch(url, json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                logging.info("Данные успешно сохранены в GitHub Gist")
            else:
                logging.error(f"Ошибка сохранения в Gist: {r.status_code} {r.text}")
        except:
            logging.error("Не удалось сохранить данные в Gist")
