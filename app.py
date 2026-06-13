import os
import logging
import requests
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

# استيراد psycopg (الإصدار الأحدث المتوافق مع Python 3.14)
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

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'evile2026')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8785192184:AAHckCzqabzQbGpO1E9r2DDm89zukKlvihc')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '@Evile_Prompts')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://evile_site_user:yxWlZVZsC39DhRtXoY7e84ci6NTJgcaR@dpg-d8mpl3rsq97s739pscq0-a.oregon-postgres.render.com/evile_site')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== Database Functions ====================

def get_db():
    """الحصول على اتصال بقاعدة البيانات"""
    try:
        if PSYCOPG_VERSION == 3:
            conn = psycopg.connect(DATABASE_URL)
            return conn
        else:
            conn = psycopg.connect(DATABASE_URL)
            return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def get_cursor(conn):
    """الحصول على cursor مع دعم الإصدارين"""
    if PSYCOPG_VERSION == 3:
        return conn.cursor(row_factory=dict_row)
    else:        return conn.cursor(cursor_factory=dict_row)

def init_db():
    """تهيئة قاعدة البيانات"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
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
        
        # التحقق من وجود شخصيات
        cur.execute("SELECT COUNT(*) FROM characters")
        count = cur.fetchone()[0]
        
        if count == 0:
            cur.execute(
                "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (%s, %s, %s, %s, %s)",
                ('لوجو ميكر', 'مصمم برومبتات شعارات احترافية',
                 'Receive any keywords in the format "Name + Element" and generate one single, ready-to-use English prompt (2-4 concise sentences): act like a master logo designer, analyze and refine intelligently, mention each element once only, determine letter orientation with fluidity, integrate the element seamlessly into the name so it becomes part of the letters, maintain strong visual balance so the logo is memorable and impactful, allow one or multiple solid colors on plain white background, strictly 2D with thin graphic letterforms.',
                 'logo_maker', '')
            )
            cur.execute(
                "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (%s, %s, %s, %s, %s)",
                ('كاتب محتوى', 'كاتب محترف لقنوات تيليجرام',
                 'أنت الآن كاتب محتوى محترف لقنوات تيليجرام، ممنوع تماماً استخدام أي إيموجي. طبّق أفضل تقنيات كتابة النصوص القوية والجذابة (Copywriting).',
                 'content_writer', '')
            )
        
        conn.commit()        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

def update_user_activity(telegram_id):
    """تحديث آخر نشاط للمستخدم"""
    if not telegram_id:
        return
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE telegram_id = %s", (telegram_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Update activity error: {e}")

def check_telegram_subscription(telegram_id):
    """التحقق من اشتراك المستخدم في القناة"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember"
        params = {"chat_id": TELEGRAM_CHANNEL_ID, "user_id": telegram_id}
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        logger.info(f"Telegram API response for {telegram_id}: {data}")
        
        if data.get("ok"):
            status = data["result"].get("status")
            is_member = status in ["member", "administrator", "creator"]
            logger.info(f"User {telegram_id} status: {status}, is_member: {is_member}")
            return is_member
        else:
            logger.error(f"Telegram API error: {data.get('description', 'Unknown error')}")
            return False
    except requests.exceptions.Timeout:
        logger.error("Telegram API timeout")
        return False
    except Exception as e:
        logger.error(f"Telegram API Error: {e}")
        return False

# ==================== Auth Decorator ====================

def admin_required(f):    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ==================== Routes ====================

@app.route('/')
def index():
    telegram_id = session.get('telegram_id')
    if telegram_id:
        update_user_activity(telegram_id)
    
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute('SELECT * FROM characters ORDER BY id')
        characters = [dict(row) for row in cur.fetchall()]
        cur.execute('SELECT * FROM notifications ORDER BY id DESC')
        notifications = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Index error: {e}")
        characters = []
        notifications = []
    
    channel_url = f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}"
    
    return render_template('index.html', 
                         characters=characters,
                         notifications=notifications,
                         telegram_id=telegram_id,
                         channel_url=channel_url)

@app.route('/register', methods=['POST'])
def register():
    """تسجيل المستخدم"""
    try:
        telegram_id = request.form.get('telegram_id', '').strip()
        
        if not telegram_id:
            return jsonify({'success': False, 'message': 'الرجاء إدخال معرّف تيليجرام'}), 400
        
        if not telegram_id.isdigit():
            return jsonify({'success': False, 'message': 'المعرّف يجب أن يحتوي على أرقام فقط'}), 400
        
        # حفظ في قاعدة البيانات        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (telegram_id) VALUES (%s) ON CONFLICT (telegram_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP",
                (telegram_id,)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as db_err:
            logger.error(f"Database error in register: {db_err}")
            return jsonify({'success': False, 'message': 'خطأ في قاعدة البيانات'}), 500
        
        # حفظ في الجلسة
        session['telegram_id'] = telegram_id
        session.permanent = True
        
        # التحقق من الاشتراك
        is_sub = check_telegram_subscription(telegram_id)
        
        # تحديث حالة الاشتراك
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET is_subscribed = %s WHERE telegram_id = %s",
                (is_sub, telegram_id)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as db_err:
            logger.error(f"Database error updating subscription: {db_err}")
        
        return jsonify({
            'success': True,
            'subscribed': is_sub,
            'telegram_id': telegram_id
        })
        
    except Exception as e:
        logger.error(f"Register error: {e}")
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'}), 500

