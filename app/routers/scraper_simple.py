from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import uuid
import os

from ..database import get_db, User, AIPersonality
from ..models_simple import ScrapeRequest, ScrapeResponse, AIEnhancedPost
from ..services.reddit_service import RedditService
from ..services.openai_service import OpenAIService

router = APIRouter(prefix="/api", tags=["scraper"])

# Initialize services
reddit_service = RedditService()
openai_service = OpenAIService()

# Simple API key authentication
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True

@router.post("/scrape")
async def scrape_reddit(
    request_data: Dict[str, Any],
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_api_key)
):
    """Scrape Reddit and generate AI titles"""
    request = ScrapeRequest.from_dict(request_data)
    task_id = str(uuid.uuid4())
    
    try:
        # Get user and personality
        user = db.query(User).filter(User.telegram_id == request.telegram_id).first()
        if not user:
            # Create default user and personality
            user = User(telegram_id=request.telegram_id)
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
            
        # Get the requested personality or default
        if request.personality_name == "default":
            personality = db.query(AIPersonality).filter(
                AIPersonality.user_id == user.user_id,
                AIPersonality.is_default == True
            ).first()
        else:
            personality = db.query(AIPersonality).filter(
                AIPersonality.user_id == user.user_id,
                AIPersonality.name == request.personality_name
            ).first()
            
        if not personality:
            raise HTTPException(status_code=404, detail=f"Personality '{request.personality_name}' not found")
            
        # Scrape Reddit
        posts = await reddit_service.scrape_subreddit(
            request.subreddit,
            request.sort,
            request.time_filter,
            request.limit
        )
        
        # Generate AI titles for each post
        enhanced_posts = []
        for post in posts:
            ai_title = await openai_service.generate_ai_title(
                post["title"],
                personality.prompt_template,
                personality.temperature,
                personality.max_tokens
            )
            
            enhanced_post = AIEnhancedPost(
                **post,
                original_title=post["title"],
                ai_title=ai_title,
                personality_used=personality.name
            )
            enhanced_posts.append(enhanced_post.to_dict())
            
        response = ScrapeResponse(
            task_id=task_id,
            status="completed",
            message=f"Successfully scraped {len(enhanced_posts)} posts from r/{request.subreddit}",
            telegram_id=request.telegram_id,
            results=enhanced_posts
        )
        
        return response.to_dict()
        
    except Exception as e:
        response = ScrapeResponse(
            task_id=task_id,
            status="failed",
            message=str(e),
            telegram_id=request.telegram_id,
            results=None
        )
        return response.to_dict()

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "reddit-scraper-api",
        "version": "1.0.0"
    }
