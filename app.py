# app.py
# pip install flask flask-socketio eventlet werkzeug pillow gunicorn

from flask import Flask, request, render_template_string, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import json
import random
import string
import base64
from datetime import datetime, timedelta
import re
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-123456789')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'voice'), exist_ok=True)

DEFAULT_PROFILE_DIR = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles-default')
os.makedirs(DEFAULT_PROFILE_DIR, exist_ok=True)

def create_default_profile_images():
    default_png = "iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAYAAABw4pVUAAAABmJLR0QA/wD/AP+gvaeTAAAAj0lEQVR4nO3BAQ0AAADCoPdPbQ8HxQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8GBXYAAVXJYlMAAAAASUVORK5CYII="
    
    png_path = os.path.join(DEFAULT_PROFILE_DIR, 'user.png')
    if not os.path.exists(png_path):
        with open(png_path, 'wb') as f:
            f.write(base64.b64decode(default_png))
    
    jpg_path = os.path.join(DEFAULT_PROFILE_DIR, 'user.jpg')
    if not os.path.exists(jpg_path):
        shutil.copy(png_path, jpg_path)

create_default_profile_images()

socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, manage_session=False)

# ============== دیتابیس ==============
def init_db():
    conn = sqlite3.connect('messenger.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  user_tag TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  display_name TEXT,
                  bio TEXT,
                  profile_pic TEXT,
                  is_bot BOOLEAN DEFAULT 0,
                  bot_token TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rooms
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  room_tag TEXT UNIQUE NOT NULL,
                  room_type TEXT CHECK(room_type IN ('group', 'channel')),
                  name TEXT NOT NULL,
                  description TEXT,
                  owner_id INTEGER,
                  is_private BOOLEAN DEFAULT 1,
                  voice_enabled BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (owner_id) REFERENCES users (id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS room_members
                 (room_id INTEGER,
                  user_id INTEGER,
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  role TEXT DEFAULT 'member',
                  PRIMARY KEY (room_id, user_id),
                  FOREIGN KEY (room_id) REFERENCES rooms (id),
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  sender_id INTEGER,
                  room_id INTEGER,
                  content TEXT,
                  file_path TEXT,
                  file_name TEXT,
                  is_voice BOOLEAN DEFAULT 0,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  reply_to INTEGER,
                  FOREIGN KEY (sender_id) REFERENCES users (id),
                  FOREIGN KEY (room_id) REFERENCES rooms (id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bots
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  bot_token TEXT UNIQUE NOT NULL,
                  bot_name TEXT NOT NULL,
                  owner_id INTEGER,
                  room_id INTEGER,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (owner_id) REFERENCES users (id),
                  FOREIGN KEY (room_id) REFERENCES rooms (id))''')
    
    conn.commit()
    
    try:
        c.execute("SELECT voice_enabled FROM rooms LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE rooms ADD COLUMN voice_enabled BOOLEAN DEFAULT 0")
            print("✅ ستون voice_enabled به جدول rooms اضافه شد!")
        except:
            pass
    
    conn.commit()
    conn.close()
    print("✅ دیتابیس ساخته شد!")

init_db()

# ============== Helper Functions ==============
def get_db():
    conn = sqlite3.connect('messenger.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_user_by_username(username):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    return user

def get_user_by_tag(user_tag):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE user_tag = ?', (user_tag,)).fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user

def get_room_by_tag(room_tag):
    conn = get_db()
    room = conn.execute('SELECT * FROM rooms WHERE room_tag = ?', (room_tag,)).fetchone()
    conn.close()
    return room

def validate_tag(tag):
    if not tag or len(tag) < 3 or len(tag) > 30:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_]+$', tag))

def get_profile_pic_path(profile_pic):
    if profile_pic and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles', profile_pic)):
        return f"/uploads/profiles/{profile_pic}"
    
    default_png = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles-default', 'user.png')
    default_jpg = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles-default', 'user.jpg')
    
    if os.path.exists(default_png):
        return f"/uploads/profiles-default/user.png"
    elif os.path.exists(default_jpg):
        return f"/uploads/profiles-default/user.jpg"
    
    emojis = ['👤', '👨', '👩', '🧑', '👦', '👧']
    return random.choice(emojis)

def create_room(room_tag, room_type, name, owner_id, description='', is_private=True, voice_enabled=False):
    conn = get_db()
    conn.execute('''INSERT INTO rooms (room_tag, room_type, name, description, owner_id, is_private, voice_enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                 (room_tag, room_type, name, description, owner_id, is_private, voice_enabled))
    conn.commit()
    room = conn.execute('SELECT * FROM rooms WHERE room_tag = ?', (room_tag,)).fetchone()
    conn.close()
    return room

def add_member_to_room(room_id, user_id, role='member'):
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO room_members (room_id, user_id, role) VALUES (?, ?, ?)',
                 (room_id, user_id, role))
    conn.commit()
    conn.close()

def remove_member_from_room(room_id, user_id):
    conn = get_db()
    conn.execute('DELETE FROM room_members WHERE room_id = ? AND user_id = ?', (room_id, user_id))
    conn.commit()
    conn.close()

def is_member_of_room(room_id, user_id):
    conn = get_db()
    result = conn.execute('SELECT * FROM room_members WHERE room_id = ? AND user_id = ?',
                          (room_id, user_id)).fetchone()
    conn.close()
    return result is not None

def get_user_role(room_id, user_id):
    conn = get_db()
    result = conn.execute('SELECT role FROM room_members WHERE room_id = ? AND user_id = ?',
                          (room_id, user_id)).fetchone()
    conn.close()
    return result['role'] if result else None

def get_room_members(room_id):
    conn = get_db()
    members = conn.execute('''SELECT u.id, u.username, u.user_tag, u.display_name, u.profile_pic, rm.role 
                              FROM room_members rm
                              JOIN users u ON rm.user_id = u.id
                              WHERE rm.room_id = ?''', (room_id,)).fetchall()
    conn.close()
    return members

def get_user_rooms(user_id):
    conn = get_db()
    rooms = conn.execute('''SELECT r.*, rm.role,
                            (SELECT COUNT(*) FROM room_members WHERE room_id = r.id) as member_count
                            FROM room_members rm
                            JOIN rooms r ON rm.room_id = r.id
                            WHERE rm.user_id = ?''', (user_id,)).fetchall()
    conn.close()
    return rooms

def save_message(sender_id, room_id, content='', file_path=None, file_name=None, is_voice=False, reply_to=None):
    conn = get_db()
    cur = conn.execute('''INSERT INTO messages (sender_id, room_id, content, file_path, file_name, is_voice, reply_to)
                          VALUES (?, ?, ?, ?, ?, ?, ?)''',
                       (sender_id, room_id, content, file_path, file_name, is_voice, reply_to))
    conn.commit()
    msg_id = cur.lastrowid
    msg = conn.execute('''SELECT m.*, u.username, u.user_tag, u.display_name, u.profile_pic
                          FROM messages m
                          JOIN users u ON m.sender_id = u.id
                          WHERE m.id = ?''', (msg_id,)).fetchone()
    conn.close()
    return msg

def get_room_messages(room_id, limit=100):
    conn = get_db()
    messages = conn.execute('''SELECT m.*, u.username, u.user_tag, u.display_name, u.profile_pic,
                               (SELECT content FROM messages WHERE id = m.reply_to) as reply_content
                               FROM messages m
                               JOIN users u ON m.sender_id = u.id
                               WHERE m.room_id = ?
                               ORDER BY m.timestamp DESC LIMIT ?''', (room_id, limit)).fetchall()
    conn.close()
    return list(reversed(messages))

def search_users_by_tag_or_name(query):
    conn = get_db()
    users = conn.execute('''SELECT id, username, user_tag, display_name, bio, profile_pic
                           FROM users 
                           WHERE (user_tag LIKE ? OR display_name LIKE ? OR username LIKE ?)
                           AND is_bot = 0
                           LIMIT 30''', (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    return users

def search_rooms_by_tag_or_name(query):
    user_id = session.get('user_id', 0)
    conn = get_db()
    rooms = conn.execute('''SELECT r.*, u.display_name as owner_name,
                            (SELECT COUNT(*) FROM room_members WHERE room_id = r.id) as member_count
                           FROM rooms r
                           JOIN users u ON r.owner_id = u.id
                           WHERE (r.room_tag LIKE ? OR r.name LIKE ?)
                           AND (r.is_private = 0 OR r.owner_id = ?)
                           LIMIT 30''', (f'%{query}%', f'%{query}%', user_id)).fetchall()
    conn.close()
    return rooms

def create_bot(owner_id, bot_name, room_tag):
    token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    conn = get_db()
    bot_username = f"bot_{bot_name}_{random.randint(1000,9999)}"
    bot_tag = f"bot_{bot_name}_{random.randint(1000,9999)}"
    cur = conn.execute('''INSERT INTO users (username, user_tag, password, display_name, is_bot, bot_token)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (bot_username, bot_tag, 'bot_password_123', bot_name, 1, token))
    bot_id = cur.lastrowid
    conn.execute('''INSERT INTO bots (bot_token, bot_name, owner_id, room_id)
                    VALUES (?, ?, ?, ?)''',
                 (token, bot_name, owner_id, None))
    conn.commit()
    conn.close()
    return {'bot_id': bot_id, 'token': token}

online_users = {}
user_sessions = {}

# ============== HTML ==============
MAIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>پیام‌رسان</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Tahoma, sans-serif; background: #0e1621; color: #fff; height: 100vh; overflow: hidden; }
        .auth-container { display: flex; align-items: center; justify-content: center; height: 100vh; }
        .auth-box { max-width: 420px; width: 100%; margin: 20px; background: #17212b; padding: 30px; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }
        .auth-box .logo { text-align: center; margin-bottom: 25px; }
        .auth-box .logo h1 { color: #65b9f6; font-size: 28px; }
        .auth-box .logo p { color: #8caab9; font-size: 14px; margin-top: 5px; }
        .auth-box input, .auth-box textarea { width: 100%; padding: 12px 16px; margin: 8px 0; background: #242f3d; border: none; border-radius: 10px; color: #fff; font-size: 16px; transition: all 0.3s; }
        .auth-box input:focus, .auth-box textarea:focus { outline: 2px solid #65b9f6; background: #2a3a4a; }
        .auth-box textarea { height: 60px; resize: vertical; }
        .auth-box button { width: 100%; padding: 14px; background: #65b9f6; color: #0e1621; border: none; border-radius: 10px; cursor: pointer; font-weight: bold; font-size: 17px; transition: all 0.3s; margin-top: 10px; }
        .auth-box button:hover { transform: translateY(-2px); box-shadow: 0 4px 20px rgba(101, 185, 246, 0.3); }
        .auth-box button:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .auth-box .switch { text-align: center; margin-top: 18px; color: #65b9f6; cursor: pointer; padding: 10px; border-radius: 8px; transition: background 0.2s; }
        .auth-box .switch:hover { background: #242f3d; }
        .auth-box .note { font-size: 12px; color: #8caab9; margin: 5px 0; }
        .auth-box .error { color: #e74c3c; text-align: center; margin: 10px 0; padding: 10px; background: #2c1a1a; border-radius: 8px; display: none; }
        .auth-box .error.show { display: block; }
        .auth-box .success { color: #2ecc71; text-align: center; margin: 10px 0; padding: 10px; background: #1a2c1a; border-radius: 8px; display: none; }
        .auth-box .success.show { display: block; }
        .auth-box .register-fields { display: none; }
        .auth-box .register-fields.show { display: block; }
        .auth-box .tag-preview { color: #65b9f6; font-size: 13px; margin: 4px 0 8px 0; }
        .auth-box .tag-preview span { background: #242f3d; padding: 2px 10px; border-radius: 4px; }
        .hidden { display: none !important; }
        .app { display: none; height: 100vh; }
        .sidebar { width: 280px; background: #17212b; border-left: 1px solid #242f3d; display: flex; flex-direction: column; height: 100vh; position: fixed; right: 0; top: 0; z-index: 10; }
        .sidebar-header { padding: 12px; background: #1e2a36; }
        .sidebar-header .user-info { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; cursor: pointer; }
        .sidebar-header .user-info .avatar { width: 40px; height: 40px; border-radius: 50%; background: #2b5278; display: flex; align-items: center; justify-content: center; font-size: 18px; overflow: hidden; flex-shrink: 0; }
        .sidebar-header .user-info .avatar img { width: 100%; height: 100%; object-fit: cover; }
        .sidebar-header .user-info .avatar .emoji-avatar { font-size: 24px; }
        .sidebar-header .user-info .name { font-weight: bold; font-size: 14px; }
        .sidebar-header .user-info .tag { font-size: 11px; color: #8caab9; }
        .sidebar-header input { width: 100%; padding: 10px; background: #242f3d; border: none; border-radius: 8px; color: #fff; font-size: 14px; }
        .sidebar-content { flex: 1; overflow-y: auto; padding: 8px; }
        .sidebar-item { padding: 10px; border-radius: 8px; margin: 4px 0; cursor: pointer; transition: background 0.2s; }
        .sidebar-item:hover { background: #242f3d; }
        .sidebar-item.active { background: #2b5278; }
        .sidebar-item .type { font-size: 10px; color: #8caab9; margin-left: 5px; }
        .sidebar-item .tag { font-size: 10px; color: #8caab9; }
        .sidebar-item .voice-badge { background: #34a853; color: #fff; padding: 1px 6px; border-radius: 10px; font-size: 9px; margin-right: 5px; }
        .sidebar-bottom { padding: 8px; border-top: 1px solid #242f3d; display: flex; flex-wrap: wrap; gap: 4px; }
        .sidebar-bottom button { flex: 1; min-width: 60px; padding: 6px; background: #2b5278; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-size: 11px; transition: opacity 0.2s; }
        .sidebar-bottom button:hover { opacity: 0.8; }
        .sidebar-bottom .logout-btn { background: #e74c3c; }
        .sidebar-status { padding: 6px; text-align: center; border-top: 1px solid #242f3d; font-size: 11px; color: #8caab9; display: flex; justify-content: space-between; }
        .chat-area { margin-right: 280px; height: 100vh; display: flex; flex-direction: column; background: #0e1621; }
        .chat-header { padding: 12px 16px; background: #17212b; border-bottom: 1px solid #242f3d; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
        .chat-header .room-info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .chat-header .room-info .title { font-weight: bold; font-size: 16px; }
        .chat-header .room-info .tag { font-size: 11px; color: #8caab9; }
        .chat-header .room-actions { display: flex; gap: 6px; flex-wrap: wrap; }
        .chat-header .room-actions button { padding: 4px 10px; background: #2b5278; border: none; border-radius: 4px; color: #fff; cursor: pointer; font-size: 11px; }
        .chat-header .room-actions .voice-btn { background: #34a853; }
        .chat-header .room-actions .voice-btn.active { background: #e74c3c; }
        .messages { flex: 1; padding: 16px; overflow-y: auto; }
        .message { margin-bottom: 10px; display: flex; flex-direction: column; max-width: 80%; }
        .message .msg-sender { font-size: 11px; color: #8caab9; margin-bottom: 2px; display: flex; align-items: center; gap: 6px; }
        .message .msg-sender .avatar-small { width: 20px; height: 20px; border-radius: 50%; background: #2b5278; display: flex; align-items: center; justify-content: center; font-size: 10px; overflow: hidden; flex-shrink: 0; }
        .message .msg-sender .avatar-small img { width: 100%; height: 100%; object-fit: cover; }
        .message .msg-content { background: #2b5278; padding: 10px 14px; border-radius: 12px; word-wrap: break-word; display: inline-block; max-width: 100%; }
        .message .msg-content img { max-width: 250px; max-height: 250px; border-radius: 8px; }
        .message .msg-content audio { max-width: 250px; }
        .message .msg-time { font-size: 9px; color: #8caab9; margin-top: 2px; }
        .message.self { align-items: flex-end; }
        .message.self .msg-content { background: #65b9f6; color: #0e1621; }
        .input-area { padding: 10px; background: #17212b; border-top: 1px solid #242f3d; display: flex; gap: 8px; }
        .input-area input[type="text"] { flex: 1; padding: 10px; background: #242f3d; border: none; border-radius: 8px; color: #fff; font-size: 15px; }
        .input-area button { padding: 10px 16px; background: #65b9f6; color: #0e1621; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 14px; }
        .input-area .file-btn { background: #2b5278; padding: 10px 14px; border-radius: 8px; cursor: pointer; }
        .input-area .voice-record-btn { background: #e74c3c; padding: 10px 14px; border-radius: 8px; cursor: pointer; animation: pulse 1.5s infinite; }
        .input-area .voice-record-btn.recording { background: #c0392b; }
        .input-area input[type="file"] { display: none; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
        .popup-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; padding: 16px; }
        .popup { background: #17212b; padding: 24px; border-radius: 12px; max-width: 500px; width: 100%; max-height: 90vh; overflow-y: auto; }
        .popup h3 { margin-bottom: 15px; color: #65b9f6; }
        .popup input, .popup textarea { width: 100%; padding: 10px; margin: 6px 0; background: #242f3d; border: none; border-radius: 8px; color: #fff; font-size: 15px; }
        .popup textarea { height: 80px; resize: vertical; }
        .popup .note { font-size: 11px; color: #8caab9; margin: 4px 0; }
        .popup .actions { display: flex; gap: 10px; margin-top: 15px; }
        .popup .actions button { flex: 1; padding: 10px; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 15px; }
        .popup .actions .cancel { background: #242f3d; color: #fff; }
        .popup .actions .confirm { background: #65b9f6; color: #0e1621; }
        .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #2b5278; color: #fff; padding: 12px 24px; border-radius: 8px; z-index: 2000; max-width: 90%; text-align: center; font-size: 14px; }
        .search-results { margin-top: 8px; max-height: 200px; overflow-y: auto; }
        .search-result-item { padding: 10px; background: #242f3d; border-radius: 8px; margin: 4px 0; cursor: pointer; display: flex; align-items: center; gap: 10px; }
        .search-result-item:hover { background: #2b5278; }
        .search-result-item .info { flex: 1; }
        .search-result-item .info .name { font-weight: bold; font-size: 14px; }
        .search-result-item .info .tag { font-size: 11px; color: #8caab9; }
        .search-result-item .avatar-small { width: 30px; height: 30px; border-radius: 50%; background: #2b5278; display: flex; align-items: center; justify-content: center; font-size: 14px; overflow: hidden; flex-shrink: 0; }
        .search-result-item .avatar-small img { width: 100%; height: 100%; object-fit: cover; }
        .botfather-chat { background: #1e2a36; border-radius: 8px; padding: 12px; max-height: 300px; overflow-y: auto; margin: 10px 0; }
        .botfather-chat .msg { padding: 6px 10px; margin: 4px 0; border-radius: 6px; }
        .botfather-chat .bot { background: #2b5278; }
        .botfather-chat .user { background: #242f3d; text-align: left; }
        @media (max-width: 768px) {
            .sidebar { width: 100%; height: 60px; border-left: none; border-bottom: 1px solid #242f3d; flex-direction: row; overflow-x: auto; }
            .sidebar-header { display: flex; align-items: center; gap: 10px; padding: 8px 12px; flex-shrink: 0; }
            .sidebar-header .user-info { margin-bottom: 0; }
            .sidebar-header input { display: none; }
            .sidebar-content { display: flex; gap: 4px; padding: 4px 8px; overflow-x: auto; flex: 1; }
            .sidebar-item { white-space: nowrap; padding: 6px 12px; margin: 0; }
            .sidebar-bottom { display: none; }
            .sidebar-status { display: none; }
            .chat-area { margin-right: 0; margin-top: 60px; height: calc(100vh - 60px); }
            .message { max-width: 90%; }
            .message .msg-content img { max-width: 200px; max-height: 200px; }
        }
        @media (max-width: 480px) {
            .chat-header { padding: 8px 12px; }
            .chat-header .room-info .title { font-size: 14px; }
            .input-area { padding: 6px; }
            .input-area input[type="text"] { font-size: 14px; padding: 8px; }
            .input-area button { padding: 8px 12px; font-size: 12px; }
            .message { max-width: 95%; }
            .popup { padding: 16px; }
        }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: #17212b; }
        ::-webkit-scrollbar-thumb { background: #242f3d; border-radius: 3px; }
    </style>
</head>
<body>

<!-- Auth -->
<div id="auth-page" class="auth-container">
    <div class="auth-box">
        <div class="logo">
            <h1>💬 پیام‌رسان</h1>
            <p id="auth-subtitle">وارد شوید یا حساب جدید بسازید</p>
        </div>
        <div id="auth-error" class="error"></div>
        <div id="auth-success" class="success"></div>
        <form id="auth-form">
            <input type="text" id="username" placeholder="نام کاربری" required autocomplete="username">
            <input type="password" id="password" placeholder="رمز عبور" required autocomplete="current-password">
            <div id="register-fields" class="register-fields">
                <input type="text" id="user_tag" placeholder="@آیدی کاربری (مثل: ali_reza)" required autocomplete="off">
                <div class="note">فقط حروف انگلیسی، اعداد و زیرخط (۳ تا ۳۰ کاراکتر)</div>
                <div class="tag-preview">آیدی شما: <span id="tag-preview">@...</span></div>
                <input type="text" id="display_name" placeholder="نام نمایشی (اختیاری)" autocomplete="off">
                <textarea id="bio" placeholder="بیوگرافی (اختیاری)"></textarea>
                <div class="note">📸 می‌توانید بعداً عکس پروفایل خود را آپلود کنید</div>
            </div>
            <button type="button" id="auth-btn">ورود</button>
        </form>
        <div class="switch" id="switch-auth">حساب ندارید؟ ثبت نام کنید</div>
    </div>
</div>

<!-- App -->
<div id="app-page" class="app">
    <div class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <div class="user-info" onclick="showProfile()">
                <div class="avatar" id="my-avatar">👤</div>
                <div>
                    <div class="name" id="my-name">کاربر</div>
                    <div class="tag" id="my-tag">@username</div>
                </div>
            </div>
            <input type="text" id="search-input" placeholder="جستجو..." oninput="searchGlobal(this.value)">
            <div id="search-results" style="display:none;position:absolute;top:100%;left:0;right:0;background:#17212b;z-index:20;border-radius:8px;padding:8px;"></div>
        </div>
        <div class="sidebar-content" id="sidebar-content"></div>
        <div class="sidebar-bottom">
            <button onclick="showCreateGroup()">📦 گروه</button>
            <button onclick="showCreateChannel()">📢 کانال</button>
            <button onclick="showJoinRoom()">🔗 پیوستن</button>
            <button onclick="showBotFather()">🤖 بات</button>
            <button class="logout-btn" onclick="logout()">🚪 خروج</button>
        </div>
        <div class="sidebar-status">
            <span>🟢 <span id="online-count">0</span></span>
            <span id="sidebar-time"></span>
        </div>
    </div>
    <div class="chat-area">
        <div class="chat-header">
            <div class="room-info">
                <span class="title" id="chat-title">انتخاب کنید</span>
                <span class="tag" id="chat-tag"></span>
            </div>
            <div class="room-actions" id="room-actions" style="display:none;">
                <button onclick="toggleVoiceChat()" class="voice-btn" id="voice-btn">🎙️ صوتی</button>
                <button onclick="showRoomMembers()">👥 اعضا</button>
                <button onclick="showRoomSettings()">⚙️</button>
            </div>
        </div>
        <div class="messages" id="messages">
            <div style="text-align:center; color:#8caab9; padding:40px;">یک گروه یا کانال انتخاب کنید</div>
        </div>
        <div class="input-area">
            <input type="text" id="msg-input" placeholder="پیام..." onkeypress="if(event.key==='Enter') sendMessage()">
            <button class="file-btn" onclick="document.getElementById('file-input').click()">📎</button>
            <input type="file" id="file-input" multiple accept="image/*,video/*,.pdf,.doc,.docx" onchange="sendFiles(this)">
            <button class="voice-record-btn" id="voice-record-btn" onclick="toggleVoiceRecording()" style="display:none;">🎤</button>
            <button onclick="sendMessage()">ارسال</button>
        </div>
    </div>
</div>

<!-- Popup -->
<div class="popup-overlay" id="popup">
    <div class="popup">
        <h3 id="popup-title">عنوان</h3>
        <div id="popup-body"></div>
        <div class="actions">
            <button class="cancel" onclick="closePopup()">انصراف</button>
            <button class="confirm" id="popup-confirm">تایید</button>
        </div>
    </div>
</div>

<script src="https://cdn.socket.io/4.5.0/socket.io.min.js"></script>
<script>
// ============ DOM Elements ============
const authPage = document.getElementById('auth-page');
const appPage = document.getElementById('app-page');
const authBtn = document.getElementById('auth-btn');
const switchAuth = document.getElementById('switch-auth');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const userTagInput = document.getElementById('user_tag');
const displayNameInput = document.getElementById('display_name');
const bioInput = document.getElementById('bio');
const registerFields = document.getElementById('register-fields');
const errorMsg = document.getElementById('auth-error');
const successMsg = document.getElementById('auth-success');
const tagPreview = document.getElementById('tag-preview');

let socket = null;
let currentUser = null;
let currentUserId = null;
let currentRoom = null;
let replyTo = null;
let allRooms = [];
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let voiceEnabled = false;
let isLogin = true;

// ============ Auth ============
userTagInput.addEventListener('input', function() {
    const val = this.value.trim();
    tagPreview.textContent = val ? '@' + val : '@...';
});

switchAuth.addEventListener('click', function() {
    isLogin = !isLogin;
    this.textContent = isLogin ? 'حساب ندارید؟ ثبت نام کنید' : 'حساب دارید؟ وارد شوید';
    authBtn.textContent = isLogin ? 'ورود' : 'ثبت نام';
    document.getElementById('auth-subtitle').textContent = isLogin ? 'وارد شوید یا حساب جدید بسازید' : 'ثبت نام در پیام‌رسان';
    registerFields.classList.toggle('show');
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');
});

document.getElementById('auth-form').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); handleAuth(); }
});

authBtn.addEventListener('click', handleAuth);

function showAuthError(msg) {
    errorMsg.textContent = msg;
    errorMsg.classList.add('show');
    successMsg.classList.remove('show');
}

function showAuthSuccess(msg) {
    successMsg.textContent = msg;
    successMsg.classList.add('show');
    errorMsg.classList.remove('show');
}

function handleAuth() {
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');
    
    const username = usernameInput.value.trim();
    const password = passwordInput.value;
    
    if (!username || !password) {
        showAuthError('لطفا نام کاربری و رمز عبور را وارد کنید');
        return;
    }
    
    const data = { action: isLogin ? 'login' : 'register', username, password };
    
    if (!isLogin) {
        const userTag = userTagInput.value.trim();
        const displayName = displayNameInput.value.trim() || username;
        const bio = bioInput.value.trim();
        
        if (!userTag) { showAuthError('لطفا آیدی کاربری را وارد کنید'); return; }
        if (!/^[a-zA-Z0-9_]+$/.test(userTag) || userTag.length < 3 || userTag.length > 30) {
            showAuthError('آیدی نامعتبر (فقط حروف انگلیسی، اعداد و زیرخط، ۳ تا ۳۰ کاراکتر)');
            return;
        }
        data.user_tag = userTag;
        data.display_name = displayName;
        data.bio = bio;
    }
    
    authBtn.disabled = true;
    authBtn.innerHTML = isLogin ? '⏳ در حال ورود...' : '⏳ در حال ثبت نام...';
    
    fetch('/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => res.json())
    .then(data => {
        authBtn.disabled = false;
        authBtn.textContent = isLogin ? 'ورود' : 'ثبت نام';
        
        if (data.success) {
            showAuthSuccess('✅ ' + (isLogin ? 'ورود موفق' : 'ثبت نام موفق') + '!');
            setTimeout(() => {
                initApp();
            }, 300);
        } else {
            showAuthError(data.message || 'خطا در ارتباط با سرور');
        }
    })
    .catch(err => {
        authBtn.disabled = false;
        authBtn.textContent = isLogin ? 'ورود' : 'ثبت نام';
        showAuthError('خطا در ارتباط با سرور: ' + err.message);
    });
}

// ============ Init App ============
function initApp() {
    fetch('/me')
        .then(res => res.json())
        .then(data => {
            if (data.user) {
                authPage.style.display = 'none';
                appPage.style.display = 'flex';
                currentUser = data.user.username;
                currentUserId = data.user.id;
                document.getElementById('my-name').textContent = data.user.display_name || data.user.username;
                document.getElementById('my-tag').textContent = '@' + data.user.user_tag;
                
                if (data.user.profile_pic_url) {
                    if (data.user.profile_pic_url.startsWith('http') || data.user.profile_pic_url.startsWith('/')) {
                        document.getElementById('my-avatar').innerHTML = `<img src="${data.user.profile_pic_url}">`;
                    } else {
                        document.getElementById('my-avatar').innerHTML = `<span class="emoji-avatar">${data.user.profile_pic_url}</span>`;
                    }
                } else if (data.user.profile_pic) {
                    document.getElementById('my-avatar').innerHTML = `<img src="/uploads/profiles/${data.user.profile_pic}">`;
                } else {
                    const emojis = ['👤', '👨', '👩', '🧑', '👦', '👧'];
                    document.getElementById('my-avatar').innerHTML = `<span class="emoji-avatar">${emojis[Math.floor(Math.random() * emojis.length)]}</span>`;
                }
                
                initSocket();
                loadRooms();
                setInterval(updateTime, 1000);
                if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                    document.getElementById('voice-record-btn').style.display = 'block';
                }
            }
        });
}

// ============ Check if already logged in ============
fetch('/me')
    .then(res => res.json())
    .then(data => {
        if (data.user) {
            initApp();
        }
    });

function updateTime() {
    const now = new Date();
    document.getElementById('sidebar-time').textContent = now.toLocaleTimeString('fa-IR');
}

// ============ Socket ============
function initSocket() {
    socket = io();
    socket.on('message', (data) => displayMessage(data));
    socket.on('online_count', (count) => document.getElementById('online-count').textContent = count);
    socket.on('room_created', (data) => { showToast(`گروه ${data.name} ساخته شد!`); loadRooms(); });
    socket.on('voice_start', (data) => { showToast(`${data.username} گفتگوی صوتی را شروع کرد`); });
    socket.on('voice_stop', (data) => { showToast(`${data.username} گفتگوی صوتی را متوقف کرد`); });
}

// ============ Display Message ============
function displayMessage(data) {
    const container = document.getElementById('messages');
    if (data.room_tag && currentRoom && data.room_tag !== currentRoom.room_tag) return;
    const div = document.createElement('div');
    div.className = 'message';
    if (data.sender_id === currentUserId) div.classList.add('self');
    let content = '';
    if (data.is_voice && data.file_path) {
        content = `<audio controls src="/uploads/${data.file_path}"></audio>`;
    } else if (data.file_path) {
        const ext = data.file_path.split('.').pop().toLowerCase();
        if (['jpg','jpeg','png','gif','webp'].includes(ext)) {
            content = `<img src="/uploads/${data.file_path}" loading="lazy">`;
        } else {
            content = `📎 <a href="/uploads/${data.file_path}" target="_blank">${data.file_name}</a>`;
        }
    } else {
        content = data.content || '';
    }
    const senderName = data.display_name || data.username || 'ناشناس';
    
    let avatarHtml = '';
    if (data.profile_pic_url) {
        if (data.profile_pic_url.startsWith('http') || data.profile_pic_url.startsWith('/')) {
            avatarHtml = `<img src="${data.profile_pic_url}">`;
        } else {
            avatarHtml = `<span class="emoji-avatar">${data.profile_pic_url}</span>`;
        }
    } else if (data.profile_pic) {
        avatarHtml = `<img src="/uploads/profiles/${data.profile_pic}">`;
    } else {
        const emojis = ['👤', '👨', '👩', '🧑', '👦', '👧'];
        avatarHtml = `<span class="emoji-avatar">${emojis[Math.floor(Math.random() * emojis.length)]}</span>`;
    }
    
    div.innerHTML = `
        <div class="msg-sender"><span class="avatar-small">${avatarHtml}</span> ${senderName} ${data.user_tag ? `<span style="font-size:10px;color:#8caab9;">@${data.user_tag}</span>` : ''}</div>
        <div class="msg-content">${content}</div>
        <span class="msg-time">${data.timestamp ? new Date(data.timestamp).toLocaleTimeString('fa-IR') : ''}</span>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ============ Send Message ============
function sendMessage() {
    const input = document.getElementById('msg-input');
    const content = input.value.trim();
    if (!content || !currentRoom) { if (!currentRoom) showToast('ابتدا یک گروه انتخاب کنید'); return; }
    socket.emit('message', { room_tag: currentRoom.room_tag, content, reply_to: replyTo });
    input.value = '';
    replyTo = null;
}

// ============ Voice Recording ============
function toggleVoiceRecording() {
    if (!currentRoom) { showToast('ابتدا یک گروه انتخاب کنید'); return; }
    if (!navigator.mediaDevices) { showToast('مرورگر شما از ضبط صدا پشتیبانی نمی‌کند'); return; }
    if (isRecording) { stopRecording(); } else { startRecording(); }
}

function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = event => { audioChunks.push(event.data); };
        mediaRecorder.onstop = () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/ogg' });
            const reader = new FileReader();
            reader.onload = function(e) {
                socket.emit('voice_message', { room_tag: currentRoom.room_tag, audio_data: e.target.result.split(',')[1] });
            };
            reader.readAsDataURL(audioBlob);
            document.getElementById('voice-record-btn').classList.remove('recording');
            document.getElementById('voice-record-btn').textContent = '🎤';
            isRecording = false;
        };
        mediaRecorder.start();
        document.getElementById('voice-record-btn').classList.add('recording');
        document.getElementById('voice-record-btn').textContent = '⏹️';
        isRecording = true;
        showToast('در حال ضبط... دوباره کلیک کنید تا متوقف شود');
    }).catch(err => { showToast('خطا: ' + err.message); });
}

function stopRecording() {
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        document.getElementById('voice-record-btn').textContent = '🎤';
        isRecording = false;
    }
}

// ============ Voice Chat ============
function toggleVoiceChat() {
    if (!currentRoom) return;
    voiceEnabled = !voiceEnabled;
    socket.emit('voice_chat', { room_tag: currentRoom.room_tag, enabled: voiceEnabled });
    const btn = document.getElementById('voice-btn');
    if (voiceEnabled) { btn.classList.add('active'); btn.textContent = '🔴 صوتی'; showToast('گفتگوی صوتی فعال شد'); }
    else { btn.classList.remove('active'); btn.textContent = '🎙️ صوتی'; showToast('گفتگوی صوتی غیرفعال شد'); }
}

// ============ Files ============
function sendFiles(input) {
    const files = input.files;
    if (!files.length || !currentRoom) { showToast('ابتدا یک گروه انتخاب کنید'); return; }
    for (let file of files) {
        const reader = new FileReader();
        reader.onload = function(e) {
            socket.emit('share_file', { room_tag: currentRoom.room_tag, file_data: e.target.result.split(',')[1], file_name: file.name });
        };
        reader.readAsDataURL(file);
    }
    input.value = '';
}

// ============ Rooms ============
function loadRooms() {
    fetch('/my_rooms').then(res => res.json()).then(data => {
        allRooms = data.rooms;
        renderSidebar();
        if (!currentRoom && allRooms.length > 0) selectRoom(allRooms[0]);
    });
}

function renderSidebar() {
    const container = document.getElementById('sidebar-content');
    container.innerHTML = '';
    allRooms.forEach(room => {
        const div = document.createElement('div');
        div.className = 'sidebar-item' + (currentRoom && currentRoom.room_tag === room.room_tag ? ' active' : '');
        const typeIcon = room.room_type === 'group' ? '👥' : '📢';
        const voiceBadge = room.voice_enabled ? '<span class="voice-badge">🎙️</span>' : '';
        div.innerHTML = `<div><span class="type">${typeIcon}</span> ${room.name} ${voiceBadge}<span style="font-size:10px;color:#8caab9;float:left;">@${room.room_tag}</span></div>`;
        div.onclick = () => selectRoom(room);
        container.appendChild(div);
    });
    if (!allRooms.length) container.innerHTML = '<div style="text-align:center;color:#8caab9;padding:20px;">هیچ گروهی ندارید</div>';
}

function selectRoom(room) {
    if (socket && currentRoom) socket.emit('leave_room', { room_tag: currentRoom.room_tag });
    currentRoom = room;
    document.getElementById('chat-title').textContent = room.name;
    document.getElementById('chat-tag').textContent = `@${room.room_tag}`;
    document.getElementById('room-actions').style.display = 'flex';
    document.getElementById('voice-record-btn').style.display = room.voice_enabled ? 'block' : 'none';
    if (room.voice_enabled) { document.getElementById('voice-btn').style.display = 'inline-block'; }
    else { document.getElementById('voice-btn').style.display = 'none'; }
    fetch(`/room_messages/${room.room_tag}`).then(res => res.json()).then(data => {
        document.getElementById('messages').innerHTML = '';
        data.messages.forEach(msg => displayMessage(msg));
    });
    if (socket) socket.emit('join_room', { room_tag: room.room_tag });
    renderSidebar();
}

// ============ Search ============
function searchGlobal(query) {
    const container = document.getElementById('search-results');
    if (!query.trim() || query.length < 2) { container.style.display = 'none'; return; }
    fetch(`/search_global?q=${encodeURIComponent(query)}`).then(res => res.json()).then(data => {
        container.style.display = 'block';
        container.innerHTML = '';
        if (!data.users.length && !data.rooms.length) {
            container.innerHTML = '<div style="padding:10px;color:#8caab9;">نتیجه‌ای یافت نشد</div>';
            return;
        }
        data.users.forEach(user => {
            const div = document.createElement('div');
            div.className = 'search-result-item';
            let avatarHtml = '';
            if (user.profile_pic_url) {
                if (user.profile_pic_url.startsWith('http') || user.profile_pic_url.startsWith('/')) {
                    avatarHtml = `<img src="${user.profile_pic_url}">`;
                } else {
                    avatarHtml = `<span class="emoji-avatar">${user.profile_pic_url}</span>`;
                }
            } else if (user.profile_pic) {
                avatarHtml = `<img src="/uploads/profiles/${user.profile_pic}">`;
            } else {
                const emojis = ['👤', '👨', '👩', '🧑', '👦', '👧'];
                avatarHtml = `<span class="emoji-avatar">${emojis[Math.floor(Math.random() * emojis.length)]}</span>`;
            }
            div.innerHTML = `<div class="avatar-small">${avatarHtml}</div><div class="info"><div class="name">${user.display_name || user.username}</div><div class="tag">@${user.user_tag}</div></div>`;
            div.onclick = () => { container.style.display = 'none'; document.getElementById('search-input').value = ''; showToast(`کاربر ${user.display_name}`); };
            container.appendChild(div);
        });
        data.rooms.forEach(room => {
            const div = document.createElement('div');
            div.className = 'search-result-item';
            const typeIcon = room.room_type === 'group' ? '👥' : '📢';
            div.innerHTML = `<div style="font-size:24px;">${typeIcon}</div><div class="info"><div class="name">${room.name}</div><div class="tag">@${room.room_tag}</div></div>`;
            div.onclick = () => {
                container.style.display = 'none';
                document.getElementById('search-input').value = '';
                fetch('/join_room', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ room_tag: room.room_tag })
                }).then(res => res.json()).then(data => {
                    if (data.success) { showToast(`به ${data.room_name} پیوستید!`); loadRooms(); }
                    else showToast('خطا: ' + data.message);
                });
            };
            container.appendChild(div);
        });
    });
}

// ============ Create Group / Channel ============
function showCreateGroup() {
    showPopup('گروه جدید', `
        <input type="text" id="room-tag" placeholder="@آیدی گروه (3-30 کاراکتر)" required>
        <div class="note">فقط حروف انگلیسی، اعداد و زیرخط</div>
        <input type="text" id="room-name" placeholder="نام گروه" required>
        <textarea id="room-desc" placeholder="توضیحات"></textarea>
        <label><input type="checkbox" id="room-voice"> 🎙️ فعال کردن گفتگوی صوتی</label>
    `, function() {
        const tag = document.getElementById('room-tag').value.trim();
        const name = document.getElementById('room-name').value.trim();
        if (!tag || !name) return showToast('لطفا آیدی و نام را وارد کنید');
        if (!/^[a-zA-Z0-9_]+$/.test(tag) || tag.length < 3) return showToast('آیدی نامعتبر');
        const voice_enabled = document.getElementById('room-voice').checked;
        fetch('/create_room', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ room_type: 'group', room_tag: tag, name, description: document.getElementById('room-desc').value.trim(), is_private: false, voice_enabled: voice_enabled })
        }).then(res => res.json()).then(data => {
            if (data.success) { closePopup(); showToast(`گروه ${tag} ساخته شد!`); loadRooms(); }
            else showToast('خطا: ' + data.message);
        });
    });
}

function showCreateChannel() {
    showPopup('کانال جدید', `
        <input type="text" id="room-tag" placeholder="@آیدی کانال (3-30 کاراکتر)" required>
        <div class="note">فقط حروف انگلیسی، اعداد و زیرخط</div>
        <input type="text" id="room-name" placeholder="نام کانال" required>
        <textarea id="room-desc" placeholder="توضیحات"></textarea>
        <div class="note">⚠️ فقط سازنده می‌تواند در کانال پیام بفرستد</div>
    `, function() {
        const tag = document.getElementById('room-tag').value.trim();
        const name = document.getElementById('room-name').value.trim();
        if (!tag || !name) return showToast('لطفا آیدی و نام را وارد کنید');
        if (!/^[a-zA-Z0-9_]+$/.test(tag) || tag.length < 3) return showToast('آیدی نامعتبر');
        fetch('/create_room', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ room_type: 'channel', room_tag: tag, name, description: document.getElementById('room-desc').value.trim(), is_private: false, voice_enabled: false })
        }).then(res => res.json()).then(data => {
            if (data.success) { closePopup(); showToast(`کانال ${tag} ساخته شد!`); loadRooms(); }
            else showToast('خطا: ' + data.message);
        });
    });
}

function showJoinRoom() {
    showPopup('پیوستن', `
        <input type="text" id="join-room-tag" placeholder="@آیدی گروه یا کانال" style="direction:ltr;">
        <div class="note">مثال: my_group</div>
    `, function() {
        const tag = document.getElementById('join-room-tag').value.trim().replace('@', '');
        if (!tag) return showToast('لطفا آیدی را وارد کنید');
        fetch('/join_room', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ room_tag: tag })
        }).then(res => res.json()).then(data => {
            if (data.success) { closePopup(); showToast(`به ${data.room_name} پیوستید!`); loadRooms(); }
            else showToast('خطا: ' + data.message);
        });
    });
}

// ============ Room Members ============
function showRoomMembers() {
    if (!currentRoom) return;
    fetch(`/room_members/${currentRoom.room_tag}`).then(res => res.json()).then(data => {
        let html = '<div style="max-height:300px;overflow-y:auto;">';
        data.members.forEach(m => {
            const roleIcon = m.role === 'owner' ? '👑' : m.role === 'admin' ? '🛡️' : '👤';
            html += `<div style="padding:8px;background:#242f3d;margin:4px 0;border-radius:6px;display:flex;justify-content:space-between;">
                <span>${roleIcon} ${m.display_name || m.username}</span>
                <span style="color:#8caab9;font-size:12px;">@${m.user_tag}</span>
            </div>`;
        });
        html += '</div>';
        showPopup('اعضای گروه', html, function() { closePopup(); });
        document.getElementById('popup-confirm').textContent = 'بستن';
    });
}

// ============ Room Settings ============
function showRoomSettings() {
    if (!currentRoom) return;
    fetch(`/room_info/${currentRoom.room_tag}`).then(res => res.json()).then(data => {
        if (!data.room) return;
        const isOwner = data.room.owner_id === currentUserId;
        let html = `<div style="padding:10px;background:#242f3d;border-radius:8px;margin:8px 0;">
            <div><strong>نام:</strong> ${data.room.name}</div>
            <div><strong>آیدی:</strong> @${data.room.room_tag}</div>
            <div><strong>نوع:</strong> ${data.room.room_type === 'group' ? 'گروه' : 'کانال'}</div>
            <div><strong>اعضا:</strong> ${data.room.member_count}</div>
            <div><strong>صوتی:</strong> ${data.room.voice_enabled ? '✅ فعال' : '❌ غیرفعال'}</div>
        </div>`;
        if (isOwner) {
            html += `<div style="margin-top:10px;">
                <button onclick="addAdmin()" style="width:100%;padding:10px;background:#2b5278;border:none;border-radius:8px;color:#fff;cursor:pointer;margin:4px 0;">➕ افزودن ادمین</button>
                <button onclick="removeUser()" style="width:100%;padding:10px;background:#e67e22;border:none;border-radius:8px;color:#fff;cursor:pointer;margin:4px 0;">🚫 حذف کاربر</button>
                <button onclick="deleteRoom()" style="width:100%;padding:10px;background:#e74c3c;border:none;border-radius:8px;color:#fff;cursor:pointer;margin:4px 0;">🗑️ حذف گروه</button>
            </div>`;
        }
        showPopup('تنظیمات گروه', html, function() { closePopup(); });
        document.getElementById('popup-confirm').textContent = 'بستن';
    });
}

function addAdmin() {
    if (!currentRoom) return;
    showPopup('افزودن ادمین', `
        <input type="text" id="admin-tag" placeholder="@آیدی کاربر" style="direction:ltr;">
        <div class="note">فقط ادمین‌ها می‌توانند پیام بفرستند و اعضا را مدیریت کنند</div>
    `, function() {
        const tag = document.getElementById('admin-tag').value.trim().replace('@', '');
        if (!tag) return showToast('لطفا آیدی را وارد کنید');
        fetch('/add_admin', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ room_tag: currentRoom.room_tag, user_tag: tag })
        }).then(res => res.json()).then(data => {
            if (data.success) { closePopup(); showToast('ادمین اضافه شد!'); }
            else showToast('خطا: ' + data.message);
        });
    });
}

function removeUser() {
    if (!currentRoom) return;
    showPopup('حذف کاربر', `
        <input type="text" id="remove-tag" placeholder="@آیدی کاربر" style="direction:ltr;">
        <div class="note">کاربر از گروه حذف خواهد شد</div>
    `, function() {
        const tag = document.getElementById('remove-tag').value.trim().replace('@', '');
        if (!tag) return showToast('لطفا آیدی را وارد کنید');
        fetch('/remove_user', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ room_tag: currentRoom.room_tag, user_tag: tag })
        }).then(res => res.json()).then(data => {
            if (data.success) { closePopup(); showToast('کاربر حذف شد!'); loadRooms(); }
            else showToast('خطا: ' + data.message);
        });
    });
}

function deleteRoom() {
    if (!currentRoom) return;
    if (!confirm(`آیا مطمئن هستید که می‌خواهید "${currentRoom.name}" را حذف کنید؟`)) return;
    fetch('/delete_room', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ room_tag: currentRoom.room_tag })
    }).then(res => res.json()).then(data => {
        if (data.success) { showToast('گروه حذف شد!'); currentRoom = null; loadRooms(); }
        else showToast('خطا: ' + data.message);
    });
}

// ============ BotFather ============
function showBotFather() {
    showPopup('🤖 BotFather', `
        <div class="botfather-chat" id="botfather-chat">
            <div class="msg bot">سلام! من BotFather هستم. با من می‌تونی بات بسازی.</div>
            <div class="msg bot">برای شروع، /start رو بفرست</div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px;">
            <input type="text" id="botfather-input" placeholder="پیام به BotFather..." style="flex:1;" onkeypress="if(event.key==='Enter') sendBotFatherMessage()">
            <button onclick="sendBotFatherMessage()" style="padding:10px 16px;background:#65b9f6;border:none;border-radius:8px;color:#0e1621;cursor:pointer;">ارسال</button>
        </div>
    `, function() { closePopup(); });
    document.getElementById('popup-confirm').textContent = 'بستن';
}

function sendBotFatherMessage() {
    const input = document.getElementById('botfather-input');
    const msg = input.value.trim();
    if (!msg) return;
    const chat = document.getElementById('botfather-chat');
    chat.innerHTML += `<div class="msg user">${msg}</div>`;
    input.value = '';
    chat.scrollTop = chat.scrollHeight;
    setTimeout(() => {
        let response = '';
        if (msg === '/start') {
            response = `سلام! 👋\\nمن BotFather هستم.\\n\\n📋 دستورات:\\n/newbot - ساخت بات جدید\\n/mybots - لیست بات‌های من\\n/token - دریافت توکن بات`;
        } else if (msg === '/newbot') {
            showBotCreation(); return;
        } else if (msg === '/mybots') {
            fetch('/my_bots').then(res => res.json()).then(data => {
                if (data.bots.length) {
                    let list = '🤖 بات‌های شما:\\n';
                    data.bots.forEach((b, i) => { list += `${i+1}. ${b.bot_name}\\n   توکن: ${b.bot_token}\\n`; });
                    chat.innerHTML += `<div class="msg bot">${list}</div>`;
                } else {
                    chat.innerHTML += `<div class="msg bot">شما هنوز بات نساخته‌اید. /newbot رو بفرستید.</div>`;
                }
                chat.scrollTop = chat.scrollHeight;
            });
            return;
        } else if (msg.startsWith('/token')) {
            const parts = msg.split(' ');
            if (parts.length > 1) {
                fetch('/get_bot_token', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ bot_name: parts.slice(1).join(' ') })
                }).then(res => res.json()).then(data => {
                    if (data.success) { chat.innerHTML += `<div class="msg bot">🔑 توکن: <code>${data.token}</code></div>`; }
                    else { chat.innerHTML += `<div class="msg bot">❌ ${data.message}</div>`; }
                    chat.scrollTop = chat.scrollHeight;
                });
                return;
            } else {
                response = 'لطفاً نام بات را مشخص کنید: /token [نام بات]';
            }
        } else {
            response = `❌ دستور "${msg}" نامشخص است.\\nدستورات موجود:\\n/start\\n/newbot\\n/mybots\\n/token [نام بات]`;
        }
        chat.innerHTML += `<div class="msg bot">${response}</div>`;
        chat.scrollTop = chat.scrollHeight;
    }, 500);
}

function showBotCreation() {
    const chat = document.getElementById('botfather-chat');
    chat.innerHTML += `<div class="msg bot">نام بات رو وارد کن (مثلاً: MyBot):</div>`;
    chat.scrollTop = chat.scrollHeight;
    const input = document.getElementById('botfather-input');
    const origOnKey = input.onkeypress;
    input.onkeypress = function(e) {
        if (e.key === 'Enter') {
            const name = input.value.trim();
            if (name) {
                input.value = '';
                chat.innerHTML += `<div class="msg user">${name}</div>`;
                fetch('/create_bot', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ bot_name: name })
                }).then(res => res.json()).then(data => {
                    if (data.success) {
                        chat.innerHTML += `<div class="msg bot">✅ بات "${name}" ساخته شد!</div>`;
                        chat.innerHTML += `<div class="msg bot">🤖 @${data.bot_tag}</div>`;
                        chat.innerHTML += `<div class="msg bot">🔑 توکن: <code>${data.token}</code></div>`;
                        chat.innerHTML += `<div class="msg bot">💡 برای دیدن توکن: /token ${name}</div>`;
                    } else {
                        chat.innerHTML += `<div class="msg bot">❌ ${data.message}</div>`;
                    }
                    chat.scrollTop = chat.scrollHeight;
                    input.onkeypress = origOnKey;
                });
            }
        }
    };
}

// ============ Profile ============
function showProfile() {
    showPopup('تنظیمات پروفایل', `
        <div style="text-align:center;margin:10px 0;">
            <div style="width:80px;height:80px;border-radius:50%;background:#242f3d;margin:0 auto;display:flex;align-items:center;justify-content:center;overflow:hidden;cursor:pointer;" onclick="document.getElementById('profile-pic-input').click()">
                <div id="profile-pic-preview" style="font-size:40px;">📷</div>
            </div>
            <input type="file" id="profile-pic-input" accept="image/*" style="display:none;" onchange="previewProfilePic(this)">
            <div class="note">برای تغییر عکس کلیک کنید</div>
        </div>
        <input type="text" id="edit-display_name" placeholder="نام نمایشی">
        <textarea id="edit-bio" placeholder="بیوگرافی"></textarea>
    `, function() {
        const display_name = document.getElementById('edit-display_name').value.trim();
        const bio = document.getElementById('edit-bio').value.trim();
        const data = {};
        if (display_name) data.display_name = display_name;
        if (bio) data.bio = bio;
        
        const fileInput = document.getElementById('profile-pic-input');
        if (fileInput.files && fileInput.files[0]) {
            const reader = new FileReader();
            reader.onload = function(e) {
                data.profile_pic = e.target.result.split(',')[1];
                saveProfile(data);
            };
            reader.readAsDataURL(fileInput.files[0]);
        } else {
            saveProfile(data);
        }
    });
    
    fetch('/me').then(res => res.json()).then(data => {
        if (data.user) {
            document.getElementById('edit-display_name').value = data.user.display_name || '';
            document.getElementById('edit-bio').value = data.user.bio || '';
            if (data.user.profile_pic) {
                document.getElementById('profile-pic-preview').innerHTML = `<img src="/uploads/profiles/${data.user.profile_pic}" style="width:100%;height:100%;object-fit:cover;">`;
            } else if (data.user.profile_pic_url) {
                if (data.user.profile_pic_url.startsWith('http') || data.user.profile_pic_url.startsWith('/')) {
                    document.getElementById('profile-pic-preview').innerHTML = `<img src="${data.user.profile_pic_url}" style="width:100%;height:100%;object-fit:cover;">`;
                } else {
                    document.getElementById('profile-pic-preview').innerHTML = `<span style="font-size:40px;">${data.user.profile_pic_url}</span>`;
                }
            }
        }
    });
}

function previewProfilePic(input) {
    const file = input.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            document.getElementById('profile-pic-preview').innerHTML = `<img src="${e.target.result}" style="width:100%;height:100%;object-fit:cover;">`;
        };
        reader.readAsDataURL(file);
    }
}

function saveProfile(data) {
    fetch('/update_profile', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    }).then(res => res.json()).then(data => {
        if (data.success) { closePopup(); showToast('پروفایل به‌روز شد!'); location.reload(); }
        else showToast('خطا: ' + data.message);
    });
}

// ============ Popup ============
function showPopup(title, bodyHtml, onConfirm) {
    document.getElementById('popup').style.display = 'flex';
    document.getElementById('popup-title').textContent = title;
    document.getElementById('popup-body').innerHTML = bodyHtml;
    document.getElementById('popup-confirm').onclick = onConfirm;
    document.getElementById('popup-confirm').textContent = 'تایید';
}

function closePopup() { document.getElementById('popup').style.display = 'none'; }

// ============ Toast ============
function showToast(msg) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// ============ Logout ============
function logout() { 
    if (socket) socket.disconnect(); 
    fetch('/logout').then(() => { location.reload(); }); 
}
</script>
</body>
</html>
'''

# ============== Routes ==============
@app.route('/')
def index():
    return render_template_string(MAIN_TEMPLATE)

@app.route('/auth', methods=['POST'])
def auth():
    data = request.get_json()
    action = data.get('action')
    username = data.get('username', '').strip()
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': 'نام کاربری و رمز عبور را وارد کنید'})

    conn = get_db()
    
    if action == 'register':
        user_tag = data.get('user_tag', '').strip()
        display_name = data.get('display_name', username).strip()
        bio = data.get('bio', '').strip()
        
        if not user_tag or not validate_tag(user_tag):
            return jsonify({'success': False, 'message': 'آیدی معتبر نیست (3-30 کاراکتر، فقط حروف انگلیسی، اعداد و زیرخط)'})
        
        if get_user_by_username(username):
            conn.close()
            return jsonify({'success': False, 'message': 'این نام کاربری قبلاً ثبت شده است'})
        
        if get_user_by_tag(user_tag):
            conn.close()
            return jsonify({'success': False, 'message': 'این آیدی قبلاً ثبت شده است'})
        
        hashed = generate_password_hash(password)
        cur = conn.execute('''INSERT INTO users (username, user_tag, password, display_name, bio)
                              VALUES (?, ?, ?, ?, ?)''',
                           (username, user_tag, hashed, display_name, bio))
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        
        session.permanent = True
        session['user_id'] = user_id
        session['username'] = username
        return jsonify({'success': True, 'user_id': user_id, 'username': username})

    elif action == 'login':
        user = get_user_by_username(username)
        conn.close()
        if user and check_password_hash(user['password'], password):
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = username
            return jsonify({'success': True, 'user_id': user['id'], 'username': username})
        return jsonify({'success': False, 'message': 'نام کاربری یا رمز عبور اشتباه است'})

@app.route('/me')
def me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'user': None})
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({'user': None})
    
    profile_pic_url = get_profile_pic_path(user['profile_pic'])
    
    return jsonify({'user': {
        'id': user['id'],
        'username': user['username'],
        'user_tag': user['user_tag'],
        'display_name': user['display_name'],
        'bio': user['bio'],
        'profile_pic': user['profile_pic'],
        'profile_pic_url': profile_pic_url
    }})

@app.route('/update_profile', methods=['POST'])
def update_profile():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    
    data = request.get_json()
    conn = get_db()
    updates = []
    params = []
    
    if 'display_name' in data:
        updates.append('display_name = ?')
        params.append(data['display_name'].strip())
    if 'bio' in data:
        updates.append('bio = ?')
        params.append(data['bio'].strip())
    
    if 'profile_pic' in data:
        file_data = data['profile_pic']
        filename = f"profile_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles', filename)
        
        try:
            old = get_user_by_id(user_id)['profile_pic']
            if old:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], 'profiles', old)
                if os.path.exists(old_path):
                    os.remove(old_path)
            
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(file_data))
            
            updates.append('profile_pic = ?')
            params.append(filename)
        except Exception as e:
            conn.close()
            return jsonify({'success': False, 'message': f'خطا در ذخیره عکس: {str(e)}'})
    
    if not updates:
        conn.close()
        return jsonify({'success': False, 'message': 'هیچ تغییری اعمال نشد'})
    
    params.append(user_id)
    conn.execute(f'UPDATE users SET {", ".join(updates)} WHERE id = ?', params)
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/my_rooms')
def my_rooms():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'rooms': []})
    rooms = get_user_rooms(user_id)
    room_list = []
    for r in rooms:
        room_dict = {
            'room_tag': r['room_tag'],
            'room_type': r['room_type'],
            'name': r['name'],
            'description': r['description'],
            'is_private': r['is_private'],
            'member_count': r['member_count'],
            'role': r['role'],
            'owner_id': r['owner_id'],
            'voice_enabled': r['voice_enabled'] if 'voice_enabled' in r.keys() else False
        }
        room_list.append(room_dict)
    return jsonify({'rooms': room_list})

