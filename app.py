import os
import sqlite3
import logging
import requests
import time
from datetime import datetime, timedelta
from functools import wraps
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'evile-secret-key-2026')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'evile2026')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785192184:AAHckCzqabzQbGpO1E9r2DDm89zukKlvihc')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '@Evile_Prompts')
DATABASE_FILE = 'evile.db'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_characters_cache = {'data': None, 'timestamp': 0}
CACHE_TTL = 300

def dict_factory(cursor, row):
    """Convert row to dictionary for sqlite3"""
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}

@contextmanager
def get_db():
    conn = None
    cur = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = dict_factory
        cur = conn.cursor()
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                prompt TEXT NOT NULL,
                callback_key TEXT UNIQUE NOT NULL,
                logo_url TEXT DEFAULT ''
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT UNIQUE NOT NULL,
                is_subscribed INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            cur.execute("SELECT COUNT(*) as cnt FROM characters")
            row = cur.fetchone()
            count = row['cnt'] if row else 0
            if count == 0:
                cur.execute(
                    "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (?, ?, ?, ?, ?)",
                    ('لوجو ميكر', 'مصمم برومبتات شعارات احترافية',
                     'Receive any keywords in the format "Name + Element" and generate one single, ready-to-use English prompt (2-4 concise sentences): act like a master logo designer.',
                     'logo_maker', 'https://i.ibb.co/XZ3SRWQN/x.jpg')
                )
                cur.execute(
                    "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (?, ?, ?, ?, ?)",
                    ('كاتب محتوى', 'كاتب محترف لقنوات تيليجرام',
                     'أنت كاتب محتوى محترف لقنوات تيليجرام، ممنوع تماماً استخدام أي إيموجي.',
                     'content_writer', 'https://i.ibb.co/wNwDgkmV/x.png')
                )
        logger.info("SQLite Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

def update_user_activity(telegram_id):
    if not telegram_id:
        return
    try:
        with get_db() as cur:
            cur.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE telegram_id = ?", (telegram_id,))
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
            characters = cur.fetchall()
            cur.execute('SELECT * FROM notifications ORDER BY id DESC')
            notifications = cur.fetchall()
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
                "INSERT INTO users (telegram_id) VALUES (?) ON CONFLICT(telegram_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP",
                (telegram_id,)
            )
        session['telegram_id'] = telegram_id
        session.permanent = True
        is_sub = check_telegram_subscription(telegram_id)
        with get_db() as cur:
            cur.execute("UPDATE users SET is_subscribed = ? WHERE telegram_id = ?", (1 if is_sub else 0, telegram_id))
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
            cur.execute("UPDATE users SET is_subscribed = ?, last_active = CURRENT_TIMESTAMP WHERE telegram_id = ?", (1 if is_sub else 0, telegram_id))
        return jsonify({'success': is_sub, 'subscribed': is_sub})
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return jsonify({'success': False, 'subscribed': False}), 500

@app.route('/api/active_users')
def api_active_users():
    try:
        with get_db() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM users WHERE last_active > datetime('now', '-5 minutes')")
            row = cur.fetchone()
            count = row['cnt'] if row else 0
        return jsonify({'count': count})
    except Exception as e:
        logger.error(f"Active users error: {e}")
        return jsonify({'count': 0})

