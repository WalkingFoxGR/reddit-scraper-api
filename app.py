from flask import Flask, request, jsonify
import os
import praw
from openai import OpenAI
import pandas as pd
import uuid
from datetime import datetime
from functools import wraps
import json
from pathlib import Path

app = Flask(__name__)

# Initialize services
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT", "RedditScraper/1.0")
)

# Initialize OpenAI client properly
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Excel file for database
EXCEL_FILE = "reddit_bot_data.xlsx"

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.getenv("API_KEY"):
            return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated_function

def init_excel_db():
    """Initialize Excel database with required sheets"""
    if not Path(EXCEL_FILE).exists():
        print(f"Creating new Excel database: {EXCEL_FILE}")
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl') as writer:
            # Users sheet
            users_df = pd.DataFrame(columns=['telegram_id', 'username', 'first_name', 'created_at'])
            users_df.to_excel(writer, sheet_name='users', index=False)
            
            # Personalities sheet
            personalities_df = pd.DataFrame(columns=[
                'personality_id', 'telegram_id', 'name', 'description', 
                'prompt_template', 'temperature', 'max_tokens', 'is_default', 'created_at'
            ])
            personalities_df.to_excel(writer, sheet_name='personalities', index=False)
            
            # Scraping history sheet
            history_df = pd.DataFrame(columns=[
                'scrape_id', 'telegram_id', 'subreddit', 'timestamp', 'personality_used'
            ])
            history_df.to_excel(writer, sheet_name='history', index=False)
        print("Excel database created successfully!")
    else:
        print(f"Excel database already exists: {EXCEL_FILE}")

def get_or_create_user(telegram_id, username=None, first_name=None):
    """Get or create user in Excel database"""
    try:
        users_df = pd.read_excel(EXCEL_FILE, sheet_name='users')
        
        # Check if user exists
        user_exists = users_df[users_df['telegram_id'] == telegram_id]
        if not user_exists.empty:
            return user_exists.iloc[0].to_dict()
        
        # Create new user
        new_user = {
            'telegram_id': telegram_id,
            'username': username or '',
            'first_name': first_name or '',
            'created_at': datetime.now().isoformat()
        }
        
        users_df = pd.concat([users_df, pd.DataFrame([new_user])], ignore_index=True)
        
        # Save to Excel
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            users_df.to_excel(writer, sheet_name='users', index=False)
        
        # Create default personality for new user
        create_default_personality(telegram_id)
        
        return new_user
    except Exception as e:
        print(f"Error managing user: {e}")
        return None

def create_default_personality(telegram_id):
    """Create default personality for new user"""
    try:
        personalities_df = pd.read_excel(EXCEL_FILE, sheet_name='personalities')
        
        # Check if default personality already exists
        existing_default = personalities_df[
            (personalities_df['telegram_id'] == telegram_id) & 
            (personalities_df['is_default'] == True)
        ]
        
        if existing_default.empty:
            default_personality = {
                'personality_id': str(uuid.uuid4()),
                'telegram_id': telegram_id,
                'name': 'default',
                'description': 'Default friendly personality',
                'prompt_template': 'Please rewrite this Reddit post title in a more engaging way while keeping the main points: {original_title}',
                'temperature': 0.7,
                'max_tokens': 100,
                'is_default': True,
                'created_at': datetime.now().isoformat()
            }
            
            personalities_df = pd.concat([personalities_df, pd.DataFrame([default_personality])], ignore_index=True)
            
            with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                personalities_df.to_excel(writer, sheet_name='personalities', index=False)
            
            print(f"Created default personality for user {telegram_id}")
    except Exception as e:
        print(f"Error creating default personality: {e}")

def get_user_personalities(telegram_id):
    """Get user personalities from Excel"""
    try:
        personalities_df = pd.read_excel(EXCEL_FILE, sheet_name='personalities')
        user_personalities = personalities_df[personalities_df['telegram_id'] == telegram_id]
        return user_personalities.to_dict('records')
    except Exception as e:
        print(f"Error getting personalities: {e}")
        return []