@app.route('/create_room', methods=['POST'])
def create_room_route():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    data = request.get_json()
    room_tag = data.get('room_tag', '').strip()
    room_type = data.get('room_type')
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    is_private = data.get('is_private', True)
    voice_enabled = data.get('voice_enabled', False)
    
    if not room_tag or not validate_tag(room_tag):
        return jsonify({'success': False, 'message': 'آیدی معتبر نیست'})
    if get_room_by_tag(room_tag):
        return jsonify({'success': False, 'message': 'این آیدی قبلاً ثبت شده است'})
    if not name:
        return jsonify({'success': False, 'message': 'نام را وارد کنید'})
    
    room = create_room(room_tag, room_type, name, user_id, description, is_private, voice_enabled)
    add_member_to_room(room['id'], user_id, 'owner')
    socketio.emit('room_created', {'room_tag': room_tag, 'name': name, 'room_type': room_type})
    return jsonify({'success': True, 'room_tag': room_tag})

@app.route('/join_room', methods=['POST'])
def join_room_route():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    room_tag = request.get_json().get('room_tag', '').strip()
    room = get_room_by_tag(room_tag)
    if not room:
        return jsonify({'success': False, 'message': 'گروه یا کانالی با این آیدی یافت نشد'})
    if is_member_of_room(room['id'], user_id):
        return jsonify({'success': True, 'room_name': room['name']})
    add_member_to_room(room['id'], user_id)
    return jsonify({'success': True, 'room_name': room['name']})

