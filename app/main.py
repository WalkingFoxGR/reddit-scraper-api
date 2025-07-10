from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .routers import scraper_simple

app = FastAPI(
    title="Reddit Scraper API",
    description="API for scraping Reddit posts and generating AI-enhanced titles",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(scraper_simple.router)

@app.get("/")
async def root():
    return {
        "message": "Reddit Scraper API",
        "docs": "/docs",
        "health": "/api/health"
    }
