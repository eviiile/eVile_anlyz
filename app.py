import os
import sqlite3
import logging
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'evile-secret-key-2026')

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'evile2026')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')
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
        callback_key TEXT UNIQUE NOT NULL,
        logo_url TEXT DEFAULT ''
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    count = conn.execute('SELECT COUNT(*) FROM characters').fetch