@app.route('/room_members/<room_tag>')
def room_members(room_tag):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'members': []})
    room = get_room_by_tag(room_tag)
    if not room:
        return jsonify({'members': []})
    members = get_room_members(room['id'])
    member_list = []
    for m in members:
        member_list.append({
            'id': m['id'],
            'username': m['username'],
            'user_tag': m['user_tag'],
            'display_name': m['display_name'],
            'role': m['role']
        })
    return jsonify({'members': member_list})

@app.route('/room_info/<room_tag>')
def room_info(room_tag):
    room = get_room_by_tag(room_tag)
    if not room:
        return jsonify({'room': None})
    members = get_room_members(room['id'])
    return jsonify({
        'room': {
            'room_tag': room['room_tag'],
            'name': room['name'],
            'description': room['description'],
            'member_count': len(members),
            'owner_id': room['owner_id'],
            'room_type': room['room_type'],
            'voice_enabled': room['voice_enabled'] if 'voice_enabled' in room.keys() else False
        }
    })

@app.route('/add_admin', methods=['POST'])
def add_admin():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    data = request.get_json()
    room_tag = data.get('room_tag')
    user_tag = data.get('user_tag')
    room = get_room_by_tag(room_tag)
    if not room:
        return jsonify({'success': False, 'message': 'گروه یافت نشد'})
    if room['owner_id'] != user_id:
        return jsonify({'success': False, 'message': 'فقط سازنده گروه می‌تواند ادمین اضافه کند'})
    target_user = get_user_by_tag(user_tag)
    if not target_user:
        return jsonify({'success': False, 'message': 'کاربر یافت نشد'})
    if not is_member_of_room(room['id'], target_user['id']):
        return jsonify({'success': False, 'message': 'این کاربر عضو گروه نیست'})
    conn = get_db()
    conn.execute('UPDATE room_members SET role = ? WHERE room_id = ? AND user_id = ?',
                 ('admin', room['id'], target_user['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/remove_user', methods=['POST'])
def remove_user():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    data = request.get_json()
    room_tag = data.get('room_tag')
    user_tag = data.get('user_tag')
    room = get_room_by_tag(room_tag)
    if not room:
        return jsonify({'success': False, 'message': 'گروه یافت نشد'})
    role = get_user_role(room['id'], user_id)
    if role not in ['owner', 'admin']:
        return jsonify({'success': False, 'message': 'شما اجازه حذف کاربر را ندارید'})
    target_user = get_user_by_tag(user_tag)
    if not target_user:
        return jsonify({'success': False, 'message': 'کاربر یافت نشد'})
    if target_user['id'] == room['owner_id']:
        return jsonify({'success': False, 'message': 'نمی‌توانید سازنده گروه را حذف کنید'})
    if not is_member_of_room(room['id'], target_user['id']):
        return jsonify({'success': False, 'message': 'این کاربر عضو گروه نیست'})
    remove_member_from_room(room['id'], target_user['id'])
    return jsonify({'success': True})

@app.route('/delete_room', methods=['POST'])
def delete_room():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    room_tag = request.get_json().get('room_tag')
    room = get_room_by_tag(room_tag)
    if not room:
        return jsonify({'success': False, 'message': 'گروه یافت نشد'})
    if room['owner_id'] != user_id:
        return jsonify({'success': False, 'message': 'فقط سازنده گروه می‌تواند آن را حذف کند'})
    conn = get_db()
    conn.execute('DELETE FROM messages WHERE room_id = ?', (room['id'],))
    conn.execute('DELETE FROM room_members WHERE room_id = ?', (room['id'],))
    conn.execute('DELETE FROM rooms WHERE id = ?', (room['id'],))
    conn.commit()
    conn.close()
    socketio.emit('room_deleted', {'room_tag': room_tag})
    return jsonify({'success': True})

@app.route('/room_messages/<room_tag>')
def room_messages(room_tag):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'messages': []})
    room = get_room_by_tag(room_tag)
    if not room or not is_member_of_room(room['id'], user_id):
        return jsonify({'messages': []})
    messages = get_room_messages(room['id'])
    msg_list = []
    for m in messages:
        profile_pic_url = get_profile_pic_path(m['profile_pic'])
        
        msg_list.append({
            'id': m['id'],
            'sender_id': m['sender_id'],
            'username': m['username'],
            'user_tag': m['user_tag'],
            'display_name': m['display_name'],
            'profile_pic': m['profile_pic'],
            'profile_pic_url': profile_pic_url,
            'content': m['content'],
            'file_path': m['file_path'],
            'file_name': m['file_name'],
            'is_voice': m['is_voice'],
            'timestamp': m['timestamp'],
            'reply_to': m['reply_to'],
            'reply_content': m['reply_content'] if 'reply_content' in m.keys() else None,
            'room_tag': room_tag
        })
    return jsonify({'messages': msg_list})