def create_personality(telegram_id, name, description, prompt_template, temperature=0.7, max_tokens=100, is_default=False):
    """Create new personality in Excel"""
    try:
        personalities_df = pd.read_excel(EXCEL_FILE, sheet_name='personalities')
        
        # Check if personality name already exists for this user
        existing_personality = personalities_df[
            (personalities_df['telegram_id'] == telegram_id) & 
            (personalities_df['name'] == name)
        ]
        
        if not existing_personality.empty:
            return {"error": f"Personality '{name}' already exists!"}
        
        # If setting as default, unset other defaults for this user
        if is_default:
            personalities_df.loc[
                personalities_df['telegram_id'] == telegram_id, 'is_default'
            ] = False
        
        new_personality = {
            'personality_id': str(uuid.uuid4()),
            'telegram_id': telegram_id,
            'name': name,
            'description': description,
            'prompt_template': prompt_template,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'is_default': is_default,
            'created_at': datetime.now().isoformat()
        }
        
        personalities_df = pd.concat([personalities_df, pd.DataFrame([new_personality])], ignore_index=True)
        
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            personalities_df.to_excel(writer, sheet_name='personalities', index=False)
        
        return new_personality
    except Exception as e:
        print(f"Error creating personality: {e}")
        return {"error": str(e)}

def delete_personality(telegram_id, personality_name):
    """Delete personality from Excel"""
    try:
        personalities_df = pd.read_excel(EXCEL_FILE, sheet_name='personalities')
        
        # Find the personality to delete
        personality_to_delete = personalities_df[
            (personalities_df['telegram_id'] == telegram_id) & 
            (personalities_df['name'] == personality_name)
        ]
        
        if personality_to_delete.empty:
            return {"error": f"Personality '{personality_name}' not found!"}
        
        # Don't allow deleting default personality if it's the only one
        user_personalities = personalities_df[personalities_df['telegram_id'] == telegram_id]
        if len(user_personalities) == 1 and personality_to_delete.iloc[0]['is_default']:
            return {"error": "Cannot delete the only personality! Create another one first."}
        
        # Remove the personality
        personalities_df = personalities_df[
            ~((personalities_df['telegram_id'] == telegram_id) & 
              (personalities_df['name'] == personality_name))
        ]
        
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            personalities_df.to_excel(writer, sheet_name='personalities', index=False)
        
        return {"success": f"Personality '{personality_name}' deleted successfully!"}
    except Exception as e:
        print(f"Error deleting personality: {e}")
        return {"error": str(e)}

@app.route('/')
def home():
    return jsonify({
        "message": "Reddit Scraper API with Excel Database",
        "database": EXCEL_FILE,
        "endpoints": {
            "health": "/api/health",
            "scrape": "/api/scrape",
            "personalities": "/api/personalities",
            "create_personality": "/api/personality",
            "delete_personality": "/api/personality/delete"
        }
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "service": "reddit-scraper-api",
        "version": "1.0.0",
        "database": EXCEL_FILE,
        "database_exists": Path(EXCEL_FILE).exists()
    })

