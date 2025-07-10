# Reddit Scraper API with Telegram Bot Integration

A FastAPI-based service that scrapes Reddit posts and generates AI-enhanced titles using OpenAI. Designed to work with n8n workflows and Telegram bots.

## Features

- 🤖 **AI-Powered Title Generation**: Uses OpenAI GPT-3.5 to create engaging titles
- 📱 **Telegram Bot Integration**: Full command-based interface via n8n workflows
- 🎭 **Multiple AI Personalities**: Users can create and manage different writing styles
- 🚀 **Fast & Async**: Built with FastAPI for high performance
- 🔒 **Secure**: API key authentication and environment-based configuration
- 📊 **PostgreSQL Database**: Persistent storage for users and personalities

## Tech Stack

- **Backend**: FastAPI, Python 3.9+
- **Database**: PostgreSQL
- **APIs**: Reddit (PRAW), OpenAI
- **Deployment**: Render.com
- **Workflow**: n8n
- **Frontend**: Telegram Bot

## Commands

- `/start` - Welcome message
- `/help` - Show available commands
- `/scrape [subreddit] [limit] [sort] [time] [personality]` - Scrape Reddit posts
  - Example: `/scrape python 10 top week funny`
- `/personalities` - List your AI personalities
- `/addpersonality [name] "description" "prompt"` - Add new personality

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/reddit-scraper-api.git
cd reddit-scraper-api