@app.route('/search_global')
def search_global():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify({'users': [], 'rooms': []})
    users = search_users_by_tag_or_name(query)
    user_list = []
    for u in users:
        profile_pic_url = get_profile_pic_path(u['profile_pic'])
        user_list.append({
            'id': u['id'],
            'username': u['username'],
            'user_tag': u['user_tag'],
            'display_name': u['display_name'],
            'bio': u['bio'],
            'profile_pic': u['profile_pic'],
            'profile_pic_url': profile_pic_url
        })
    rooms = search_rooms_by_tag_or_name(query)
    room_list = []
    for r in rooms:
        room_list.append({
            'room_tag': r['room_tag'],
            'room_type': r['room_type'],
            'name': r['name'],
            'description': r['description'],
            'member_count': r['member_count'],
            'is_private': r['is_private'],
            'voice_enabled': r['voice_enabled'] if 'voice_enabled' in r.keys() else False
        })
    return jsonify({'users': user_list, 'rooms': room_list})

@app.route('/create_bot', methods=['POST'])
def create_bot():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    bot_name = request.get_json().get('bot_name', '').strip()
    if not bot_name:
        return jsonify({'success': False, 'message': 'نام بات را وارد کنید'})
    result = create_bot(user_id, bot_name, None)
    user = get_user_by_id(result['bot_id'])
    return jsonify({
        'success': True,
        'bot_name': bot_name,
        'bot_tag': user['user_tag'],
        'token': result['token']
    })

