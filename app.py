from flask import Flask, request, jsonify
import os
import praw
import openai
from sqlalchemy import create_engine, Column, BigInteger, String, Text, Boolean, TIMESTAMP, ForeignKey, Float, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
from dotenv import load_dotenv
import uuid
import asyncio
from functools import wraps

load_dotenv()

# Flask app
app = Flask(__name__)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Models
class User(Base):
    __tablename__ = "users"
    
    user_id = Column(BigInteger, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255))
    first_name = Column(String(255))
    created_at = Column(TIMESTAMP, server_default=func.now())
    is_active = Column(Boolean, default=True)
    
    personalities = relationship("AIPersonality", back_populates="user", cascade="all, delete-orphan")

class AIPersonality(Base):
    __tablename__ = "ai_personalities"
    
    personality_id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    prompt_template = Column(Text, nullable=False)
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=100)
    is_default = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    user = relationship("User", back_populates="personalities")

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize services
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT", "RedditScraper/1.0")
)

openai.api_key = os.getenv("OPENAI_API_KEY")

# API key check decorator
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.getenv("API_KEY"):
            return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    return jsonify({
        "message": "Reddit Scraper API",
        "endpoints": {
            "health": "/api/health",
            "scrape": "/api/scrape",
            "personalities": "/api/personalities"
        }
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "service": "reddit-scraper-api",
        "version": "1.0.0"
    })

@app.route('/api/scrape', methods=['POST'])
@require_api_key
def scrape_reddit():
    """Scrape Reddit and generate AI titles"""
    data = request.get_json()
    
    # Extract parameters
    subreddit = data.get('subreddit', 'python')
    limit = min(data.get('limit', 10), 50)  # Max 50
    sort = data.get('sort', 'hot')
    time_filter = data.get('time_filter', 'week')
    telegram_id = data.get('telegram_id', 0)
    personality_name = data.get('personality_name', 'default')
    
    task_id = str(uuid.uuid4())
    
    try:
        # Get database session
        db = SessionLocal()
        
        # Get or create user
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            user = User(telegram_id=telegram_id)
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # Create default personality
            default_personality = AIPersonality(
                user_id=user.user_id,
                name="default",
                description="Default friendly personality",
                prompt_template="""Please rewrite the following Reddit post title in a more engaging way while keeping the main points:

{original_title}

Make it more conversational and add some personality. Keep the tone friendly and approachable.""",
                is_default=True
            )
            db.add(default_personality)
            db.commit()
        
        # Get personality
        if personality_name == "default":
            personality = db.query(AIPersonality).filter(
                AIPersonality.user_id == user.user_id,
                AIPersonality.is_default == True
            ).first()
        else:
            personality = db.query(AIPersonality).filter(
                AIPersonality.user_id == user.user_id,
                AIPersonality.name == personality_name
            ).first()
            
        if not personality:
            # Use the default personality if requested one not found
            personality = db.query(AIPersonality).filter(
                AIPersonality.user_id == user.user_id,
                AIPersonality.is_default == True
            ).first()
        
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
            # Get post data
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
            
            # Generate AI title
            try:
                prompt = personality.prompt_template.replace("{original_title}", submission.title)
                
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a creative title rewriter. Keep titles concise and engaging."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=personality.temperature,
                    max_tokens=personality.max_tokens
                )
                
                ai_title = response.choices[0].message.content.strip().strip('"').strip("'")
                post_data["ai_title"] = ai_title
            except Exception as e:
                post_data["ai_title"] = f"[AI Error] {submission.title}"
                
            post_data["personality_used"] = personality.name
            results.append(post_data)
        
        db.close()
        
        return jsonify({
            "task_id": task_id,
            "status": "completed",
            "message": f"Successfully scraped {len(results)} posts from r/{subreddit}",
            "telegram_id": telegram_id,
            "results": results
        })
        
    except Exception as e:
        return jsonify({
            "task_id": task_id,
            "status": "failed",
            "message": str(e),
            "telegram_id": telegram_id,
            "results": None
        }), 500

@app.route('/api/personalities', methods=['GET'])
@require_api_key
def list_personalities():
    """List personalities for a user"""
    telegram_id = request.args.get('telegram_id', type=int)
    if not telegram_id:
        return jsonify({"error": "telegram_id required"}), 400
        
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    
    if not user:
        db.close()
        return jsonify([])
    
    personalities = db.query(AIPersonality).filter(
        AIPersonality.user_id == user.user_id
    ).all()
    
    result = [
        {
            "personality_id": p.personality_id,
            "name": p.name,
            "description": p.description,
            "is_default": p.is_default,
            "created_at": p.created_at.isoformat() if p.created_at else None
        }
        for p in personalities
    ]
    
    db.close()
    return jsonify(result)

@app.route('/api/personality', methods=['POST'])
@require_api_key
def create_personality():
    """Create a new personality"""
    data = request.get_json()
    
    telegram_id = data.get('telegram_id')
    if not telegram_id:
        return jsonify({"error": "telegram_id required"}), 400
        
    db = SessionLocal()
    
    # Get or create user
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # Create personality
    personality = AIPersonality(
        user_id=user.user_id,
        name=data.get('name', 'custom'),
        description=data.get('description', ''),
        prompt_template=data.get('prompt_template', 'Rewrite this title: {original_title}'),
        temperature=data.get('temperature', 0.7),
        max_tokens=data.get('max_tokens', 100),
        is_default=data.get('is_default', False)
    )
    
    if personality.is_default:
        # Unset other defaults
        db.query(AIPersonality).filter(
            AIPersonality.user_id == user.user_id,
            AIPersonality.is_default == True
        ).update({"is_default": False})
    
    db.add(personality)
    db.commit()
    db.refresh(personality)
    
    result = {
        "personality_id": personality.personality_id,
        "name": personality.name,
        "description": personality.description,
        "is_default": personality.is_default,
        "created_at": personality.created_at.isoformat() if personality.created_at else None
    }
    
    db.close()
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
