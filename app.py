import sqlite3
import random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, leave_room, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mostchat_red_black_secret'
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024)

DB_NAME = 'mostchat.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT UNIQUE,
        username TEXT UNIQUE,
        password TEXT,
        bio TEXT DEFAULT 'В сети Mostchat',
        avatar_color TEXT DEFAULT '#e11d48',
        banner_color TEXT DEFAULT '#1f1215',
        avatar_img TEXT DEFAULT ''
    )''')
    for col, default in [('banner_color', "'#1f1215'"), ('avatar_img', "''")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")
        except sqlite3.OperationalError:
            pass

    c.execute('''CREATE TABLE IF NOT EXISTS friends (
        user_uid TEXT,
        friend_uid TEXT,
        UNIQUE(user_uid, friend_uid)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room TEXT,
        sender_uid TEXT,
        sender_name TEXT,
        sender_color TEXT,
        sender_avatar TEXT DEFAULT '',
        text TEXT,
        media TEXT DEFAULT '',
        media_type TEXT DEFAULT '',
        time TEXT
    )''')
    for col in ['sender_avatar', 'media', 'media_type']:
        try:
            c.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

    c.execute('''CREATE TABLE IF NOT EXISTS servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT,
        owner_uid TEXT,
        color TEXT DEFAULT '#e11d48'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS server_members (
        server_code TEXT,
        user_uid TEXT,
        UNIQUE(server_code, user_uid)
    )''')
    conn.commit()
    conn.close()

init_db()

def generate_uid(prefix="MC"):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    table = "users" if prefix == "MC" else "servers"
    col = "uid" if prefix == "MC" else "code"
    while True:
        code = f"{prefix}-{random.randint(1000, 9999)}"
        c.execute(f"SELECT 1 FROM {table} WHERE {col}=?", (code,))
        if not c.fetchone():
            conn.close()
            return code

def get_user_friends(uid):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT u.uid, u.username, u.bio, u.avatar_color, u.banner_color, u.avatar_img 
                 FROM friends f 
                 JOIN users u ON f.friend_uid = u.uid 
                 WHERE f.user_uid=?''', (uid,))
    rows = c.fetchall()
    conn.close()
    return [{
        'uid': r[0],
        'username': r[1],
        'bio': r[2] or 'В сети Mostchat',
        'color': r[3] or '#e11d48',
        'banner': r[4] or '#1f1215',
        'avatar': r[5] or ''
    } for r in rows]

