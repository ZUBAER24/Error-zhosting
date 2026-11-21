from flask import Flask, request, render_template, redirect, url_for, flash, session, send_file, jsonify, after_this_request
import subprocess
import os
import json
import threading
import time
import hashlib
import shutil
import zipfile
import tempfile
from datetime import datetime
import psutil
import signal
import sys
import re

app = Flask(__name__)
app.secret_key = 'f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8'

# ========== কনফিগারেশন ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

USERS_FILE = os.path.join(BASE_DIR, 'users.json')
ADMIN_CONFIG_FILE = os.path.join(BASE_DIR, 'admin_config.json')
RUNNING_SCRIPTS_FILE = os.path.join(BASE_DIR, 'running_scripts.json')
ACTIVITY_LOG_FILE = os.path.join(BASE_DIR, 'activity.log')

# ========== ডাটাবেস ফাংশন ==========
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def load_admin_config():
    if os.path.exists(ADMIN_CONFIG_FILE):
        with open(ADMIN_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {'password': None, 'created': False}

def save_admin_config(config):
    with open(ADMIN_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def load_running_scripts():
    if os.path.exists(RUNNING_SCRIPTS_FILE):
        with open(RUNNING_SCRIPTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_running_scripts(scripts):
    with open(RUNNING_SCRIPTS_FILE, 'w') as f:
        json.dump(scripts, f, indent=4)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_activity(message):
    with open(ACTIVITY_LOG_FILE, 'a') as f:
        f.write(f"[{datetime.now()}] {message}\n")

# ========== গ্লোবাল ভেরিয়েবল ==========
users = load_users()
admin_config = load_admin_config()
running_scripts = load_running_scripts()

# ========== হেল্পার ফাংশন ==========
def get_user_folder(username):
    folder = os.path.join(BASE_DIR, f'user_{username}')
    os.makedirs(folder, exist_ok=True)
    return folder

def get_user_logs(username):
    return os.path.join(BASE_DIR, f'logs_{username}.txt')

def get_user_scripts(username):
    user_folder = get_user_folder(username)
    scripts = []
    if os.path.exists(user_folder):
        for file in os.listdir(user_folder):
            if file.endswith('.py'):
                file_path = os.path.join(user_folder, file)
                scripts.append({
                    'name': file,
                    'path': file_path,
                    'size': os.path.getsize(file_path),
                    'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
                })
    return scripts

def get_script_status(username, script_name):
    for script_id, info in running_scripts.items():
        if info['username'] == username and info['script_name'] == script_name:
            if is_script_running(script_id):
                return 'running', script_id
            else:
                return 'stopped', script_id
    return 'stopped', None

def is_script_running(script_id):
    if script_id in running_scripts:
        try:
            pid = running_scripts[script_id]['pid']
            process = psutil.Process(pid)
            return process.is_running()
        except:
            if script_id in running_scripts:
                del running_scripts[script_id]
                save_running_scripts(running_scripts)
            return False
    return False

def run_python_script(script_path, username, script_name):
    try:
        script_id = f"{username}_{script_name}_{int(time.time())}"
        log_file = get_user_logs(username)
        
        with open(log_file, 'a') as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"Script started at: {datetime.now()}\n")
            f.write(f"Script: {script_name}\n")
            f.write(f"User: {username}\n")
            f.write(f"Script ID: {script_id}\n")
            f.write(f"{'='*50}\n")
        
        process = subprocess.Popen(
            [sys.executable, script_path],
            cwd=os.path.dirname(script_path),
            stdout=open(log_file, 'a'),
            stderr=open(log_file, 'a'),
            stdin=subprocess.PIPE
        )
        
        running_scripts[script_id] = {
            'pid': process.pid,
            'username': username,
            'script_name': script_name,
            'script_path': script_path,
            'start_time': datetime.now().isoformat(),
            'status': 'running'
        }
        save_running_scripts(running_scripts)
        
        with open(log_file, 'a') as f:
            f.write(f"Process started with PID: {process.pid}\n")
            f.write(f"{'='*50}\n\n")
        
        log_activity(f"Script started: {username}/{script_name} (PID: {process.pid})")
        return script_id
        
    except Exception as e:
        log_activity(f"Error starting script: {e}")
        return None

def stop_script(script_id):
    try:
        if script_id in running_scripts:
            script_info = running_scripts[script_id]
            pid = script_info['pid']
            username = script_info['username']
            script_name = script_info['script_name']
            
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    child.terminate()
                parent.terminate()
                parent.wait(timeout=3)
            except:
                try:
                    os.kill(pid, signal.SIGTERM)
                except:
                    pass
            
            log_file = get_user_logs(username)
            with open(log_file, 'a') as f:
                f.write(f"\nScript stopped at: {datetime.now()}\n")
                f.write(f"{'='*50}\n\n")
            
            del running_scripts[script_id]
            save_running_scripts(running_scripts)
            log_activity(f"Script stopped: {username}/{script_name}")
            return True
    except Exception as e:
        log_activity(f"Error stopping script: {e}")
    return False

def delete_script_file(username, script_name):
    user_folder = get_user_folder(username)
    script_path = os.path.join(user_folder, script_name)
    
    for script_id, info in list(running_scripts.items()):
        if info['username'] == username and info['script_name'] == script_name:
            stop_script(script_id)
            break
    
    if os.path.exists(script_path):
        os.remove(script_path)
        log_activity(f"Script deleted: {username}/{script_name}")
        return True
    return False

def get_script_log(username, script_name):
    log_file = get_user_logs(username)
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            return f.read()
    return "No logs available"

def clear_user_logs(username):
    log_file = get_user_logs(username)
    if os.path.exists(log_file):
        with open(log_file, 'w') as f:
            f.write(f"Logs cleared at: {datetime.now()}\n")
        log_activity(f"Logs cleared for: {username}")
        return True
    return False

def get_all_scripts():
    all_scripts = []
    for username in users:
        user_scripts = get_user_scripts(username)
        for script in user_scripts:
            status, script_id = get_script_status(username, script['name'])
            all_scripts.append({
                'username': username,
                'name': script['name'],
                'status': status,
                'script_id': script_id,
                'size': script['size'],
                'modified': script['modified']
            })
    return all_scripts

def get_system_stats():
    total_users = len(users)
    total_scripts = len(get_all_scripts())
    running = len([s for s in running_scripts.values() if is_script_running(list(running_scripts.keys())[list(running_scripts.values()).index(s)])])
    stopped = total_scripts - running
    
    total_size = 0
    for username in users:
        user_folder = get_user_folder(username)
        if os.path.exists(user_folder):
            for root, dirs, files in os.walk(user_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    total_size += os.path.getsize(file_path)
    
    return {
        'total_users': total_users,
        'total_scripts': total_scripts,
        'running': running,
        'stopped': stopped,
        'total_size': round(total_size / (1024 * 1024), 2)
    }

# ========== অ্যাডমিন চেক ডেকোরেটর ==========
def admin_required(f):
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('অনুগ্রহ করে অ্যাডমিন হিসেবে লগইন করুন!', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# ========== ইউজার রুটস ==========
@app.route('/')
def index():
    return render_template('index.html', admin_created=admin_config.get('created', False))

@app.route('/login_user', methods=['POST'])
def login_user():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        flash('ইউজারনেম এবং পাসওয়ার্ড প্রয়োজন!', 'danger')
        return redirect(url_for('index'))
    
    if username not in users:
        flash('ইউজার পাওয়া যায়নি!', 'danger')
        return redirect(url_for('index'))
    
    if users[username]['password'] == hash_password(password):
        session['username'] = username
        flash(f'স্বাগতম {username}!', 'success')
        log_activity(f"User logged in: {username}")
        return redirect(url_for('user_dashboard', username=username))
    
    flash('ভুল পাসওয়ার্ড!', 'danger')
    return redirect(url_for('index'))

# ========== নতুন: ইউজার রেজিস্ট্রেশন ==========
@app.route('/register_user', methods=['POST'])
def register_user():
    global users
    
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    if not username or not password:
        flash('ইউজারনেম এবং পাসওয়ার্ড প্রয়োজন!', 'danger')
        return redirect(url_for('index'))
    
    if len(username) < 3:
        flash('ইউজারনেম কমপক্ষে ৩ অক্ষরের হতে হবে!', 'danger')
        return redirect(url_for('index'))
    
    if len(password) < 4:
        flash('পাসওয়ার্ড কমপক্ষে ৪ অক্ষরের হতে হবে!', 'danger')
        return redirect(url_for('index'))
    
    if username in users:
        flash('এই ইউজারনেম ইতিমধ্যে নেওয়া হয়েছে!', 'danger')
        return redirect(url_for('index'))
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        flash('ইউজারনেমে শুধু ইংরেজি অক্ষর, সংখ্যা ও _ ব্যবহার করুন!', 'danger')
        return redirect(url_for('index'))
    
    users[username] = {
        'password': hash_password(password),
        'created': datetime.now().isoformat(),
        'scripts': []
    }
    save_users(users)
    get_user_folder(username)
    
    log_activity(f"User registered: {username}")
    flash(f'রেজিস্ট্রেশন সফল! "{username}" এখন লগইন করুন।', 'success')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    username = session.get('username')
    session.clear()
    if username:
        log_activity(f"User logged out: {username}")
    flash('লগআউট সম্পন্ন!', 'info')
    return redirect(url_for('index'))

# ========== ইউজার ড্যাশবোর্ড ==========
@app.route('/user/<username>')
def user_dashboard(username):
    if 'username' not in session or session['username'] != username:
        flash('অনুগ্রহ করে লগইন করুন!', 'danger')
        return redirect(url_for('index'))
    
    scripts = get_user_scripts(username)
    for script in scripts:
        status, script_id = get_script_status(username, script['name'])
        script['status'] = status
        script['script_id'] = script_id
    
    return render_template('user_dashboard.html', 
                         username=username,
                         scripts=scripts)

# ========== স্ক্রিপ্ট ম্যানেজমেন্ট ==========
@app.route('/upload_script', methods=['POST'])
def upload_script():
    if 'username' not in session:
        flash('অনুগ্রহ করে লগইন করুন!', 'danger')
        return redirect(url_for('index'))

    username = session['username']

    script_file = request.files.get('script')
    req_file = request.files.get('requirements')

    if not script_file or not script_file.filename:
        flash('কোনো স্ক্রিপ্ট ফাইল নির্বাচন করা হয়নি!', 'danger')
        return redirect(url_for('user_dashboard', username=username))

    if not script_file.filename.endswith('.py'):
        flash('শুধুমাত্র Python (.py) স্ক্রিপ্ট সাপোর্ট করে!', 'danger')
        return redirect(url_for('user_dashboard', username=username))

    script_file.seek(0, 2)
    script_size = script_file.tell()
    script_file.seek(0)
    if script_size > 10 * 1024 * 1024:
        flash('স্ক্রিপ্ট ফাইল সাইজ 10MB এর বেশি!', 'danger')
        return redirect(url_for('user_dashboard', username=username))

    user_folder = get_user_folder(username)
    script_path = os.path.join(user_folder, script_file.filename)
    script_file.save(script_path)

    flash(f'স্ক্রিপ্ট "{script_file.filename}" আপলোড সম্পন্ন!', 'success')
    log_activity(f"Script uploaded: {username}/{script_file.filename}")

    if req_file and req_file.filename:
        if req_file.filename != 'requirements.txt':
            flash('রিকোয়ারমেন্ট ফাইলের নাম অবশ্যই requirements.txt হতে হবে!', 'warning')
            return redirect(url_for('user_dashboard', username=username))

        req_file.seek(0, 2)
        req_size = req_file.tell()
        req_file.seek(0)
        if req_size > 10 * 1024 * 1024:
            flash('requirements.txt ফাইল সাইজ 10MB এর বেশি!', 'danger')
            return redirect(url_for('user_dashboard', username=username))

        req_path = os.path.join(user_folder, 'requirements.txt')
        req_file.save(req_path)
        log_activity(f"Requirements uploaded: {username}/requirements.txt")

        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-r', req_path],
                capture_output=True,
                text=True,
                timeout=180
            )
            if result.returncode == 0:
                flash('requirements.txt ইনস্টল সম্পন্ন!', 'success')
                log_activity(f"Requirements installed: {username}")
            else:
                err = (result.stderr or result.stdout or 'Unknown error').strip()
                flash(f'pip install ব্যর্থ: {err[:200]}', 'danger')
                log_activity(f"Requirements install failed: {username} - {err[:200]}")
        except subprocess.TimeoutExpired:
            flash('pip install সময়সীমা (180s) ছাড়িয়ে গেছে!', 'danger')
            log_activity(f"Requirements install timeout: {username}")
        except Exception as e:
            flash(f'pip install এরর: {str(e)[:200]}', 'danger')
            log_activity(f"Requirements install exception: {username} - {e}")

    return redirect(url_for('user_dashboard', username=username))

@app.route('/run_script/<username>/<script_name>')
def run_script_route(username, script_name):
    if 'username' not in session or session['username'] != username:
        flash('অননুমোদিত অ্যাক্সেস!', 'danger')
        return redirect(url_for('index'))
    
    user_folder = get_user_folder(username)
    script_path = os.path.join(user_folder, script_name)
    
    if not os.path.exists(script_path):
        flash('স্ক্রিপ্ট পাওয়া যায়নি!', 'danger')
        return redirect(url_for('user_dashboard', username=username))
    
    for script_id, info in running_scripts.items():
        if info['username'] == username and info['script_name'] == script_name:
            if is_script_running(script_id):
                flash('স্ক্রিপ্ট ইতিমধ্যে চলছে!', 'warning')
                return redirect(url_for('user_dashboard', username=username))
    
    script_id = run_python_script(script_path, username, script_name)
    if script_id:
        flash(f'স্ক্রিপ্ট "{script_name}" শুরু হয়েছে!', 'success')
    else:
        flash('স্ক্রিপ্ট শুরু করতে ব্যর্থ!', 'danger')
    
    return redirect(url_for('user_dashboard', username=username))

@app.route('/stop_script/<username>/<script_name>')
def stop_script_route(username, script_name):
    if 'username' not in session or session['username'] != username:
        flash('অননুমোদিত অ্যাক্সেস!', 'danger')
        return redirect(url_for('index'))
    
    stopped = False
    for script_id, info in list(running_scripts.items()):
        if info['username'] == username and info['script_name'] == script_name:
            if stop_script(script_id):
                stopped = True
                break
    
    if stopped:
        flash(f'স্ক্রিপ্ট "{script_name}" বন্ধ হয়েছে!', 'success')
    else:
        flash('স্ক্রিপ্ট বন্ধ করতে ব্যর্থ বা স্ক্রিপ্ট চলছে না!', 'danger')
    
    return redirect(url_for('user_dashboard', username=username))

@app.route('/restart_script/<username>/<script_name>')
def restart_script_route(username, script_name):
    if 'username' not in session or session['username'] != username:
        flash('অননুমোদিত অ্যাক্সেস!', 'danger')
        return redirect(url_for('index'))
    
    for script_id, info in list(running_scripts.items()):
        if info['username'] == username and info['script_name'] == script_name:
            stop_script(script_id)
            break
    
    user_folder = get_user_folder(username)
    script_path = os.path.join(user_folder, script_name)
    
    if os.path.exists(script_path):
        script_id = run_python_script(script_path, username, script_name)
        if script_id:
            flash(f'স্ক্রিপ্ট "{script_name}" রিস্টার্ট হয়েছে!', 'success')
        else:
            flash('স্ক্রিপ্ট রিস্টার্ট করতে ব্যর্থ!', 'danger')
    else:
        flash('স্ক্রিপ্ট পাওয়া যায়নি!', 'danger')
    
    return redirect(url_for('user_dashboard', username=username))

@app.route('/delete_script/<username>/<script_name>')
def delete_script_route(username, script_name):
    if 'username' not in session or session['username'] != username:
        flash('অননুমোদিত অ্যাক্সেস!', 'danger')
        return redirect(url_for('index'))
    
    if delete_script_file(username, script_name):
        flash(f'স্ক্রিপ্ট "{script_name}" ডিলিট হয়েছে!', 'success')
    else:
        flash('স্ক্রিপ্ট ডিলিট করতে ব্যর্থ!', 'danger')
    
    return redirect(url_for('user_dashboard', username=username))

@app.route('/view_logs/<username>/<script_name>')
def view_logs(username, script_name):
    if 'username' not in session or session['username'] != username:
        flash('অননুমোদিত অ্যাক্সেস!', 'danger')
        return redirect(url_for('index'))
    
    logs = get_script_log(username, script_name)
    return render_template('logs.html', 
                         username=username,
                         script_name=script_name,
                         logs=logs)

@app.route('/clear_logs/<username>')
def clear_logs(username):
    if 'username' not in session or session['username'] != username:
        flash('অননুমোদিত অ্যাক্সেস!', 'danger')
        return redirect(url_for('index'))
    
    if clear_user_logs(username):
        flash('লগ ক্লিয়ার করা হয়েছে!', 'success')
    else:
        flash('লগ ক্লিয়ার করতে ব্যর্থ!', 'danger')
    
    return redirect(url_for('user_dashboard', username=username))

@app.route('/get_script_status/<username>/<script_name>')
def get_script_status_route(username, script_name):
    if 'username' not in session:
        return jsonify({'status': 'unauthorized'})
    
    status, script_id = get_script_status(username, script_name)
    return jsonify({
        'status': status,
        'script_id': script_id,
        'running': status == 'running'
    })

# ========== অ্যাডমিন রুটস (/ethbd) ==========
@app.route('/ethbd')
def admin_panel():
    if not admin_config.get('created', False):
        return redirect(url_for('setup_admin'))
    
    if not session.get('admin_logged_in'):
        flash('অনুগ্রহ করে অ্যাডমিন হিসেবে লগইন করুন!', 'danger')
        return redirect(url_for('admin_login'))
    
    stats = get_system_stats()
    running_scripts_list = []
    for script_id, info in running_scripts.items():
        if is_script_running(script_id):
            running_scripts_list.append({
                'script_id': script_id,
                'username': info['username'],
                'script_name': info['script_name'],
                'pid': info['pid'],
                'start_time': info['start_time']
            })
    
    return render_template('admin.html',
                         users=users,
                         running_scripts=running_scripts_list,
                         all_scripts=get_all_scripts(),
                         stats=stats,
                         admin_config=admin_config)

@app.route('/admin_backup_user/<username>')
@admin_required
def admin_backup_user(username):
    if not re.match(r'^[a-zA-Z0-9_]+$', username) or username not in users:
        flash('ইউজার পাওয়া যায়নি!', 'danger')
        return redirect(url_for('admin_panel'))

    user_folder = os.path.join(BASE_DIR, f'user_{username}')
    log_file = get_user_logs(username)

    if not os.path.exists(user_folder) and not os.path.exists(log_file):
        flash(f'"{username}" ইউজারের ব্যাকআপ করার মতো কোনো ফাইল নেই!', 'warning')
        return redirect(url_for('admin_panel'))

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tmp_dir = tempfile.mkdtemp()
    zip_filename = f"backup_{username}_{timestamp}.zip"
    zip_path = os.path.join(tmp_dir, zip_filename)

    try:
        file_count = 0
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(user_folder):
                for root, dirs, files in os.walk(user_folder):
                    for file in files:
                        abs_file_path = os.path.join(root, file)
                        rel_path = os.path.join(f'user_{username}', os.path.relpath(abs_file_path, user_folder))
                        zf.write(abs_file_path, rel_path)
                        file_count += 1

            if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
                zf.write(log_file, f'logs_{username}.txt')
                file_count += 1

        if file_count == 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            flash(f'"{username}" ইউজারের ফোল্ডার খালি, ব্যাকআপ ফাইল তৈরি হয়নি।', 'warning')
            return redirect(url_for('admin_panel'))

        @after_this_request
        def cleanup(response):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return response

        log_activity(f"Admin downloaded backup for user: {username} ({file_count} files)")
        return send_file(zip_path, as_attachment=True, download_name=zip_filename)

    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log_activity(f"Backup failed for {username}: {e}")
        flash(f'ব্যাকআপ তৈরি করতে সমস্যা হয়েছে: {str(e)[:120]}', 'danger')
        return redirect(url_for('admin_panel'))

@app.route('/setup_admin', methods=['GET', 'POST'])
def setup_admin():
    if admin_config.get('created', False):
        flash('অ্যাডমিন ইতিমধ্যে তৈরি করা হয়েছে!', 'warning')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm = request.form.get('confirm')
        
        if not password or password != confirm:
            flash('পাসওয়ার্ড মেলেনি!', 'danger')
            return render_template('setup_admin.html')
        
        if len(password) < 6:
            flash('পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে!', 'danger')
            return render_template('setup_admin.html')
        
        admin_config['password'] = hash_password(password)
        admin_config['created'] = True
        admin_config['created_at'] = datetime.now().isoformat()
        save_admin_config(admin_config)
        
        log_activity("Admin created")
        flash('অ্যাডমিন তৈরি সম্পন্ন! এখন লগইন করুন।', 'success')
        return redirect(url_for('admin_login'))
    
    return render_template('setup_admin.html')

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if not admin_config.get('created', False):
        return redirect(url_for('setup_admin'))
    
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        if hash_password(password) == admin_config['password']:
            session['admin_logged_in'] = True
            log_activity("Admin logged in")
            flash('স্বাগতম অ্যাডমিন!', 'success')
            return redirect(url_for('admin_panel'))
        else:
            flash('ভুল পাসওয়ার্ড!', 'danger')
    
    return render_template('admin_login.html')

@app.route('/admin_logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    log_activity("Admin logged out")
    flash('অ্যাডমিন লগআউট সম্পন্ন!', 'info')
    return redirect(url_for('index'))

@app.route('/change_admin_password', methods=['POST'])
@admin_required
def change_admin_password():
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if hash_password(old_password) != admin_config['password']:
        flash('পুরনো পাসওয়ার্ড ভুল!', 'danger')
        return redirect(url_for('admin_panel'))
    
    if new_password != confirm_password:
        flash('নতুন পাসওয়ার্ড মেলেনি!', 'danger')
        return redirect(url_for('admin_panel'))
    
    if len(new_password) < 6:
        flash('পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে!', 'danger')
        return redirect(url_for('admin_panel'))
    
    admin_config['password'] = hash_password(new_password)
    admin_config['changed_at'] = datetime.now().isoformat()
    save_admin_config(admin_config)
    
    log_activity("Admin password changed")
    flash('অ্যাডমিন পাসওয়ার্ড পরিবর্তন করা হয়েছে!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_create_user', methods=['POST'])
@admin_required
def admin_create_user():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        flash('ইউজারনেম এবং পাসওয়ার্ড প্রয়োজন!', 'danger')
        return redirect(url_for('admin_panel'))
    
    if username in users:
        flash('এই ইউজারনেম ইতিমধ্যে আছে!', 'danger')
        return redirect(url_for('admin_panel'))
    
    if len(username) < 3:
        flash('ইউজারনেম কমপক্ষে ৩ অক্ষরের হতে হবে!', 'danger')
        return redirect(url_for('admin_panel'))
    
    if len(password) < 4:
        flash('পাসওয়ার্ড কমপক্ষে ৪ অক্ষরের হতে হবে!', 'danger')
        return redirect(url_for('admin_panel'))
    
    users[username] = {
        'password': hash_password(password),
        'created': datetime.now().isoformat(),
        'scripts': []
    }
    save_users(users)
    get_user_folder(username)
    
    log_activity(f"Admin created user: {username}")
    flash(f'ইউজার "{username}" তৈরি করা হয়েছে!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_delete_user/<username>')
@admin_required
def admin_delete_user(username):
    if username in users:
        user_folder = get_user_folder(username)
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
        
        log_file = get_user_logs(username)
        if os.path.exists(log_file):
            os.remove(log_file)
        
        for script_id, info in list(running_scripts.items()):
            if info['username'] == username:
                stop_script(script_id)
        
        del users[username]
        save_users(users)
        log_activity(f"Admin deleted user: {username}")
        flash(f'ইউজার "{username}" ডিলিট করা হয়েছে!', 'success')
    else:
        flash('ইউজার পাওয়া যায়নি!', 'danger')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin_stop_all_scripts')
@admin_required
def admin_stop_all_scripts():
    stopped = 0
    for script_id in list(running_scripts.keys()):
        if stop_script(script_id):
            stopped += 1
    
    log_activity(f"Admin stopped all scripts: {stopped}")
    flash(f'{stopped} টি স্ক্রিপ্ট বন্ধ করা হয়েছে!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_clear_all_logs')
@admin_required
def admin_clear_all_logs():
    for username in users:
        clear_user_logs(username)
    
    log_activity("Admin cleared all logs")
    flash('সব লগ ক্লিয়ার করা হয়েছে!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_restart_all_scripts')
@admin_required
def admin_restart_all_scripts():
    restarted = 0
    for username in users:
        scripts = get_user_scripts(username)
        for script in scripts:
            for script_id, info in list(running_scripts.items()):
                if info['username'] == username and info['script_name'] == script['name']:
                    stop_script(script_id)
                    break
            
            script_path = os.path.join(get_user_folder(username), script['name'])
            if os.path.exists(script_path):
                if run_python_script(script_path, username, script['name']):
                    restarted += 1
    
    log_activity(f"Admin restarted all scripts: {restarted}")
    flash(f'{restarted} টি স্ক্রিপ্ট রিস্টার্ট করা হয়েছে!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_get_stats')
@admin_required
def admin_get_stats():
    stats = get_system_stats()
    return jsonify(stats)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


# ========== রান ==========
if __name__ == '__main__':
    print("="*60)
    print("EXU HOSTING PLATFORM - FULL UPGRADED")
    print("="*60)
    print(f"Base Directory: {BASE_DIR}")
    print(f"Total Users: {len(users)}")
    print(f"Running Scripts: {len(running_scripts)}")
    print(f"Admin Created: {admin_config.get('created', False)}")
    print("="*60)
    print("Server running at: http://localhost:5000")
    print("Admin Panel URL: http://localhost:5000/ethbd")
    print("="*60)
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