@app.route('/api/verify_subscription', methods=['POST'])
def api_verify_subscription():
    """التحقق من الاشتراك"""
    try:
        telegram_id = session.get('telegram_id')        if not telegram_id:
            return jsonify({'success': False, 'message': 'غير مسجل', 'subscribed': False}), 401
        
        is_sub = check_telegram_subscription(telegram_id)
        
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET is_subscribed = %s, last_active = CURRENT_TIMESTAMP WHERE telegram_id = %s",
                (is_sub, telegram_id)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as db_err:
            logger.error(f"Database error in verify: {db_err}")
        
        return jsonify({
            'success': is_sub,
            'subscribed': is_sub,
            'message': 'مشترك' if is_sub else 'لم يتم الاشتراك بعد'
        })
    except Exception as e:
        logger.error(f"Verify subscription error: {e}")
        return jsonify({'success': False, 'subscribed': False, 'message': str(e)}), 500

@app.route('/api/active_users')
def api_active_users():
    """عدد المستخدمين النشطين"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '5 minutes'")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({'count': count})
    except Exception as e:
        logger.error(f"Active users error: {e}")
        return jsonify({'count': 0})

@app.route('/keepalive')
def keepalive():
    """Endpoint للحفاظ على نشاط الموقع"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]        cur.close()
        conn.close()
        return jsonify({'status': 'alive', 'users': count, 'time': datetime.now().isoformat()})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ==================== Admin Routes ====================

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
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute('SELECT * FROM characters ORDER BY id DESC')
        characters = [dict(row) for row in cur.fetchall()]
        cur.execute('SELECT * FROM notifications ORDER BY id DESC')
        notifications = [dict(row) for row in cur.fetchall()]
        cur.execute('SELECT COUNT(*) FROM users')
        users_count = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Admin panel error: {e}")
        characters = []
        notifications = []
        users_count = 0
    
    return render_template('admin.html', 
                         characters=characters,
                         notifications=notifications,
                         users_count=users_count)

@app.route('/admin/character/add', methods=['POST'])@admin_required
def add_character():
    name = request.form.get('name')
    description = request.form.get('description')
    prompt = request.form.get('prompt')
    callback_key = request.form.get('callback_key', name.lower().replace(' ', '_'))
    logo_url = request.form.get('logo_url', '')
    
    if name and description and prompt:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO characters (name, description, prompt, callback_key, logo_url) VALUES (%s, %s, %s, %s, %s)",
                (name, description, prompt, callback_key, logo_url)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('تمت إضافة الشخصية بنجاح', 'success')
        except Exception as e:
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                flash('مفتاح الشخصية موجود مسبقاً', 'error')
            else:
                flash(f'خطأ: {str(e)}', 'error')
    
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
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE characters SET name=%s, description=%s, prompt=%s, logo_url=%s WHERE id=%s",
                (name, description, prompt, logo_url, char_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('تم تعديل الشخصية بنجاح', 'success')
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'error')    
    return redirect(url_for('admin_panel'))

@app.route('/admin/character/<int:char_id>/delete')
@admin_required
def delete_character(char_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM characters WHERE id=%s", (char_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash('تم حذف الشخصية', 'success')
    except Exception as e:
        flash(f'خطأ: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/notification/add', methods=['POST'])
@admin_required
def add_notification():
    title = request.form.get('title')
    text = request.form.get('text')
    if title and text:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("INSERT INTO notifications (title, text) VALUES (%s, %s)", (title, text))
            conn.commit()
            cur.close()
            conn.close()
            flash('تم إرسال الإشعار بنجاح', 'success')
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/notification/<int:notif_id>/delete')
@admin_required
def delete_notification(notif_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM notifications WHERE id=%s", (notif_id,))
        conn.commit()
        cur.close()
        conn.close()
        flash('تم حذف الإشعار', 'success')
    except Exception as e:
        flash(f'خطأ: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))
# ==================== API Routes ====================

@app.route('/api/characters')
def api_characters():
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute('SELECT * FROM characters ORDER BY id')
        characters = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(characters)
    except Exception as e:
        return jsonify([])

@app.route('/api/notifications')
def api_notifications():
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute('SELECT * FROM notifications ORDER BY id DESC')
        notifications = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(notifications)
    except Exception as e:
        return jsonify([])

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    character_key = data.get('character', 'logo_maker')
    message = data.get('message', '')
    
    try:
        conn = get_db()
        cur = get_cursor(conn)
        cur.execute("SELECT * FROM characters WHERE callback_key=%s", (character_key,))
        character = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Get character error: {e}")
        return jsonify({'error': 'Database error'}), 500
    
    if not character:
        return jsonify({'error': 'Character not found'}), 404
    
    headers = {        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
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
        logger.error(f"API Error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== Main ====================

if __name__ == '__main__':
    init_db()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
