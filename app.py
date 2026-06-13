import os
import sqlite3
import logging
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'evile-secret-key-2026')

# قراءة من متغيرات البيئة
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'evile2026')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DATABASE = 'evile.db'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        prompt TEXT NOT NULL,
        callback_key TEXT UNIQUE NOT NULL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    count = conn.execute('SELECT COUNT(*) FROM characters').fetchone()[0]
    if count == 0:
        conn.execute("INSERT INTO characters (name, description, prompt, callback_key) VALUES (?, ?, ?, ?)",
            ('لوجو ميكر', 'مصمم برومبتات شعارات احترافية',
             'Receive any keywords in the format "Name + Element" and generate one single, ready-to-use English prompt (2-4 concise sentences): act like a master logo designer, analyze and refine intelligently, mention each element once only, determine letter orientation with fluidity, integrate the element seamlessly into the name so it becomes part of the letters, maintain strong visual balance so the logo is memorable and impactful, allow one or multiple solid colors on plain white background, strictly 2D with thin graphic letterforms.',
             'logo_maker'))
        conn.execute("INSERT INTO characters (name, description, prompt, callback_key) VALUES (?, ?, ?, ?)",
            ('كاتب محتوى', 'كاتب محترف لقنوات تيليجرام',
             'أنت الآن كاتب محتوى محترف لقنوات تيليجرام، ممنوع تماماً استخدام أي إيموجي. طبّق أفضل تقنيات كتابة النصوص القوية والجذابة (Copywriting).',
             'content_writer'))
    conn.commit()
    conn.close()

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    conn = get_db()
    characters = conn.execute('SELECT * FROM characters ORDER BY id').fetchall()
    notifications = conn.execute('SELECT * FROM notifications ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('index.html', 
                         characters=[dict(c) for c in characters],
                         notifications=[dict(n) for n in notifications])

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            flash('كلمة المرور غير صحيحة', 'error')
    return render_template('login.html')

@app.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@admin_required
def admin_panel():
    conn = get_db()
    characters = conn.execute('SELECT * FROM characters ORDER BY id DESC').fetchall()
    notifications = conn.execute('SELECT * FROM notifications ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('admin.html', 
                         characters=[dict(c) for c in characters],
                         notifications=[dict(n) for n in notifications])

@app.route('/admin/character/add', methods=['POST'])
@admin_required
def add_character():    name = request.form.get('name')
    description = request.form.get('description')
    prompt = request.form.get('prompt')
    callback_key = request.form.get('callback_key', name.lower().replace(' ', '_'))
    
    if name and description and prompt:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO characters (name, description, prompt, callback_key) VALUES (?, ?, ?, ?)",
                (name, description, prompt, callback_key)
            )
            conn.commit()
            flash('تمت إضافة الشخصية بنجاح', 'success')
        except sqlite3.IntegrityError:
            flash('مفتاح الشخصية موجود مسبقاً', 'error')
        finally:
            conn.close()
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/character/<int:char_id>/edit', methods=['POST'])
@admin_required
def edit_character(char_id):
    name = request.form.get('name')
    description = request.form.get('description')
    prompt = request.form.get('prompt')
    
    if name and description and prompt:
        conn = get_db()
        conn.execute(
            "UPDATE characters SET name=?, description=?, prompt=? WHERE id=?",
            (name, description, prompt, char_id)
        )
        conn.commit()
        conn.close()
        flash('تم تعديل الشخصية بنجاح', 'success')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/character/<int:char_id>/delete')
@admin_required
def delete_character(char_id):
    conn = get_db()
    conn.execute("DELETE FROM characters WHERE id=?", (char_id,))
    conn.commit()
    conn.close()
    flash('تم حذف الشخصية', 'success')
    return redirect(url_for('admin_panel'))
@app.route('/admin/notification/add', methods=['POST'])
@admin_required
def add_notification():
    title = request.form.get('title')
    text = request.form.get('text')
    
    if title and text:
        conn = get_db()
        conn.execute("INSERT INTO notifications (title, text) VALUES (?, ?)", (title, text))
        conn.commit()
        conn.close()
        flash('تم إرسال الإشعار بنجاح', 'success')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/notification/<int:notif_id>/delete')
@admin_required
def delete_notification(notif_id):
    conn = get_db()
    conn.execute("DELETE FROM notifications WHERE id=?", (notif_id,))
    conn.commit()
    conn.close()
    flash('تم حذف الإشعار', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/api/characters')
def api_characters():
    conn = get_db()
    characters = conn.execute('SELECT * FROM characters ORDER BY id').fetchall()
    conn.close()
    return jsonify([dict(c) for c in characters])

@app.route('/api/notifications')
def api_notifications():
    conn = get_db()
    notifications = conn.execute('SELECT * FROM notifications ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify([dict(n) for n in notifications])

@app.route('/api/chat', methods=['POST'])
def api_chat():
    import aiohttp
    data = request.json
    character_key = data.get('character', 'logo_maker')
    message = data.get('message', '')
    
    conn = get_db()
    character = conn.execute("SELECT * FROM characters WHERE callback_key=?", (character_key,)).fetchone()
    conn.close()
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
        import requests
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers)
        result = response.json()
        return jsonify({'response': result['choices'][0]['message']['content']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
