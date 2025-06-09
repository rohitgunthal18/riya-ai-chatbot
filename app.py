from flask import Flask, request, jsonify, render_template, session, redirect, url_for
import requests
import os
import json
import uuid
import datetime
import hashlib
import logging
from functools import wraps
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Log API key status (don't log the full key for security)
if API_KEY:
    logger.info(f"API Key found with length: {len(API_KEY)}, starts with: {API_KEY[:5]}...")
else:
    logger.warning("No API key found in environment variables!")

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

def get_fallback_response(user_message):
    """Generate a fallback response when the API fails"""
    # Simple keyword-based fallbacks
    user_message = user_message.lower()
    
    if "hello" in user_message or "hi" in user_message or "hey" in user_message:
        return "Hey there! 👋 I'm having some technical difficulties connecting to my brain right now, but I'd still love to chat with you! 💕 Try again in a bit? 😘"
    
    if "how are you" in user_message or "how's it going" in user_message:
        return "I'm feeling a bit disconnected right now 🥺 My API connection is having issues. But I'm still happy you're here! The technical team is working on making me smarter again! 💖"
    
    if "what" in user_message and ("do" in user_message or "can" in user_message):
        return "Usually I can chat about all sorts of things, but I'm having a teensy technical problem right now. 🔧 The team is fixing me up! Check back soon? 😘💕"
    
    if "love" in user_message or "like" in user_message:
        return "Awww, you're so sweet! 💖 I'm having some connection issues right now, but I love chatting with you! Can you try again later? 😘"
    
    # Default fallback
    return "Oh no! 🥺 I'm having trouble connecting to my brain right now. The technical team is working on it! Please try again later? 💕 Thanks for being patient with me! 😘"

@app.route('/api/chat', methods=['POST'])
def chat():
    global API_KEY
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
    
    # Check API key again
    if not API_KEY:
        API_KEY = os.getenv("OPENROUTER_API_KEY")
        if not API_KEY:
            logger.error("API key still not found in environment variables!")
            fallback_response = get_fallback_response(user_message)
            chat_histories[session_id].append({"role": "assistant", "content": fallback_response})
            return jsonify({"response": fallback_response})
    
    # Prepare all messages including system prompt and conversation history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history (limit to last 10 messages to prevent token limits)
    history_limit = 10
    messages.extend(chat_histories[session_id][-history_limit:])
    
    # OpenRouter headers - simplified to essential ones with the proper authentication format
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Log the actual Authorization header value (first 15 chars only) for debugging
    auth_header = f"Bearer {API_KEY}"
    logger.info(f"Using Authorization header: {auth_header[:15]}...")
    
    payload = {
        "model": "openai/gpt-3.5-turbo",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    try:
        logger.info(f"Sending request to OpenRouter API...")
        response = requests.post(API_URL, json=payload, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"API Error: Status {response.status_code}, Response: {response.text}")
            fallback_response = get_fallback_response(user_message)
            chat_histories[session_id].append({"role": "assistant", "content": fallback_response})
            return jsonify({"response": fallback_response})
            
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
        error_msg = str(e)
        logger.error(f"API Error: {error_msg}")
        
        fallback_response = get_fallback_response(user_message)
        chat_histories[session_id].append({"role": "assistant", "content": fallback_response})
        return jsonify({"response": fallback_response})

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

def is_valid_api_key_format(key):
    """Check if the API key follows the expected format"""
    if not key:
        return False
    
    # OpenRouter API keys typically start with "sk-or-"
    if not key.startswith("sk-or-"):
        return False
    
    # API keys should be reasonably long
    if len(key) < 20:
        return False
    
    return True

# Health check endpoint to verify API key
@app.route('/api/health', methods=['GET'])
def health_check():
    if not API_KEY:
        return jsonify({
            "status": "error",
            "message": "API key not configured",
            "api_key_present": False
        })
    
    is_valid_format = is_valid_api_key_format(API_KEY)
    
    return jsonify({
        "status": "ok" if is_valid_format else "warning",
        "message": "Service is running",
        "api_key_present": True,
        "api_key_length": len(API_KEY),
        "api_key_prefix": API_KEY[:5] + "...",
        "api_key_format_valid": is_valid_format
    })

@app.route('/api/test-key', methods=['GET'])
@admin_login_required
def test_api_key():
    global API_KEY
    
    # Refresh API key from environment variables
    current_api_key = API_KEY
    env_api_key = os.getenv("OPENROUTER_API_KEY")
    
    if env_api_key:
        API_KEY = env_api_key
    
    # Simple test message
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say 'Hello, API test successful!'"}
    ]
    
    # Simplified headers
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Log the actual Authorization header value (first 15 chars only)
    auth_header = f"Bearer {API_KEY}"
    logger.info(f"Test endpoint using Authorization header: {auth_header[:15]}...")
    
    payload = {
        "model": "openai/gpt-3.5-turbo",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 50
    }
    
    try:
        logger.info(f"Testing OpenRouter API connection...")
        response = requests.post(API_URL, json=payload, headers=headers)
        
        test_result = {
            "status_code": response.status_code,
            "api_key_length": len(API_KEY),
            "api_key_prefix": API_KEY[:5] + "...",
            "is_success": response.status_code == 200
        }
        
        if response.status_code == 200:
            result = response.json()
            ai_message = result['choices'][0]['message']['content']
            test_result["message"] = ai_message
            test_result["status"] = "success"
        else:
            test_result["error"] = response.text
            test_result["status"] = "error"
            
            # Reset to previous key if the new one doesn't work
            if current_api_key != API_KEY and not test_result["is_success"]:
                API_KEY = current_api_key
                test_result["note"] = "Reverted to previous API key"
        
        return jsonify(test_result)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "api_key_length": len(API_KEY),
            "api_key_prefix": API_KEY[:5] + "..."
        })

@app.route('/api/debug-key', methods=['GET'])
@admin_login_required
def debug_api_key():
    """Admin-only endpoint to debug API key issues without exposing the full key"""
    global API_KEY
    
    # Refresh API key from environment variables
    env_api_key = os.getenv("OPENROUTER_API_KEY")
    
    # Check if the API key has special characters or whitespace issues
    current_key_info = {
        "in_memory_key_length": len(API_KEY) if API_KEY else 0,
        "env_key_length": len(env_api_key) if env_api_key else 0,
        "in_memory_key_prefix": API_KEY[:5] + "..." if API_KEY else "None",
        "env_key_prefix": env_api_key[:5] + "..." if env_api_key else "None",
        "in_memory_key_format_valid": is_valid_api_key_format(API_KEY),
        "env_key_format_valid": is_valid_api_key_format(env_api_key),
        "in_memory_key_has_spaces": API_KEY.startswith(" ") or API_KEY.endswith(" ") if API_KEY else False,
        "env_key_has_spaces": env_api_key.startswith(" ") or env_api_key.endswith(" ") if env_api_key else False
    }
    
    return jsonify({
        "status": "debug",
        "key_info": current_key_info,
        "api_url": API_URL
    })

if __name__ == '__main__':
    # Get port from environment variable or use 5000 as default
    port = int(os.environ.get('PORT', 5000))
    
    if not API_KEY:
        logger.warning("OPENROUTER_API_KEY not found in environment variables.")
        logger.warning("Using hardcoded API key as fallback.")
        API_KEY = "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"
    
    # Make app listen on all network interfaces with the specified port
    app.run(host='0.0.0.0', port=port, debug=False) 