@app.route('/health')
def health_check():
    try:
        with get_db() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            db_ok = row is not None
        return jsonify({
            'status': 'healthy' if db_ok else 'unhealthy',
            'database': 'connected' if db_ok else 'disconnected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        flash('كلمة المرور غير صحيحة', 'error')
    return render_template('login.html')

@app.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@admin_required
def admin_panel():
    try:
        with get_db() as cur:
            cur.execute('SELECT * FROM characters ORDER BY id DESC')
            characters = cur.fetchall()
            cur.execute('SELECT * FROM notifications ORDER BY id DESC')
            notifications = cur.fetchall()
            cur.execute('SELECT COUNT(*) as cnt FROM users')
            row = cur.fetchone()
            users_count = row['cnt'] if row else 0
    except Exception as e:
        logger.error(f"Admin panel error: {e}")
        characters, notifications, users_count = [], [], 0
    return render_template('admin.html', characters=characters, notifications=notifications, users_count=users_count)

@app.route('/admin/character/add', methods=['POST'])
@admin_required
def add_character():
    name = request.form.get('name')
    description = request.form.get('description')
    prompt = request.form.get('prompt')
    callback_key = request.form.get('callback_key', name.lower().replace(' ', '_'))
    logo_url = request.form.get('logo_url', '')
    if name and description and prompt:
        try:
            with get_db() as cur:
                cur.execute("INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (?, ?, ?, ?, ?)",
                    (name, description, prompt, callback_key, logo_url))
            flash('تمت إضافة الشخصية بنجاح', 'success')
        except Exception as e:
            flash('مفتاح الشخصية موجود مسبقاً' if 'unique' in str(e).lower() else str(e), 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/character/<int:char_id>/edit', methods=['POST'])
@admin_required
def edit_character(char_id):
    name = request.form.get('name')
    description = request.form.get('description')
    prompt = request.form.get('prompt')
    logo_url = request.form.get('logo_url', '')
    if name and description and prompt:
        try:
            with get_db() as cur:
                cur.execute("UPDATE characters SET name=?, description=?, prompt=?, logo_url=? WHERE id=?",
                    (name, description, prompt, logo_url, char_id))
            flash('تم تعديل الشخصية بنجاح', 'success')
        except Exception as e:
            flash(str(e), 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/character/<int:char_id>/delete')
@admin_required
def delete_character(char_id):
    try:
        with get_db() as cur:
            cur.execute("DELETE FROM characters WHERE id=?", (char_id,))
        flash('تم حذف الشخصية', 'success')
    except Exception as e:
        flash(str(e), 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/notification/add', methods=['POST'])
@admin_required
def add_notification():
    title = request.form.get('title')
    text = request.form.get('text')
    if title and text:
        try:
            with get_db() as cur:
                cur.execute("INSERT INTO notifications (title, text) VALUES (?, ?)", (title, text))
            flash('تم إرسال الإشعار بنجاح', 'success')
        except Exception as e:
            flash(str(e), 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/notification/<int:notif_id>/delete')
@admin_required
def delete_notification(notif_id):
    try:
        with get_db() as cur:
            cur.execute("DELETE FROM notifications WHERE id=?", (notif_id,))
        flash('تم حذف الإشعار', 'success')
    except Exception as e:
        flash(str(e), 'error')
    return redirect(url_for('admin_panel'))

@app.route('/api/characters')
def api_characters():
    now = time.time()
    if _characters_cache['data'] and (now - _characters_cache['timestamp']) < CACHE_TTL:
        return jsonify(_characters_cache['data'])
    try:
        with get_db() as cur:
            cur.execute('SELECT * FROM characters ORDER BY id')
            data = cur.fetchall()
        _characters_cache['data'] = data
        _characters_cache['timestamp'] = now
        return jsonify(data)
    except Exception as e:
        logger.error(f"API characters error: {e}")
        return jsonify([])

@app.route('/api/notifications')
def api_notifications():
    try:
        with get_db() as cur:
            cur.execute('SELECT * FROM notifications ORDER BY id DESC')
            return jsonify(cur.fetchall())
    except Exception as e:
        logger.error(f"API notifications error: {e}")
        return jsonify([])

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    character_key = data.get('character', 'logo_maker')
    message = data.get('message', '')
    try:
        with get_db() as cur:
            cur.execute("SELECT * FROM characters WHERE callback_key=?", (character_key,))
            character = cur.fetchone()
    except Exception as e:
        logger.error(f"Get character error: {e}")
        return jsonify({'error': str(e)}), 500
    if not character:
        return jsonify({'error': 'Character not found'}), 404
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': request.url_root,
        'X-Title': 'EVILE'
    }
    payload = {
        'model': 'openrouter/auto',
        'messages': [
            {'role': 'system', 'content': character['prompt']},
            {'role': 'user', 'content': message}
        ],
        'temperature': 0.7
    }
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
        result = response.json()
        return jsonify({'response': result['choices'][0]['message']['content']})
    except Exception as e:
        logger.error(f"API chat error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=False)
