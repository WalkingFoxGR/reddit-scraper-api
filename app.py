from flask import Flask, request, jsonify
import os
import praw
from dotenv import load_dotenv
from datetime import datetime
import uuid
import logging

load_dotenv()

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
            "scrape": "/api/scrape",
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
    """Simple scrape that returns just titles and upvotes"""
    data = request.get_json()
    
    # Log received data for debugging
    logger.info(f"Received data: {data}")
    
    subreddit = data.get('subreddit', 'python')
    limit = min(data.get('limit', 10), 50)
    sort = data.get('sort', 'hot')
    time_filter = data.get('time_filter', 'week')
    telegram_id = data.get('telegram_id')
    
    # Additional logging
    logger.info(f"Scraping r/{subreddit} with {limit} posts, sort: {sort}, time: {time_filter}")
    
    task_id = str(uuid.uuid4())
    
    try:
        subreddit_obj = reddit.subreddit(subreddit)
        
        # Get submissions based on sort type
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
        
        results = []
        for i, submission in enumerate(submissions, 1):
            post_data = {
                "index": i,
                "id": submission.id,
                "title": submission.title,
                "score": submission.score,
                "url": submission.url,
                "permalink": f"https://reddit.com{submission.permalink}",
                "author": str(submission.author) if submission.author else "[deleted]",
                "subreddit": subreddit,
                "num_comments": submission.num_comments
            }
            results.append(post_data)
        
        logger.info(f"Successfully scraped {len(results)} posts from r/{subreddit}")
        
        return jsonify({
            "task_id": task_id,
            "status": "completed",
            "message": f"Successfully scraped {len(results)} posts from r/{subreddit}",
            "results": results,
            "subreddit": subreddit,
            "sort": sort,
            "time_filter": time_filter,
            "telegram_id": telegram_id
        })
        
    except Exception as e:
        logger.error(f"Error scraping r/{subreddit}: {str(e)}")
        return jsonify({
            "task_id": task_id,
            "status": "failed", 
            "message": f"Error scraping r/{subreddit}: {str(e)}",
            "results": []
        }), 500

@app.route('/api/enhance-titles', methods=['POST'])
def enhance_titles():
    """Enhance titles with AI based on user prompt"""
    try:
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
    except ImportError:
        return jsonify({
            "status": "failed",
            "message": "OpenAI library not available"
        }), 500
    
    data = request.get_json()
    titles = data.get('titles', [])
    user_prompt = data.get('prompt', 'Make these titles more engaging and clickable')
    telegram_id = data.get('telegram_id')
    
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
            
            # Create AI prompt
            ai_prompt = f"""
            Transform this Reddit post title to be more engaging and clickable.
            
            Original title: "{original_title}"
            Upvotes: {score}
            
            User instruction: {user_prompt}
            
            Rules:
            - Keep it under 100 characters
            - Make it engaging and clickable
            - Maintain the original meaning
            - Don't use excessive clickbait
            
            Enhanced title:
            """
            
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are an expert at creating engaging, clickable titles while maintaining authenticity."},
                        {"role": "user", "content": ai_prompt}
                    ],
                    max_tokens=100,
                    temperature=0.7
                )
                
                enhanced_title = response.choices[0].message.content.strip()
                
                enhanced_titles.append({
                    "index": item.get('index', len(enhanced_titles) + 1),
                    "original_title": original_title,
                    "enhanced_title": enhanced_title,
                    "score": score,
                    "url": item.get('url', ''),
                    "permalink": item.get('permalink', ''),
                    "author": item.get('author', '[deleted]')
                })
                
            except Exception as ai_error:
                logger.error(f"AI enhancement error: {str(ai_error)}")
                # Fallback to original title
                enhanced_titles.append({
                    "index": item.get('index', len(enhanced_titles) + 1),
                    "original_title": original_title,
                    "enhanced_title": original_title,
                    "score": score,
                    "url": item.get('url', ''),
                    "permalink": item.get('permalink', ''),
                    "author": item.get('author', '[deleted]'),
                    "error": "AI enhancement failed"
                })
        
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

# Keep the original scrape endpoint for backward compatibility
@app.route('/api/scrape', methods=['POST'])
def scrape_reddit():
    """Original scrape endpoint - for backward compatibility"""
    return scrape_simple()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
