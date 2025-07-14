import os
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import json
from typing import Dict, List
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
REDDIT_API_URL = os.getenv('REDDIT_API_URL', 'https://reddit-scraper-api-yp5t.onrender.com')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')
ALLOWED_USERS = os.getenv('ALLOWED_USERS', '').split(',')

class RedditAPIConnector:
    """Connect to your existing Reddit API on Render"""
    def __init__(self, api_url: str):
        self.api_url = api_url
        
    async def scrape_subreddit(
        self, 
        subreddit: str, 
        limit: int = 10, 
        sort: str = 'hot',
        time: str = 'week'
    ) -> Dict:
        """Call your existing Reddit API"""
        endpoint = f"{self.api_url}/api/scrape-simple"
        
        async with aiohttp.ClientSession() as session:
            try:
                # Your API expects empty body based on logs
                async with session.post(
                    endpoint,
                    json={},  # Empty as per your logs
                    params={
                        'subreddit': subreddit,
                        'limit': limit,
                        'sort': sort,
                        'time': time
                    }
                ) as response:
                    return await response.json()
            except Exception as e:
                logger.error(f"Error calling Reddit API: {e}")
                raise

class N8NConnector:
    """Send data to n8n webhook"""
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        
    async def send_to_n8n(self, data: Dict) -> Dict:
        """Send scraped data to n8n"""
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

# Initialize connectors
reddit_api = RedditAPIConnector(REDDIT_API_URL)
n8n_connector = N8NConnector(N8N_WEBHOOK_URL) if N8N_WEBHOOK_URL else None

async def check_access(user_id: int) -> bool:
    """Check if user has access"""
    if not ALLOWED_USERS or ALLOWED_USERS == ['']:
        return True
    return str(user_id) in ALLOWED_USERS

async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scrape command"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check access
    if not await check_access(user_id):
        await update.message.reply_text(
            "❌ Access denied. Please contact @panagiotis_krb to request access."
        )
        return
    
    # Parse arguments
    args = context.args
    if len(args) < 4:
        await update.message.reply_text(
            "🤔 I need more info to scrape Reddit!\n\n"
            "💡 Try: `/scrape python 10 top week`\n\n"
            "Format: /scrape [subreddit] [limit] [sort] [time_filter]",
            parse_mode='Markdown'
        )
        return
    
    subreddit = args[0]
    try:
        limit = min(int(args[1]), 50)
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Use 1-50.")
        return
        
    sort_type = args[2].lower()
    time_filter = args[3].lower()
    
    # Send initial message
    await update.message.reply_text(
        f"🔍 <b>Scraping r/{subreddit}...</b>\n"
        f"📊 Fetching {limit} {sort_type} posts...",
        parse_mode='HTML'
    )
    
    try:
        # Call your Reddit API
        result = await reddit_api.scrape_subreddit(
            subreddit=subreddit,
            limit=limit,
            sort=sort_type,
            time=time_filter
        )
        
        # Extract posts from response
        posts = result.get('posts', [])
        
        if not posts:
            await update.message.reply_text(
                f"❌ No posts found in r/{subreddit}"
            )
            return
        
        # Show preview
        preview = "✅ <b>Successfully scraped!</b>\n\n<b>Preview:</b>\n"
        for i, post in enumerate(posts[:5]):
            title = post.get('title', 'No title')
            preview += f"{i+1}. {title[:80]}{'...' if len(title) > 80 else ''}\n"
        
        if len(posts) > 5:
            preview += f"\n<i>...and {len(posts) - 5} more posts</i>"
            
        await update.message.reply_text(preview, parse_mode='HTML')
        
        # Ask about AI processing
        await update.message.reply_text(
            "🤖 Would you like to rewrite these titles with AI?\n\n"
            "Reply with instructions (e.g., 'Make them more clickbait')\n"
            "or type 'skip' to keep originals."
        )
        
        # Store data for next message
        context.user_data['pending_scrape'] = {
            'telegram_id': user_id,
            'chat_id': chat_id,
            'subreddit': subreddit,
            'posts': posts,
            'metadata': {
                'sort_type': sort_type,
                'time_filter': time_filter,
                'count': len(posts),
                'timestamp': datetime.utcnow().isoformat()
            }
        }
        context.user_data['awaiting_ai_prompt'] = True
        
    except Exception as e:
        logger.error(f"Scrape error: {e}")
        await update.message.reply_text(
            f"❌ Error scraping r/{subreddit}\n"
            "Please try again later."
        )

async def handle_ai_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle AI prompt response"""
    if not context.user_data.get('awaiting_ai_prompt'):
        return
    
    user_message = update.message.text.strip()
    scrape_data = context.user_data.get('pending_scrape')
    
    if not scrape_data:
        return
    
    context.user_data['awaiting_ai_prompt'] = False
    
    # Prepare data for n8n
    if user_message.lower() == 'skip':
        scrape_data['ai_processing'] = False
    else:
        scrape_data['ai_processing'] = True
        scrape_data['ai_prompt'] = user_message
    
    # Send to n8n
    if n8n_connector:
        await update.message.reply_text("📤 Sending to n8n workflow...")
        try:
            response = await n8n_connector.send_to_n8n(scrape_data)
            await update.message.reply_text(
                f"✅ {response.get('message', 'Processing complete!')}"
            )
        except Exception as e:
            logger.error(f"n8n error: {e}")
            await update.message.reply_text(
                "⚠️ Error sending to n8n. Data saved locally."
            )
    else:
        # Just log if n8n not configured
        logger.info(f"Scrape data: {json.dumps(scrape_data, indent=2)}")
        await update.message.reply_text(
            "✅ Data processed! (n8n not configured)"
        )
    
    context.user_data.clear()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start"""
    await update.message.reply_text(
        "👋 Welcome to Reddit Scraper!\n\n"
        "Use /scrape to fetch Reddit posts.\n"
        "Example: `/scrape python 10 top week`",
        parse_mode='Markdown'
    )

def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    # Create application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_ai_prompt
    ))
    
    # Run bot
    logger.info("Starting bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
