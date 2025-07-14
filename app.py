import os
import asyncio
import logging
from datetime import datetime, timedelta
import json
import aiohttp
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import praw
from typing import Dict, List, Optional
import redis
from dataclasses import dataclass, asdict
import time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', 'RedditScraperBot/1.0')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
ALLOWED_USERS = os.getenv('ALLOWED_USERS', '').split(',')  # Comma-separated telegram user IDs

# Initialize Redis for rate limiting
try:
    redis_client = redis.from_url(REDIS_URL)
except Exception as e:
    logger.warning(f"Redis connection failed: {e}. Rate limiting disabled.")
    redis_client = None

@dataclass
class RedditPost:
    """Reddit post data structure"""
    title: str
    score: int
    url: str
    author: str
    created_utc: float
    num_comments: int
    subreddit: str
    permalink: str

class RateLimiter:
    """Rate limiter for Reddit API calls"""
    def __init__(self, redis_client: Optional[redis.Redis]):
        self.redis = redis_client
        self.reddit_limit = 100  # Reddit: 100 requests per minute
        self.telegram_limit = 30  # Telegram: 30 messages per second
        
    async def check_reddit_limit(self, user_id: str) -> bool:
        """Check if we can make a Reddit API call"""
        if not self.redis:
            return True
            
        key = f"reddit_limit:{user_id}"
        current = self.redis.incr(key)
        if current == 1:
            self.redis.expire(key, 60)
        return current <= self.reddit_limit
    
    async def check_telegram_limit(self) -> bool:
        """Check if we can send a Telegram message"""
        if not self.redis:
            return True
            
        key = "telegram_limit"
        current = self.redis.incr(key)
        if current == 1:
            self.redis.expire(key, 1)
        return current <= self.telegram_limit

rate_limiter = RateLimiter(redis_client)

class RedditScraper:
    """Reddit API wrapper using PRAW"""
    def __init__(self):
        self.reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT
        )
        
    async def scrape_subreddit(
        self, 
        subreddit_name: str, 
        limit: int = 10, 
        sort_type: str = 'hot',
        time_filter: str = 'week'
    ) -> List[RedditPost]:
        """Scrape posts from a subreddit"""
        try:
            subreddit = self.reddit.subreddit(subreddit_name)
            
            # Get posts based on sort type
            if sort_type == 'top':
                posts = subreddit.top(time_filter=time_filter, limit=limit)
            elif sort_type == 'new':
                posts = subreddit.new(limit=limit)
            elif sort_type == 'hot':
                posts = subreddit.hot(limit=limit)
            elif sort_type == 'rising':
                posts = subreddit.rising(limit=limit)
            else:
                posts = subreddit.hot(limit=limit)
            
            # Extract post data
            scraped_posts = []
            for post in posts:
                reddit_post = RedditPost(
                    title=post.title,
                    score=post.score,
                    url=post.url,
                    author=str(post.author) if post.author else '[deleted]',
                    created_utc=post.created_utc,
                    num_comments=post.num_comments,
                    subreddit=post.subreddit.display_name,
                    permalink=f"https://reddit.com{post.permalink}"
                )
                scraped_posts.append(reddit_post)
                
            return scraped_posts
            
        except Exception as e:
            logger.error(f"Error scraping r/{subreddit_name}: {e}")
            raise

