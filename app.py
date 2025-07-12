from flask import Flask, request, jsonify
import os
import praw
from dotenv import load_dotenv
from datetime import datetime
import uuid

load_dotenv()

# Flask app
app = Flask(__name__)

# Initialize Reddit
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
            "scrape": "/api/scrape"
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
def scrape_reddit():
    """Scrape Reddit posts - AI processing handled by n8n"""
    data = request.get_json()
    
    # Extract parameters
    subreddit = data.get('subreddit', 'python')
    limit = min(data.get('limit', 10), 50)
    sort = data.get('sort', 'hot')
    time_filter = data.get('time_filter', 'week')
    telegram_id = data.get('telegram_id')
    
    task_id = str(uuid.uuid4())
    
    try:
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
        
        # Process posts without AI (AI will be handled in n8n)
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
                "num_comments": submission.num_comments,
                "upvote_ratio": submission.upvote_ratio,
                "selftext": submission.selftext[:200] if submission.selftext else "",
                "is_video": submission.is_video,
                "over_18": submission.over_18
            }
            results.append(post_data)
        
        return jsonify({
            "task_id": task_id,
            "status": "completed",
            "message": f"Successfully scraped {len(results)} posts from r/{subreddit}",
            "results": results,
            "subreddit": subreddit
        })
        
    except Exception as e:
        return jsonify({
            "task_id": task_id,
            "status": "failed",
            "message": str(e),
            "results": None
        }), 500

if __name__ == '__main__':
    app.run(debug=True)
