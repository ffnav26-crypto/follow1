import os
import json
import logging
import requests
import sys
import time
import random
from threading import Thread
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from instagrapi import Client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

ACCOUNTS_FILE = 'accounts.json'
SOURCES_FILE = 'sources.json'
STATS_FILE = 'stats.json'

def load_json(filename, default):
    if not os.path.exists(filename):
        with open(filename, 'w') as f:
            json.dump(default, f)
        return default
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except:
        return default

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

app = Flask(__name__, template_folder='templates')
app.secret_key = os.urandom(24)

# Initialize Instagram Client
cl = Client()
cl.delay_range = [2, 5]
logs = []
is_paused = False

def add_log(message, level="INFO"):
    log_entry = f"{time.strftime('%H:%M:%S')} [{level}] {message}"
    logger.info(message)
    logs.append(log_entry)
    if len(logs) > 100: logs.pop(0)

def login_account(acc):
    """Attempt to login and update account status."""
    try:
        cl.set_settings({})
        if acc.get('session_id'):
            cl.login_by_sessionid(acc['session_id'])
        else:
            cl.login(acc['username'], acc['password'])
        
        acc['status'] = 'active'
        acc['last_login'] = datetime.utcnow().isoformat()
        add_log(f"LOGIN SUCCESS: {acc['username']}")
        return True
    except Exception as e:
        acc['status'] = 'invalid'
        add_log(f"LOGIN FAILED: {acc['username']} - {str(e)}", "ERROR")
        return False

def fetch_accounts_job():
    if is_paused: return
    sources = load_json(SOURCES_FILE, [])
    accounts = load_json(ACCOUNTS_FILE, [])
    
    updated = False
    for source in sources:
        if not source.get('active', True): continue
        try:
            add_log(f"Fetching from source: {source['url']}")
            response = requests.get(source['url'], timeout=15)
            data = response.json()
            if data.get("success") and data.get("accounts"):
                for acc_data in data["accounts"]:
                    existing = next((a for a in accounts if a['username'] == acc_data['username']), None)
                    if not existing:
                        new_acc = {
                            "username": acc_data['username'],
                            "password": acc_data.get('password'),
                            "session_id": acc_data.get('session_id'),
                            "status": "active",
                            "last_login": None
                        }
                        accounts.append(new_acc)
                        login_account(new_acc)
                    else:
                        existing['password'] = acc_data.get('password')
                        existing['session_id'] = acc_data.get('session_id')
                        login_account(existing)
                    
                    source['fetched_count'] = source.get('fetched_count', 0) + 1
                    updated = True
                
                add_log(f"Successfully fetched and logged in accounts from {source['url']}")
        except Exception as e:
            add_log(f"Error fetching from {source['url']}: {str(e)}", "ERROR")
    
    if updated:
        save_json(ACCOUNTS_FILE, accounts)
        save_json(SOURCES_FILE, sources)

@app.route('/admin/account/add', methods=['POST'])
def add_manual_account():
    if not session.get('admin'): return jsonify({"error": "Unauthorized"}), 403
    
    auth_type = request.form.get('auth_type')
    username = request.form.get('username')
    accounts = load_json(ACCOUNTS_FILE, [])
    
    acc = next((a for a in accounts if a['username'] == username), None)
    if not acc:
        acc = {"username": username, "status": "active", "last_login": None}
        accounts.append(acc)
    
    if auth_type == 'session':
        acc['session_id'] = request.form.get('session_id')
        acc['password'] = None
    else:
        acc['password'] = request.form.get('password')
        acc['session_id'] = None
    
    success = login_account(acc)
    save_json(ACCOUNTS_FILE, accounts)
    
    return jsonify({
        "success": success,
        "message": f"Login {'successful' if success else 'failed'} for {username}"
    })

scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_accounts_job, trigger="interval", minutes=10)
scheduler.start()

def perform_follows(target_username, quantity):
    accounts = load_json(ACCOUNTS_FILE, [])
    active_accounts = [a for a in accounts if a.get('status') == 'active'][:quantity]
    stats = load_json(STATS_FILE, [])

    if not active_accounts:
        add_log("No active accounts available for following", "ERROR")
        return

    for acc in active_accounts:
        if is_paused: break
        try:
            cl.set_settings({})
            if acc.get('session_id'):
                cl.login_by_sessionid(acc['session_id'])
            else:
                cl.login(acc['username'], acc['password'])
            
            user_id = cl.user_id_from_username(target_username)
            cl.user_follow(user_id)
            
            stats.insert(0, {
                "target_username": target_username,
                "timestamp": datetime.utcnow().isoformat(),
                "success": True
            })
            if len(stats) > 100: stats.pop()
            
            add_log(f"SUCCESS: {acc['username']} followed {target_username}")
            save_json(STATS_FILE, stats)
            time.sleep(random.randint(5, 15))
        except Exception as e:
            acc['status'] = 'invalid'
            save_json(ACCOUNTS_FILE, accounts)
            add_log(f"FAILED: {acc['username']} could not follow: {str(e)}", "ERROR")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/follow', methods=['POST'])
def follow():
    target = request.form.get('target_username')
    quantity = int(request.form.get('quantity', 1))
    Thread(target=perform_follows, args=(target, quantity)).start()
    return jsonify({"success": True, "message": f"Started following {target} with {quantity} accounts"})

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == 'Nav@1234':
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'): return redirect(url_for('admin'))
    sources = load_json(SOURCES_FILE, [])
    accounts = load_json(ACCOUNTS_FILE, [])
    stats = load_json(STATS_FILE, [])
    
    active_count = sum(1 for a in accounts if a.get('status') == 'active')
    
    return render_template('admin_dashboard.html', 
                         sources=sources, 
                         acc_count=len(accounts), 
                         active_count=active_count, 
                         stats=stats[:50], 
                         is_paused=is_paused)

@app.route('/admin/source/add', methods=['POST'])
def add_source():
    if not session.get('admin'): return jsonify({"error": "Unauthorized"}), 403
    url = request.form.get('url')
    if url:
        sources = load_json(SOURCES_FILE, [])
        sources.append({"url": url, "active": True, "fetched_count": 0})
        save_json(SOURCES_FILE, sources)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/source/delete/<int:index>')
def delete_source(index):
    if not session.get('admin'): return redirect(url_for('admin'))
    sources = load_json(SOURCES_FILE, [])
    if 0 <= index < len(sources):
        sources.pop(index)
        save_json(SOURCES_FILE, sources)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle_pause')
def toggle_pause():
    global is_paused
    is_paused = not is_paused
    return redirect(url_for('admin_dashboard'))

@app.route('/logs')
def get_logs():
    return jsonify(logs)

if __name__ == "__main__":
    # Ensure default source exists
    sources = load_json(SOURCES_FILE, [])
    if not sources:
        sources.append({"url": "https://session-psi.vercel.app/gen?count=1", "active": True, "fetched_count": 0})
        save_json(SOURCES_FILE, sources)
    
    app.run(host='0.0.0.0', port=5000)