class N8NConnector:
    """Handle communication with n8n workflow"""
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        
    async def send_to_n8n(self, data: Dict) -> Dict:
        """Send data to n8n webhook and get response"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    self.webhook_url,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=180)
                ) as response:
                    return await response.json()
            except Exception as e:
                logger.error(f"Error sending to n8n: {e}")
                raise

# Initialize components
reddit_scraper = RedditScraper()
n8n_connector = N8NConnector(N8N_WEBHOOK_URL) if N8N_WEBHOOK_URL else None

async def check_user_access(user_id: int) -> bool:
    """Check if user has access to the bot"""
    if not ALLOWED_USERS or ALLOWED_USERS == ['']:
        return True  # No restrictions if ALLOWED_USERS not set
    return str(user_id) in ALLOWED_USERS

async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scrape command"""
    user_id = update.effective_user.id
    
    # Check user access
    if not await check_user_access(user_id):
        await update.message.reply_text(
            "❌ Access denied. Please contact the administrator to request access."
        )
        return
    
    # Parse command arguments
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "🤔 I need more info to scrape Reddit!\n\n"
            "💡 Usage: `/scrape [subreddit] [limit] [sort] [time_filter]`\n"
            "Example: `/scrape python 10 top week`\n\n"
            "Sort options: hot, new, top, rising\n"
            "Time filters (for top): hour, day, week, month, year, all"
        )
        return
    
    subreddit = args[0]
    try:
        limit = min(int(args[1]), 50)  # Max 50 posts
    except ValueError:
        await update.message.reply_text("❌ Invalid number of posts. Please use a number between 1-50.")
        return
        
    sort_type = args[2].lower() if args[2].lower() in ['hot', 'new', 'top', 'rising'] else 'hot'
    time_filter = args[3].lower() if args[3].lower() in ['hour', 'day', 'week', 'month', 'year', 'all'] else 'week'
    
    # Check rate limits
    if not await rate_limiter.check_reddit_limit(str(user_id)):
        await update.message.reply_text(
            "⏳ Rate limit reached. Please wait a minute before trying again."
        )
        return
    
    # Send initial message
    await update.message.reply_text(
        f"🔍 Scraping r/{subreddit}...\n"
        f"📊 Fetching {limit} {sort_type} posts"
        f"{f' from the past {time_filter}' if sort_type == 'top' else ''}..."
    )
    
    try:
        # Scrape Reddit
        posts = await reddit_scraper.scrape_subreddit(
            subreddit_name=subreddit,
            limit=limit,
            sort_type=sort_type,
            time_filter=time_filter
        )
        
        if not posts:
            await update.message.reply_text(
                f"❌ No posts found in r/{subreddit}. "
                "Please check the subreddit name and try again."
            )
            return
        
        # Prepare data for n8n
        scrape_data = {
            "telegram_id": user_id,
            "command": "scrape",
            "subreddit": subreddit,
            "posts": [asdict(post) for post in posts],
            "metadata": {
                "sort_type": sort_type,
                "time_filter": time_filter,
                "count": len(posts),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        # Send titles preview to user
        titles_preview = "\n\n".join([
            f"{i+1}. {post.title[:100]}{'...' if len(post.title) > 100 else ''}"
            for i, post in enumerate(posts[:5])
        ])
        
        await update.message.reply_text(
            f"✅ Successfully scraped {len(posts)} posts from r/{subreddit}!\n\n"
            f"**Preview of titles:**\n{titles_preview}\n\n"
            f"{'... and ' + str(len(posts) - 5) + ' more' if len(posts) > 5 else ''}"
        )
        
        # Ask user if they want AI processing
        await update.message.reply_text(
            "🤖 Would you like me to process these titles with AI?\n"
            "Reply with your instructions for how to rewrite them, "
            "or type 'skip' to just save the original titles."
        )
        
        # Store data in context for next message
        context.user_data['pending_scrape'] = scrape_data
        context.user_data['awaiting_ai_prompt'] = True
        
    except Exception as e:
        logger.error(f"Error in scrape command: {e}")
        await update.message.reply_text(
            f"❌ Error scraping r/{subreddit}: {str(e)}\n"
            "Please check the subreddit name and try again."
        )

async def handle_ai_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle AI prompt for title rewriting"""
    if not context.user_data.get('awaiting_ai_prompt'):
        return
    
    user_message = update.message.text.strip()
    scrape_data = context.user_data.get('pending_scrape')
    
    if not scrape_data:
        await update.message.reply_text("❌ No pending scrape data found. Please run /scrape again.")
        context.user_data['awaiting_ai_prompt'] = False
        return
    
    # Clear the waiting flag
    context.user_data['awaiting_ai_prompt'] = False
    
    if user_message.lower() == 'skip':
        # Just send original titles to n8n
        scrape_data['ai_processing'] = False
    else:
        # Include AI prompt
        scrape_data['ai_processing'] = True
        scrape_data['ai_prompt'] = user_message
    
    # Send to n8n if configured
    if n8n_connector:
        await update.message.reply_text("📤 Sending data to n8n workflow...")
        try:
            response = await n8n_connector.send_to_n8n(scrape_data)
            await update.message.reply_text(
                "✅ Data successfully sent to n8n!\n"
                f"Response: {response.get('message', 'Processing complete')}"
            )
        except Exception as e:
            logger.error(f"Error sending to n8n: {e}")
            await update.message.reply_text(
                "⚠️ Error sending to n8n workflow. Data has been logged locally."
            )
    else:
        # Log locally if n8n not configured
        logger.info(f"Scrape data (n8n not configured): {json.dumps(scrape_data, indent=2)}")
        await update.message.reply_text(
            "✅ Scrape complete! (n8n webhook not configured - data logged locally)"
        )
    
    # Clear user data
    context.user_data.clear()

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    help_text = """
🤖 **Reddit Scraper Bot**

**Available Commands:**
📊 `/scrape [subreddit] [limit] [sort] [time]`
Scrape Reddit posts and optionally rewrite titles with AI

**Parameters:**
• `subreddit`: Name of the subreddit (without r/)
• `limit`: Number of posts (1-50)
• `sort`: hot, new, top, rising
• `time`: hour, day, week, month, year, all (for top posts)

**Example:**
`/scrape python 10 top week`

This will fetch the top 10 posts from r/python over the past week.

After scraping, you can provide AI instructions to rewrite the titles or type 'skip' to keep originals.
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Welcome {user_name}!\n\n"
        "I'm a Reddit scraper bot that can fetch post titles and send them to n8n workflows.\n\n"
        "Use /help to see available commands."
    )

def main() -> None:
    """Start the bot"""
    # Validate environment variables
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        logger.error("Reddit API credentials not set!")
        return
    
    if not N8N_WEBHOOK_URL:
        logger.warning("N8N_WEBHOOK_URL not set - will log data locally only")
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("scrape", scrape_command))
    
    # Add message handler for AI prompts
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_ai_prompt
    ))
    
    # Start the bot
    logger.info("Starting Reddit Scraper Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