@app.route('/my_bots')
def my_bots():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'bots': []})
    conn = get_db()
    bots = conn.execute('SELECT * FROM bots WHERE owner_id = ?', (user_id,)).fetchall()
    conn.close()
    bot_list = []
    for b in bots:
        bot_list.append({
            'bot_name': b['bot_name'],
            'bot_token': b['bot_token'],
            'created_at': b['created_at']
        })
    return jsonify({'bots': bot_list})

@app.route('/get_bot_token', methods=['POST'])
def get_bot_token():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'وارد نشده‌اید'})
    bot_name = request.get_json().get('bot_name', '').strip()
    if not bot_name:
        return jsonify({'success': False, 'message': 'نام بات را وارد کنید'})
    conn = get_db()
    bot = conn.execute('SELECT * FROM bots WHERE owner_id = ? AND bot_name = ?', 
                       (user_id, bot_name)).fetchone()
    conn.close()
    if not bot:
        return jsonify({'success': False, 'message': 'باتی با این نام یافت نشد'})
    return jsonify({'success': True, 'token': bot['bot_token']})

@app.route('/bot/info')
def bot_info():
    return '''
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>راهنمای بات</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0e1621; color: #fff; padding: 20px; direction: rtl; }
            .container { max-width: 800px; margin: 0 auto; }
            .card { background: #17212b; padding: 20px; border-radius: 12px; margin: 10px 0; }
            h1 { color: #65b9f6; }
            code { background: #242f3d; padding: 2px 8px; border-radius: 4px; color: #65b9f6; }
            .step { background: #1e2a36; padding: 15px; border-radius: 8px; margin: 10px 0; border-right: 3px solid #65b9f6; }
            .token-box { background: #242f3d; padding: 15px; border-radius: 8px; font-family: monospace; word-break: break-all; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 راهنمای ساخت بات</h1>
            <div class="card">
                <h2>📋 مراحل ساخت بات</h2>
                <div class="step"><h3>مرحله ۱: ورود به BotFather</h3><p>در برنامه روی دکمه <strong>🤖 بات</strong> کلیک کنید تا با BotFather صحبت کنید.</p></div>
                <div class="step"><h3>مرحله ۲: شروع کار</h3><p>دستور <code>/start</code> را بفرستید تا راهنمایی کامل دریافت کنید.</p></div>
                <div class="step"><h3>مرحله ۳: ساخت بات جدید</h3><p>دستور <code>/newbot</code> را بفرستید و نام بات را وارد کنید.</p></div>
                <div class="step"><h3>مرحله ۴: دریافت توکن</h3><p>بعد از ساخت، توکن بات به شما نمایش داده می‌شود.<br>با دستور <code>/token [نام بات]</code> می‌توانید توکن را دوباره دریافت کنید.</p></div>
            </div>
            <div class="card">
                <h2>🔑 نحوه استفاده از توکن</h2>
                <p>توکن بات را در کد خود قرار دهید تا بتوانید از API استفاده کنید:</p>
                <div class="token-box">https://your-domain.com/bot/TOKEN</div>
                <p style="margin-top:10px;color:#8caab9;">⚠️ توکن خود را با کسی به اشتراک نگذارید!</p>
            </div>
            <div class="card">
                <h2>📚 دستورات موجود</h2>
                <ul style="line-height:2;">
                    <li><code>/start</code> - شروع کار با BotFather</li>
                    <li><code>/newbot</code> - ساخت بات جدید</li>
                    <li><code>/mybots</code> - لیست بات‌های شما</li>
                    <li><code>/token [نام بات]</code> - دریافت توکن بات</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ============== Socket Events ==============
@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if not user_id:
        return False
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    user_sessions[user_id].append(request.sid)
    online_users[request.sid] = user_id
    emit('online_count', len(online_users), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    user_id = online_users.pop(request.sid, None)
    if user_id:
        if user_id in user_sessions:
            if request.sid in user_sessions[user_id]:
                user_sessions[user_id].remove(request.sid)
            if not user_sessions[user_id]:
                del user_sessions[user_id]
        emit('online_count', len(online_users), broadcast=True)

@socketio.on('join_room')
def handle_join_room(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    room_tag = data.get('room_tag')
    room = get_room_by_tag(room_tag)
    if not room or not is_member_of_room(room['id'], user_id):
        return
    join_room(room_tag)

@socketio.on('leave_room')
def handle_leave_room(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    room_tag = data.get('room_tag')
    if room_tag:
        leave_room(room_tag)

@socketio.on('message')
def handle_message(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    
    room_tag = data.get('room_tag')
    content = data.get('content', '').strip()
    reply_to = data.get('reply_to')
    
    if not content:
        return
    
    room = get_room_by_tag(room_tag)
    if not room or not is_member_of_room(room['id'], user_id):
        return
    
    if room['room_type'] == 'channel':
        role = get_user_role(room['id'], user_id)
        if role not in ['owner', 'admin']:
            return
    
    msg = save_message(user_id, room['id'], content, reply_to=reply_to)
    if msg:
        profile_pic_url = get_profile_pic_path(msg['profile_pic'])
        
        msg_dict = {
            'id': msg['id'],
            'sender_id': msg['sender_id'],
            'username': msg['username'],
            'user_tag': msg['user_tag'],
            'display_name': msg['display_name'],
            'profile_pic': msg['profile_pic'],
            'profile_pic_url': profile_pic_url,
            'content': msg['content'],
            'timestamp': msg['timestamp'],
            'reply_to': msg['reply_to'],
            'reply_content': msg['reply_content'] if 'reply_content' in msg.keys() else None,
            'room_tag': room_tag
        }
        emit('message', msg_dict, room=room_tag, broadcast=True)

@socketio.on('voice_message')
def handle_voice_message(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    
    room_tag = data.get('room_tag')
    audio_data = data.get('audio_data')
    
    room = get_room_by_tag(room_tag)
    if not room or not is_member_of_room(room['id'], user_id):
        return
    
    filename = f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000,9999)}.ogg"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        with open(filepath, 'wb') as f:
            f.write(base64.b64decode(audio_data))
    except:
        return
    
    msg = save_message(user_id, room['id'], 'پیام صوتی', filename, 'voice.ogg', is_voice=True)
    if msg:
        profile_pic_url = get_profile_pic_path(msg['profile_pic'])
        
        msg_dict = {
            'id': msg['id'],
            'sender_id': msg['sender_id'],
            'username': msg['username'],
            'user_tag': msg['user_tag'],
            'display_name': msg['display_name'],
            'profile_pic': msg['profile_pic'],
            'profile_pic_url': profile_pic_url,
            'file_path': filename,
            'file_name': 'voice.ogg',
            'is_voice': True,
            'timestamp': msg['timestamp'],
            'room_tag': room_tag
        }
        emit('message', msg_dict, room=room_tag, broadcast=True)

@socketio.on('share_file')
def handle_share_file(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    
    room_tag = data.get('room_tag')
    file_data = data.get('file_data')
    file_name = data.get('file_name', 'file')
    
    room = get_room_by_tag(room_tag)
    if not room or not is_member_of_room(room['id'], user_id):
        return
    
    if room['room_type'] == 'channel':
        role = get_user_role(room['id'], user_id)
        if role not in ['owner', 'admin']:
            return
    
    ext = file_name.split('.')[-1] if '.' in file_name else 'bin'
    new_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{''.join(random.choices(string.ascii_lowercase, k=6))}.{ext}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
    
    try:
        with open(file_path, 'wb') as f:
            f.write(base64.b64decode(file_data))
    except:
        return
    
    msg = save_message(user_id, room['id'], f'فایل: {file_name}', new_filename, file_name)
    if msg:
        profile_pic_url = get_profile_pic_path(msg['profile_pic'])
        
        msg_dict = {
            'id': msg['id'],
            'sender_id': msg['sender_id'],
            'username': msg['username'],
            'user_tag': msg['user_tag'],
            'display_name': msg['display_name'],
            'profile_pic': msg['profile_pic'],
            'profile_pic_url': profile_pic_url,
            'file_path': new_filename,
            'file_name': file_name,
            'timestamp': msg['timestamp'],
            'room_tag': room_tag
        }
        emit('message', msg_dict, room=room_tag, broadcast=True)

@socketio.on('voice_chat')
def handle_voice_chat(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    
    room_tag = data.get('room_tag')
    enabled = data.get('enabled', False)
    
    room = get_room_by_tag(room_tag)
    if not room or room['owner_id'] != user_id:
        return
    
    conn = get_db()
    conn.execute('UPDATE rooms SET voice_enabled = ? WHERE id = ?', (enabled, room['id']))
    conn.commit()
    conn.close()
    
    user = get_user_by_id(user_id)
    if enabled:
        emit('voice_start', {'username': user['display_name'] or user['username']}, room=room_tag)
    else:
        emit('voice_stop', {'username': user['display_name'] or user['username']}, room=room_tag)

# ============== Run ==============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, port=port, host='0.0.0.0')
