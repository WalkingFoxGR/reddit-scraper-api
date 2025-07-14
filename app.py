from flask import Flask, request, jsonify
import os
import praw
from dotenv import load_dotenv
from datetime import datetime
import uuid
import logging
import random

load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Reddit client
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=os.getenv("REDDIT_USER_AGENT", "RedditScraper/1.0")
)

@app.route('/')
def home():
    return jsonify({
        "message": "Reddit Scraper API",
        "endpoints": {
            "health": "/api/health",
            "scrape-simple": "/api/scrape-simple",
            "enhance-titles": "/api/enhance-titles"
        }
    })

@app.route('/api/health')
def health():
    return jsonify({
        "status": "healthy",
        "service": "reddit-scraper-api",
        "version": "1.0.0"
    })

@app.route('/api/scrape-simple', methods=['POST'])
def scrape_simple():
    """Simple scrape that returns just titles and upvotes - matches local implementation"""
    data = request.get_json()
    
    # Log received data for debugging
    logger.info(f"=== NEW SCRAPE REQUEST ===")
    logger.info(f"Received data: {data}")
    
    subreddit_name = data.get('subreddit', 'python').lower().strip()
    limit = min(int(data.get('limit', 10)), 50)
    sort = data.get('sort', 'hot').lower().strip()
    time_filter = data.get('time_filter', 'week').lower().strip()
    telegram_id = data.get('telegram_id')
    
    # Additional logging
    logger.info(f"Processing: r/{subreddit_name}, limit={limit}, sort={sort}, time={time_filter}")
    
    task_id = str(uuid.uuid4())
    
    try:
        # Create fresh subreddit object (no caching)
        subreddit_obj = reddit.subreddit(subreddit_name)
        
        # Verify subreddit exists
        try:
            subreddit_display_name = subreddit_obj.display_name
            logger.info(f"Subreddit verified: r/{subreddit_display_name}")
        except Exception as e:
            logger.error(f"Invalid subreddit: r/{subreddit_name}")
            return jsonify({
                "task_id": task_id,
                "status": "failed",
                "message": f"Subreddit r/{subreddit_name} not found or private",
                "results": []
            }), 404
        
        # Get submissions based on sort type (exactly like local app)
        submissions = []
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
        
        logger.info(f"Retrieved {len(submissions)} submissions from Reddit")
        
        # Process submissions (exactly like local app)
        results = []
        for i, submission in enumerate(submissions, 1):
            post_data = {
                "index": i,
                "id": submission.id,
                "title": submission.title,
                "score": submission.score,  # This is upvotes
                "upvotes": submission.score,  # Add explicit upvotes field
                "url": submission.url,
                "permalink": f"https://reddit.com{submission.permalink}",
                "author": str(submission.author) if submission.author else "[deleted]",
                "subreddit": subreddit_name,  # Use requested subreddit name
                "num_comments": submission.num_comments
            }
            results.append(post_data)
        
        logger.info(f"Successfully processed {len(results)} posts from r/{subreddit_name}")
        
        return jsonify({
            "task_id": task_id,
            "status": "completed",
            "message": f"Successfully scraped {len(results)} posts from r/{subreddit_name}",
            "results": results,
            "subreddit": subreddit_name,
            "sort": sort,
            "time_filter": time_filter,
            "telegram_id": telegram_id,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error scraping r/{subreddit_name}: {str(e)}")
        return jsonify({
            "task_id": task_id,
            "status": "failed", 
            "message": f"Error scraping r/{subreddit_name}: {str(e)}",
            "results": []
        }), 500

@app.route('/api/enhance-titles', methods=['POST'])
def enhance_titles():
    """Enhance titles with AI based on user prompt - matches local implementation"""
    
    # Check OpenAI availability
    try:
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        if not openai.api_key:
            return jsonify({
                "status": "failed",
                "message": "OpenAI API key not configured"
            }), 500
            
    except ImportError:
        return jsonify({
            "status": "failed",
            "message": "OpenAI library not available"
        }), 500
    
    data = request.get_json()
    titles = data.get('titles', [])
    user_prompt = data.get('prompt', 'Make these titles more engaging and clickable')
    telegram_id = data.get('telegram_id')
    
    logger.info(f"AI Enhancement request: {len(titles)} titles, prompt: '{user_prompt}'")
    
    if not titles:
        return jsonify({
            "status": "failed",
            "message": "No titles provided"
        }), 400
    
    try:
        enhanced_titles = []
        
        for item in titles:
            original_title = item.get('title', '')
            score = item.get('score', 0)
            
            # Create AI prompt (matches local app logic)
            ai_prompt = f"""Please rewrite the following Reddit post title to make it more engaging:

Original title: "{original_title}"
Upvotes: {score}

User instruction: {user_prompt}

Rules:
- Keep it under 100 characters
- Make it engaging and clickable
- Maintain the original meaning
- Don't use excessive clickbait

Enhanced title:"""
            
            try:
                # Use OpenAI API (same as local app)
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a creative title rewriter."},
                        {"role": "user", "content": ai_prompt}
                    ],
                    max_tokens=100,
                    temperature=0.7
                )
                
                enhanced_title = response.choices[0].message.content.strip()
                
                enhanced_titles.append({
                    "index": item.get('index', len(enhanced_titles) + 1),
                    "original_title": original_title,
                    "ai_title": enhanced_title,  # Match local app naming
                    "enhanced_title": enhanced_title,  # Also provide this for compatibility
                    "score": score,
                    "upvotes": score,  # Add explicit upvotes
                    "url": item.get('url', ''),
                    "permalink": item.get('permalink', ''),
                    "author": item.get('author', '[deleted]')
                })
                
            except Exception as ai_error:
                logger.error(f"AI enhancement error for title '{original_title}': {str(ai_error)}")
                enhanced_titles.append({
                    "index": item.get('index', len(enhanced_titles) + 1),
                    "original_title": original_title,
                    "ai_title": original_title + " ✨",
                    "enhanced_title": original_title + " ✨",
                    "score": score,
                    "upvotes": score,
                    "url": item.get('url', ''),
                    "permalink": item.get('permalink', ''),
                    "author": item.get('author', '[deleted]'),
                    "error": "AI enhancement failed"
                })
        
        logger.info(f"Successfully enhanced {len(enhanced_titles)} titles")
        
        return jsonify({
            "status": "completed",
            "message": f"Enhanced {len(enhanced_titles)} titles",
            "results": enhanced_titles,
            "user_prompt": user_prompt,
            "telegram_id": telegram_id
        })
        
    except Exception as e:
        logger.error(f"Error enhancing titles: {str(e)}")
        return jsonify({
            "status": "failed",
            "message": f"Error enhancing titles: {str(e)}"
        }), 500

# Backward compatibility endpoint
@app.route('/api/scrape', methods=['POST'])
def scrape_reddit():
    """Backward compatibility with old scrape endpoint"""
    return scrape_simple()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
