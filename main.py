import os
import logging
import requests
import sys
from threading import Thread
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from instagrapi import Client
import time

# Configure logging to stdout so it shows in console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__, template_folder='templates')

# Initialize Instagram Client
cl = Client()
cl.delay_range = [2, 5]

# Global list to store logs for the UI
logs = []

def add_log(message, level="INFO"):
    log_entry = f"{time.strftime('%H:%M:%S')} [{level}] {message}"
    logger.info(message)
    logs.append(log_entry)
    if len(logs) > 100:
        logs.pop(0)

def background_follow(target_username):
    """Background task to fetch account and follow target."""
    try:
        add_log(f"Starting follow task for: {target_username}")
        add_log("Calling API: https://session-psi.vercel.app/gen?count=1")
        
        response = requests.get("https://session-psi.vercel.app/gen?count=1", timeout=15)
        response.raise_for_status()
        data = response.json()

        if not data.get("success") or not data.get("accounts"):
            add_log("FAILED: API returned success=false or no accounts", "ERROR")
            return

        acc = data["accounts"][0]
        username = acc["username"]
        password = acc["password"]
        add_log(f"GOT ACCOUNT: {username}")

        add_log(f"LOGGING IN: {username}...")
        try:
            cl.login(username, password)
            add_log(f"LOGIN SUCCESS: {username}")
        except Exception as e:
            add_log(f"LOGIN ERROR for {username}: {str(e)}", "ERROR")
            return

        add_log(f"RESOLVING USER ID: {target_username}...")
        user_id = cl.user_id_from_username(target_username)
        
        add_log(f"FOLLOWING: {target_username} (ID: {user_id})...")
        cl.user_follow(user_id)
        add_log(f"SUCCESS: {username} followed {target_username}")
        
    except Exception as e:
        add_log(f"CRITICAL ERROR: {str(e)}", "ERROR")

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/logs')
def get_logs():
    return jsonify(logs)

@app.route('/follow', methods=['POST'])
def follow():
    """Handle follow request."""
    target_username = request.form.get('target_username')
    if not target_username:
        return jsonify({"success": False, "message": "Username is required"}), 400
    
    # Start background task
    Thread(target=background_follow, args=(target_username,)).start()
    
    return jsonify({
        "success": True, 
        "message": "Task started. Check the logs below."
    })

if __name__ == "__main__":
    if not os.path.exists('templates'):
        os.makedirs('templates')
    app.run(host='0.0.0.0', port=5000, debug=True)