@app.route('/api/scrape', methods=['POST'])
@require_api_key
def scrape_reddit():
    """Scrape Reddit and optionally generate AI titles"""
    data = request.get_json()
    
    subreddit = data.get('subreddit', 'python')
    limit = min(data.get('limit', 10), 50)
    sort = data.get('sort', 'hot')
    time_filter = data.get('time_filter', 'week')
    telegram_id = data.get('telegram_id', 0)
    personality_name = data.get('personality_name', 'default')
    use_ai = data.get('use_ai', False)
    
    task_id = str(uuid.uuid4())
    
    try:
        # Get or create user
        user = get_or_create_user(telegram_id)
        if not user:
            return jsonify({"error": "Failed to manage user"}), 500
        
        # Get personality if AI is requested
        personality = None
        if use_ai:
            personalities = get_user_personalities(telegram_id)
            if personality_name == "default":
                personality = next((p for p in personalities if p['is_default']), None)
            else:
                personality = next((p for p in personalities if p['name'] == personality_name), None)
            
            if not personality:
                return jsonify({"error": f"Personality '{personality_name}' not found!"}), 400
        
        # Scrape Reddit
        subreddit_obj = reddit.subreddit(subreddit)
        
        if sort == "hot":
            submissions = list(subreddit_obj.hot(limit=limit))
        elif sort == "new":
            submissions = list(subreddit_obj.new(limit=limit))
        elif sort == "top":
            submissions = list(subreddit_obj.top(time_filter=time_filter, limit=limit))
        elif sort == "rising":
            submissions = list(subreddit_obj.rising(limit=limit))
        else:
            submissions = list(subreddit_obj.hot(limit=limit))
        
        # Process posts
        results = []
        for submission in submissions:
            post_data = {
                "id": submission.id,
                "title": submission.title,
                "score": submission.score,
                "url": submission.url,
                "permalink": f"https://reddit.com{submission.permalink}",
                "created_utc": submission.created_utc,
                "author": str(submission.author) if submission.author else "[deleted]",
                "subreddit": subreddit,
                "original_title": submission.title
            }
            
            # Generate AI title if requested
            if use_ai and personality:
                try:
                    prompt = personality['prompt_template'].replace("{original_title}", submission.title)
                    
                    response = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "You are a creative title rewriter. Keep titles concise and engaging."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=float(personality['temperature']),
                        max_tokens=int(personality['max_tokens'])
                    )
                    
                    ai_title = response.choices[0].message.content.strip().strip('"').strip("'")
                    post_data["ai_title"] = ai_title
                except Exception as e:
                    print(f"AI Error: {e}")
                    post_data["ai_title"] = submission.title  # Fallback to original
            
            post_data["personality_used"] = personality['name'] if personality else "none"
            results.append(post_data)
        
        # Save to history
        try:
            history_df = pd.read_excel(EXCEL_FILE, sheet_name='history')
            new_history = {
                'scrape_id': task_id,
                'telegram_id': telegram_id,
                'subreddit': subreddit,
                'timestamp': datetime.now().isoformat(),
                'personality_used': personality['name'] if personality else "none"
            }
            history_df = pd.concat([history_df, pd.DataFrame([new_history])], ignore_index=True)
            
            with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                history_df.to_excel(writer, sheet_name='history', index=False)
        except Exception as e:
            print(f"Error saving history: {e}")
        
        return jsonify({
            "task_id": task_id,
            "status": "completed",
            "message": f"Successfully scraped {len(results)} posts from r/{subreddit}",
            "telegram_id": telegram_id,
            "results": results,
            "ai_used": use_ai,
            "personality_used": personality['name'] if personality else "none"
        })
        
    except Exception as e:
        return jsonify({
            "task_id": task_id,
            "status": "failed",
            "message": str(e),
            "telegram_id": telegram_id,
            "results": None
        }), 500

@app.route('/api/personality', methods=['POST'])
@require_api_key
def create_personality_endpoint():
    """Create a new personality"""
    data = request.get_json()
    
    telegram_id = data.get('telegram_id')
    if not telegram_id:
        return jsonify({"error": "telegram_id required"}), 400
    
    # Get or create user first
    user = get_or_create_user(telegram_id)
    if not user:
        return jsonify({"error": "Failed to manage user"}), 500
    
    result = create_personality(
        telegram_id=telegram_id,
        name=data.get('name', 'custom'),
        description=data.get('description', ''),
        prompt_template=data.get('prompt_template', 'Rewrite this title: {original_title}'),
        temperature=data.get('temperature', 0.7),
        max_tokens=data.get('max_tokens', 100),
        is_default=data.get('is_default', False)
    )
    
    if "error" in result:
        return jsonify(result), 400
    else:
        return jsonify(result)

@app.route('/api/personality/delete', methods=['POST'])
@require_api_key
def delete_personality_endpoint():
    """Delete a personality"""
    data = request.get_json()
    
    telegram_id = data.get('telegram_id')
    personality_name = data.get('personality_name')
    
    if not telegram_id or not personality_name:
        return jsonify({"error": "telegram_id and personality_name required"}), 400
    
    result = delete_personality(telegram_id, personality_name)
    
    if "error" in result:
        return jsonify(result), 400
    else:
        return jsonify(result)

@app.route('/api/personalities', methods=['GET'])
@require_api_key
def list_personalities():
    """List personalities for a user"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({"error": "telegram_id required"}), 400
    
    # Get or create user first
    user = get_or_create_user(telegram_id)
    if not user:
        return jsonify({"error": "Failed to manage user"}), 500
    
    personalities = get_user_personalities(telegram_id)
    return jsonify(personalities)

# Initialize Excel database on startup
init_excel_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
