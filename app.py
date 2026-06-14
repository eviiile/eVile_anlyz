import os
import logging
import requests
import time
from datetime import datetime, timedelta
from functools import wraps
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

# محاولة استيراد psycopg3 مع دعم القواميس، وإلا استخدم psycopg2
try:
    import psycopg
    from psycopg.rows import dict_row
    PSYCOPG_VERSION = 3
except ImportError:
    import psycopg2 as psycopg
    from psycopg2.extras import RealDictCursor as dict_row
    PSYCOPG_VERSION = 2

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'evile-secret-key-2026')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'evile2026')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785192184:AAHckCzqabzQbGpO1E9r2DDm89zukKlvihc')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '@Evile_Prompts')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://evile_site_user:yxWlZVZsC39DhRtXoY7e84ci6NTJgcaR@dpg-d8mpl3rsq97s739pscq0-a.oregon-postgres.render.com/evile_site')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_characters_cache = {'data': None, 'timestamp': 0}
CACHE_TTL = 300

@contextmanager
def get_db():
    conn = None
    cur = None
    try:
        if PSYCOPG_VERSION == 3:
            conn = psycopg.connect(DATABASE_URL)
            cur = conn.cursor(row_factory=dict_row)
        else:
            conn = psycopg.connect(DATABASE_URL)
            cur = conn.cursor(cursor_factory=dict_row)
        yield cur
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {str(e)}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def init_db():
    try:
        with get_db() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS characters (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                prompt TEXT NOT NULL,
                callback_key TEXT UNIQUE NOT NULL,
                logo_url TEXT DEFAULT ''
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id TEXT UNIQUE NOT NULL,
                is_subscribed BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            cur.execute("SELECT COUNT(*) FROM characters")
            row = cur.fetchone()
            count = row['count'] if row and 'count' in row else row[0] if row else 0
            if count == 0:
                cur.execute(
                    "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (%s, %s, %s, %s, %s)",
                    ('لوجو ميكر', 'مصمم برومبتات شعارات احترافية',
                     'Receive any keywords in the format "Name + Element" and generate one single, ready-to-use English prompt (2-4 concise sentences): act like a master logo designer.',
                     'logo_maker', 'https://i.ibb.co/XZ3SRWQN/x.jpg')
                )
                cur.execute(
                    "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (%s, %s, %s, %s, %s)",
                    ('كاتب محتوى', 'كاتب محترف لقنوات تيليجرام',
                     'أنت كاتب محتوى محترف لقنوات تيليجرام، ممنوع تماماً استخدام أي إيموجي.',
                     'content_writer', 'https://i.ibb.co/wNwDgkmV/x.png')
                )
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

def update_user_activity(telegram_id):
    if not telegram_id:
        return
    try:
        with get_db() as cur:
            cur.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE telegram_id = %s", (telegram_id,))
    except Exception as e:
        logger.error(f"Update activity error: {e}")

def check_telegram_subscription(telegram_id):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember"
        params = {"chat_id": TELEGRAM_CHANNEL_ID, "user_id": telegram_id}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data.get("ok"):
            status = data["result"].get("status")
            return status in ["member", "administrator", "creator"]
        return False
    except Exception as e:
        logger.error(f"Telegram API Error: {e}")
        return False

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    telegram_id = session.get('telegram_id')
    if telegram_id:
        update_user_activity(telegram_id)
    try:
        with get_db() as cur:
            cur.execute('SELECT * FROM characters ORDER BY id')
            characters = [dict(row) for row in cur.fetchall()]
            cur.execute('SELECT * FROM notifications ORDER BY id DESC')
            notifications = [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Index error: {e}")
        characters, notifications = [], []
    channel_url = f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}"
    return render_template('index.html',
                         characters=characters,
                         notifications=notifications,
                         telegram_id=telegram_id,
                         channel_url=channel_url)

@app.route('/register', methods=['POST'])
def register():
    try:
        telegram_id = request.form.get('telegram_id', '').strip()
        if not telegram_id or not telegram_id.isdigit():
            return jsonify({'success': False, 'message': 'معرّف غير صحيح'}), 400
        with get_db() as cur:
            cur.execute(
                "INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT (telegram_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP",
                (telegram_id,)
            )
        session['telegram_id'] = telegram_id
        session.permanent = True
        is_sub = check_telegram_subscription(telegram_id)
        with get_db() as cur:
            cur.execute("UPDATE users SET is_subscribed = %s WHERE telegram_id = %s", (is_sub, telegram_id))
        return jsonify({'success': True, 'subscribed': is_sub})
    except Exception as e:
        logger.error(f"Register error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/verify_subscription', methods=['POST'])
def api_verify_subscription():
    try:
        telegram_id = session.get('telegram_id')
        if not telegram_id:
            return jsonify({'success': False, 'subscribed': False}), 401
        is_sub = check_telegram_subscription(telegram_id)
        with get_db() as cur:
            cur.execute("UPDATE users SET is_subscribed = %s, last_active = CURRENT_TIMESTAMP WHERE telegram_id = %s", (is_sub, telegram_id))
        return jsonify({'success': is_sub, 'subscribed': is_sub})
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return jsonify({'success': False, 'subscribed': False}), 500
