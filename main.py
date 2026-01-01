from flask import Flask, render_template, request, jsonify
import random
import time
import logging
import requests
from instagrapi import Client
import os
from threading import Thread

app = Flask(__name__)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

cl = Client()
cl.delay_range = [2, 5]

def background_follow(target_username):
    try:
        response = requests.get("https://session-psi.vercel.app/gen?count=1")
        response.raise_for_status()
        data = response.json()

        if not data.get("success") or not data.get("accounts"):
            logger.error("Failed to fetch account from API")
            return

        acc = data["accounts"][0]
        username = acc["username"]
        password = acc["password"]

        logger.info(f"Attempting to login with account: {username}")
        cl.login(username, password)
        logger.info(f"Successfully logged in as {username}")

        user_id = cl.user_id_from_username(target_username)
        cl.user_follow(user_id)
        logger.info(f"Successfully followed {target_username}")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/follow', methods=['POST'])
def follow():
    target_username = request.form.get('target_username')
    if not target_username:
        return jsonify({"success": False, "message": "Username is required"}), 400
    
    # Run in background to avoid timeout
    Thread(target=background_follow, args=(target_username,)).start()
    return jsonify({"success": True, "message": f"Started following task for {target_username}"})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
