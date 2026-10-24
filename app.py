import os
import yt_dlp
import time
import threading
import uuid
import shutil
from flask import Flask, request, jsonify, session, redirect, render_template, url_for, send_file
from functools import wraps
from database import init_db, add_user, check_user

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "anikjony-super-secret-key-2024")
COOKIE_SOURCE = "/etc/secrets/cookies.txt"
COOKIE_FILE = "/tmp/cookies.txt" # রিড-রাইট পাথ
init_db()

# কুকি ফাইলটি /tmp-তে কপি করার ফাংশন
def prepare_cookie_file():
    if os.path.exists(COOKIE_SOURCE):
        try:
            shutil.copy(COOKIE_SOURCE, COOKIE_FILE)
            os.chmod(COOKIE_FILE, 0o600) # রিড-রাইট পারমিশন
            return True
        except Exception as e:
            print(f"Cookie copy error: {e}")
            return False
    elif os.path.exists("cookies.txt"):
        # লোকাল ডেভেলপমেন্টের জন্য
        return True
    return False

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
download_tasks = {}

def cleanup_old_files():
    now = time.time()
    for f in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(fpath) and os.stat(fpath).st_mtime < now - 3600:
            try: os.remove(fpath)
            except: pass
    for tid in list(download_tasks.keys()):
        if now - download_tasks[tid].get('created_at', now) > 3600:
            del download_tasks[tid]

def login_required(f):
    @wraps(f)
    def wrap(*a, **k):
        if 'uid' not in session: return redirect(url_for('login'))
        return f(*a, **k)
    return wrap