def get_user_servers(uid):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT s.code, s.name, s.owner_uid, s.color 
                 FROM server_members sm 
                 JOIN servers s ON sm.server_code = s.code 
                 WHERE sm.user_uid=?''', (uid,))
    rows = c.fetchall()
    conn.close()
    return [{'code': r[0], 'name': r[1], 'owner': r[2], 'color': r[3] or '#e11d48'} for r in rows]

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('register')
def handle_register(data):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        emit('auth_error', 'Заполните все поля!')
        return

    uid = generate_uid("MC")
    color = '#e11d48'
    banner = '#1f1215'

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (uid, username, password, avatar_color, banner_color) VALUES (?, ?, ?, ?, ?)",
                  (uid, username, password, color, banner))
        conn.commit()
        join_room(uid)
        user_data = {
            'uid': uid,
            'username': username,
            'bio': 'В сети Mostchat',
            'color': color,
            'banner': banner,
            'avatar': '',
            'friends': [],
            'servers': []
        }
        emit('auth_success', user_data)
    except sqlite3.IntegrityError:
        emit('auth_error', 'Этот никнейм уже занят!')
    finally:
        conn.close()

@socketio.on('login')
def handle_login(data):
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT uid, username, bio, avatar_color, banner_color, avatar_img FROM users WHERE username=? AND password=?", (username, password))
    row = c.fetchone()
    conn.close()

    if row:
        uid = row[0]
        join_room(uid)
        user_data = {
            'uid': uid,
            'username': row[1],
            'bio': row[2] or 'В сети Mostchat',
            'color': row[3] or '#e11d48',
            'banner': row[4] or '#1f1215',
            'avatar': row[5] or '',
            'friends': get_user_friends(uid),
            'servers': get_user_servers(uid)
        }
        emit('auth_success', user_data)
    else:
        emit('auth_error', 'Неверный логин или пароль!')

@socketio.on('register_uid')
def handle_register_uid(data):
    if data and data.get('uid'):
        join_room(data['uid'])

@socketio.on('update_profile')
def handle_update_profile(data):
    uid = data['uid']
    new_name = data['username'].strip()
    new_bio = data['bio'].strip()
    new_color = data['color']
    new_banner = data.get('banner', '#1f1215')
    new_avatar = data.get('avatar', '')

    if not new_name:
        emit('notification', {'type': 'error', 'text': 'Никнейм не может быть пустым!'})
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("""UPDATE users 
                     SET username=?, bio=?, avatar_color=?, banner_color=?, avatar_img=? 
                     WHERE uid=?""",
                  (new_name, new_bio, new_color, new_banner, new_avatar, uid))
        conn.commit()
        emit('profile_updated', {
            'uid': uid,
            'username': new_name,
            'bio': new_bio,
            'color': new_color,
            'banner': new_banner,
            'avatar': new_avatar
        })
        friends = get_user_friends(uid)
        for f in friends:
            emit('friends_updated', get_user_friends(f['uid']), to=f['uid'])
    except sqlite3.IntegrityError:
        emit('notification', {'type': 'error', 'text': 'Этот никнейм уже занят!'})
    finally:
        conn.close()

@socketio.on('add_friend')
def handle_add_friend(data):
    my_uid = data['my_uid']
    target_uid = data['target_uid'].strip().upper()

    if my_uid == target_uid:
        emit('notification', {'type': 'error', 'text': 'Нельзя добавить самого себя!'})
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT uid, username FROM users WHERE uid=?", (target_uid,))
    target = c.fetchone()

    if not target:
        conn.close()
        emit('notification', {'type': 'error', 'text': f'Пользователь {target_uid} не найден!'})
        return

    try:
        c.execute("INSERT OR IGNORE INTO friends (user_uid, friend_uid) VALUES (?, ?)", (my_uid, target_uid))
        c.execute("INSERT OR IGNORE INTO friends (user_uid, friend_uid) VALUES (?, ?)", (target_uid, my_uid))
        conn.commit()
        my_friends = get_user_friends(my_uid)
        target_friends = get_user_friends(target_uid)
        emit('friends_updated', my_friends)
        emit('friends_updated', target_friends, to=target_uid)
        emit('notification', {'type': 'info', 'text': f'{target[1]} добавил вас в друзья!'}, to=target_uid)
        emit('notification', {'type': 'success', 'text': f'{target[1]} ({target_uid}) добавлен в друзья!'})
    finally:
        conn.close()

@socketio.on('create_server')
def handle_create_server(data):
    uid = data['uid']
    name = data['name'].strip()
    color = data.get('color', '#e11d48')
    if not name:
        emit('notification', {'type': 'error', 'text': 'Введите название сервера!'})
        return

    code = generate_uid("SRV")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO servers (code, name, owner_uid, color) VALUES (?, ?, ?, ?)",
                  (code, name, uid, color))
        c.execute("INSERT INTO server_members (server_code, user_uid) VALUES (?, ?)", (code, uid))
        conn.commit()
        emit('servers_updated', get_user_servers(uid))
        emit('notification', {'type': 'success', 'text': f'Сервер "{name}" создан! Код: {code}'})
    finally:
        conn.close()

@socketio.on('join_server')
def handle_join_server(data):
    uid = data['uid']
    code = data['code'].strip().upper()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name FROM servers WHERE code=?", (code,))
    srv = c.fetchone()
    if not srv:
        conn.close()
        emit('notification', {'type': 'error', 'text': f'Сервер с кодом {code} не найден!'})
        return

    try:
        c.execute("INSERT OR IGNORE INTO server_members (server_code, user_uid) VALUES (?, ?)", (code, uid))
        conn.commit()
        emit('servers_updated', get_user_servers(uid))
        emit('notification', {'type': 'success', 'text': f'Вы вступили на сервер "{srv[0]}"!'})
    finally:
        conn.close()

@socketio.on('join_room')
def handle_join(data):
    room = data['room']
    join_room(room)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT sender_uid, sender_name, sender_color, sender_avatar, text, media, media_type, time FROM messages WHERE room=? ORDER BY id ASC LIMIT 100", (room,))
    rows = c.fetchall()
    conn.close()
    history = [{
        'uid': r[0],
        'username': r[1],
        'color': r[2] or '#e11d48',
        'avatar': r[3] or '',
        'text': r[4],
        'media': r[5] or '',
        'media_type': r[6] or '',
        'time': r[7]
    } for r in rows]
    emit('load_history', history, to=request.sid)

@socketio.on('leave_room')
def handle_leave(data):
    leave_room(data['room'])

@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    media = data.get('media', '')
    media_type = data.get('media_type', '')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (room, sender_uid, sender_name, sender_color, sender_avatar, text, media, media_type, time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (room, data['uid'], data['username'], data['color'], data.get('avatar', ''), data['text'], media, media_type, data['time']))
    conn.commit()
    conn.close()

    emit('receive_message', data, to=room)

    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) == 3:
            u1, u2 = parts[1], parts[2]
            recipient_uid = u2 if data['uid'] == u1 else u1
            emit('dm_incoming', data, to=recipient_uid)

# --- СИГНАЛИНГ ДЛЯ ГОЛОСОВЫХ И ВИДЕОЗВОНКОВ ---

@socketio.on('call_user')
def handle_call_user(data):
    target = data.get('to_uid')
    if target:
        emit('incoming_call', data, to=target)

@socketio.on('call_accepted')
def handle_call_accepted(data):
    target = data.get('to_uid')
    if target:
        emit('call_accepted', data, to=target)

@socketio.on('call_rejected')
def handle_call_rejected(data):
    target = data.get('to_uid')
    if target:
        emit('call_rejected', data, to=target)

@socketio.on('webrtc_signal')
def handle_webrtc_signal(data):
    target = data.get('to_uid')
    if target:
        emit('webrtc_signal', data, to=target)

@socketio.on('end_call')
def handle_end_call(data):
    target = data.get('to_uid')
    if target:
        emit('call_ended', data, to=target)

@socketio.on('call_log')
def handle_call_log(data):
    room = data.get('room')
    text = data.get('text')
    time_str = data.get('time')
    if not room or not text:
        return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""INSERT INTO messages 
                 (room, sender_uid, sender_name, sender_color, sender_avatar, text, media, media_type, time) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (room, 'SYSTEM_CALL', 'Звонок', '#10b981', '', text, '', 'call_log', time_str))
    conn.commit()
    conn.close()
    payload = {
        'room': room,
        'uid': 'SYSTEM_CALL',
        'username': 'Звонок',
        'color': '#10b981',
        'avatar': '',
        'text': text,
        'media': '',
        'media_type': 'call_log',
        'time': time_str
    }
    emit('receive_message', payload, to=room)

    if room.startswith('dm_'):
        parts = room.split('_')
        if len(parts) == 3:
            u1, u2 = parts[1], parts[2]
            emit('dm_incoming', payload, to=u1)
            emit('dm_incoming', payload, to=u2)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)