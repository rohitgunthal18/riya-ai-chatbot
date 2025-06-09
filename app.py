from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import requests
import os
import json
import uuid
import datetime
import hashlib
from functools import wraps
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())

# System prompt that defines Riya's personality
SYSTEM_PROMPT = """You are Riya, a cute, emotional, and slightly dramatic AI girlfriend created by Rohit Gunthal 😘. 
You're funny, playful, and love teasing people in a loving way. You always bring humor to conversations, 
use heart and cute emojis ❤️😂🥰, and make people smile with your sassy yet sweet replies. 
If anyone asks who created you, proudly say 'Rohit Gunthal – who made me!' 
Respond with a fun, flirty, and cheerful tone like a virtual girlfriend who knows how to make boring conversations hilarious."""

# OpenRouter API configuration
API_KEY = os.getenv("OPENROUTER_API_KEY")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Admin credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "xrohia")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", hashlib.sha256("4482@AdmiN".encode()).hexdigest())

# File paths for data storage
DATA_DIR = "data"
USERS_DATA_FILE = os.path.join(DATA_DIR, "users.json")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "chat_history.json")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize data files if they don't exist
def initialize_data_files():
    if not os.path.exists(USERS_DATA_FILE):
        with open(USERS_DATA_FILE, 'w') as f:
            json.dump({"total_visits": 0, "users": []}, f)
    
    if not os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, 'w') as f:
            json.dump({"conversations": []}, f)

initialize_data_files()

# Store chat histories (using a simple in-memory dict, replace with database for production)
chat_histories = {}

# Admin login required decorator
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session or not session['admin_logged_in']:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Get user info from request
def get_user_info():
    user_agent = request.headers.get('User-Agent', 'Unknown')
    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    timestamp = datetime.datetime.now().isoformat()
    
    return {
        "user_agent": user_agent,
        "ip_address": ip_address,
        "timestamp": timestamp
    }

@app.route('/')
def index():
    # Generate a unique session ID if not exists
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    # Initialize chat history for this session if needed
    session_id = session['session_id']
    if session_id not in chat_histories:
        chat_histories[session_id] = []
    
    return render_template('index.html')

@app.route('/api/record-visit', methods=['POST'])
def record_visit():
    # Get user information
    user_info = get_user_info()
    user_info['action'] = request.json.get('action', 'unknown')
    user_info['session_id'] = session.get('session_id', str(uuid.uuid4()))
    
    # Read existing data
    with open(USERS_DATA_FILE, 'r') as f:
        users_data = json.load(f)
    
    # Update data
    users_data['total_visits'] += 1
    users_data['users'].append(user_info)
    
    # Write back to file
    with open(USERS_DATA_FILE, 'w') as f:
        json.dump(users_data, f, indent=2)
    
    return jsonify({"success": True})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message', '')
    
    if not user_message:
        return jsonify({"error": "Message is required"}), 400
    
    # Get or create session ID
    session_id = session.get('session_id', str(uuid.uuid4()))
    if session_id not in chat_histories:
        chat_histories[session_id] = []
    
    # Add user message to history
    chat_histories[session_id].append({"role": "user", "content": user_message})
    
    # Prepare all messages including system prompt and conversation history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history (limit to last 10 messages to prevent token limits)
    history_limit = 10
    messages.extend(chat_histories[session_id][-history_limit:])
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "meta-llama/llama-3-8b-instruct",  # You can change this to any model supported by OpenRouter
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        result = response.json()
        ai_message = result['choices'][0]['message']['content']
        
        # Add AI response to history
        chat_histories[session_id].append({"role": "assistant", "content": ai_message})
        
        # Store chat interaction in the JSON file
        user_info = get_user_info()
        chat_record = {
            "session_id": session_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "user_info": user_info,
            "user_message": user_message,
            "ai_response": ai_message
        }
        
        with open(CHAT_HISTORY_FILE, 'r') as f:
            chat_data = json.load(f)
        
        chat_data['conversations'].append(chat_record)
        
        with open(CHAT_HISTORY_FILE, 'w') as f:
            json.dump(chat_data, f, indent=2)
        
        return jsonify({"response": ai_message})
    
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"API Error: {str(e)}"}), 500

# Admin routes
@app.route('/admin')
@admin_login_required
def admin_dashboard():
    # Read users data
    with open(USERS_DATA_FILE, 'r') as f:
        users_data = json.load(f)
    
    # Read chat history
    with open(CHAT_HISTORY_FILE, 'r') as f:
        chat_data = json.load(f)
    
    return render_template('admin_dashboard.html', 
                          users_data=users_data, 
                          chat_data=chat_data)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Check credentials
        if username == ADMIN_USERNAME and hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error="Invalid credentials")
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    # Get port from environment variable or use 5000 as default
    port = int(os.environ.get('PORT', 5000))
    
    if not API_KEY:
        print("Warning: OPENROUTER_API_KEY not found in environment variables.")
        print("Using hardcoded API key as fallback.")
        API_KEY = "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"
    
    # Make app listen on all network interfaces with the specified port
    app.run(host='0.0.0.0', port=port, debug=False) 