@app.route('/')
@login_required
def home():
    return render_template('index.html', user=session.get('name'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        if len(u) < 3 or len(p) < 6:
            return render_template('login.html', error='❌ Username 3+ chars, Password 6+ chars', mode='signup')
        if add_user(u, p):
            return render_template('login.html', error='✅ Account created! Please Sign In.', mode='login')
        return render_template('login.html', error='❌ Username already taken.', mode='signup')
    return render_template('login.html', mode='signup')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        uid = check_user(u, p)
        if uid:
            session['uid'] = uid
            session['name'] = u
            return redirect(url_for('home'))
        return render_template('login.html', error='❌ Invalid Username or Password.', mode='login')
    return render_template('login.html', mode='login')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/fetch', methods=['POST'])
@login_required
def fetch():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    if not url: return jsonify({'error': 'Please provide a valid URL'}), 400

    # কুকি ফাইল প্রস্তুত করুন
    prepare_cookie_file()

    opts = {
        'quiet': True, 'no_warnings': True, 'nocheckcertificate': True, 
        'skip_download': True, 'socket_timeout': 20,
        'extractor_args': {'youtube': {'player_client': ['android_vr', 'mweb', 'web_creator']}},
        'geo_bypass': True
    }
    
    # /tmp/cookies.txt ব্যবহার করুন
    if os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    elif os.path.exists("cookies.txt"):
        opts['cookiefile'] = "cookies.txt"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err_str = str(e)
        if 'Failed to extract' in err_str or 'Sign in' in err_str:
            return jsonify({'error': 'YouTube blocked this server IP. Please try again later or use a different video.'}), 500
        return jsonify({'error': f'Failed: {err_str[:100]}'}), 500

    formats, seen = [], set()
    for f in info.get('formats', []):
        if not f.get('url'): continue
        height = f.get('height') or 0
        if height > 2160: continue
        
        quality_str = f"{height}p" if height else "Audio"
        has_v = f.get('vcodec') not in (None, 'none')
        has_a = f.get('acodec') not in (None, 'none')
        if not has_v and not has_a: continue
        
        key = (quality_str, f.get('ext'), has_a)
        if key in seen: continue
        seen.add(key)
        
        formats.append({
            'quality': quality_str, 'ext': f.get('ext', 'mp4'),
            'size': f.get('filesize') or f.get('filesize_approx') or 0,
            'has_audio': has_a, 'has_video': has_v,
        })

    formats.sort(key=lambda x: (-x['size']))
    return jsonify({
        'title': info.get('title', 'Unknown'), 'thumb': info.get('thumbnail'),
        'duration': info.get('duration') or 0, 'original_url': url, 'formats': formats[:10],
    })

def download_worker(task_id, url, quality, title):
    def progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed')
            eta = d.get('eta')
            
            if total and total > 0:
                percent = (downloaded / total) * 100
                current_max = download_tasks[task_id].get('progress', 0)
                if percent > current_max:
                    download_tasks[task_id]['progress'] = round(percent, 1)
            else:
                download_tasks[task_id]['progress'] = 50
                
            download_tasks[task_id]['status'] = 'downloading'
            download_tasks[task_id]['speed'] = f"{speed/1048576:.1f} MB/s" if speed else "Connecting..."
            download_tasks[task_id]['eta'] = f"{eta}s left" if eta else ""
            
        elif d['status'] == 'finished':
            download_tasks[task_id]['progress'] = 100
            download_tasks[task_id]['status'] = 'merging'
            download_tasks[task_id]['speed'] = "Merging..."
            download_tasks[task_id]['eta'] = "Wait"

    safe_title = "".join([c for c in title if c.isalnum() or c in ' -_']).rstrip()
    filename = f"AnikJony_{task_id}_{safe_title[:30]}.mp4"
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    try:
        if quality == 'Audio':
            fmt = 'bestaudio[ext=m4a]/bestaudio'
            filename = f"AnikJony_{task_id}_{safe_title[:30]}.m4a"
            filepath = os.path.join(DOWNLOAD_DIR, filename)
        else:
            try:
                h = int(quality.replace('p', ''))
                fmt = f'bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best'
            except:
                fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'

        ydl_opts = {
            'format': fmt, 
            'outtmpl': filepath, 
            'quiet': True, 
            'no_warnings': True,
            'merge_output_format': 'mp4', 
            'concurrent_fragment_downloads': 16,
            'progress_hooks': [progress_hook],
            'format_sort': ['ext:mp4:m4a', 'vcodec:h264', 'acodec:aac'],
            'extractor_args': {'youtube': {'player_client': ['android_vr', 'mweb', 'web_creator']}},
            'geo_bypass': True
        }
        
        # /tmp/cookies.txt ব্যবহার করুন
        if os.path.exists(COOKIE_FILE): 
            ydl_opts['cookiefile'] = COOKIE_FILE
        elif os.path.exists("cookies.txt"):
            ydl_opts['cookiefile'] = "cookies.txt"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            actual_filepath = ydl.prepare_filename(info)
            
            if not os.path.exists(actual_filepath):
                base, _ = os.path.splitext(actual_filepath)
                for ext in ['.mp4', '.webm', '.mkv', '.m4a']:
                    if os.path.exists(base + ext):
                        actual_filepath = base + ext
                        break

            if os.path.exists(actual_filepath):
                download_tasks[task_id]['status'] = 'ready'
                download_tasks[task_id]['filepath'] = actual_filepath
                download_tasks[task_id]['filename'] = os.path.basename(actual_filepath)
            else:
                raise Exception("File not found after merge.")
                
    except Exception as e:
        download_tasks[task_id]['status'] = 'error'
        err_msg = str(e).replace('[youtube]', '').replace('ERROR:', '').strip()
        download_tasks[task_id]['error_msg'] = err_msg[:100]

@app.route('/api/start_download', methods=['POST'])
@login_required
def start_download():
    cleanup_old_files()
    data = request.get_json() or {}
    url = data.get('url')
    quality = data.get('quality', 'best')
    title = data.get('title', 'video')
    
    if not url: return jsonify({'error': 'Missing URL'}), 400

    task_id = str(uuid.uuid4())[:6]
    download_tasks[task_id] = {
        'status': 'starting', 'progress': 0, 'speed': '0 MB/s', 'eta': '',
        'user_id': session['uid'], 'created_at': time.time()
    }
    
    threading.Thread(target=download_worker, args=(task_id, url, quality, title)).start()
    return jsonify({'task_id': task_id})

@app.route('/api/progress/<task_id>')
@login_required
def get_progress(task_id):
    task = download_tasks.get(task_id)
    if not task: return jsonify({'error': 'Task not found'}), 404
    if task.get('user_id') != session['uid']: return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(task)

@app.route('/api/get_file/<task_id>')
@login_required
def get_file(task_id):
    task = download_tasks.get(task_id)
    if task and task.get('status') == 'ready':
        if task.get('user_id') != session['uid']: return "Unauthorized access", 403
        return send_file(task['filepath'], as_attachment=True, download_name=task['filename'])
    return "File not ready", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
