from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import json

@dataclass
class ScrapeRequest:
    subreddit: str
    limit: int = 10
    sort: str = "hot"
    time_filter: str = "week"
    telegram_id: int = 0
    personality_name: str = "default"
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)

@dataclass
class RedditPost:
    id: str
    title: str
    score: int
    url: str
    permalink: str
    created_utc: float
    author: Optional[str]
    subreddit: str
    
    def to_dict(self):
        return self.__dict__

@dataclass
class AIEnhancedPost:
    id: str
    title: str
    score: int
    url: str
    permalink: str
    created_utc: float
    author: Optional[str]
    subreddit: str
    original_title: str
    ai_title: str
    personality_used: str
    
    def to_dict(self):
        return self.__dict__

@dataclass
class ScrapeResponse:
    task_id: str
    status: str
    message: str
    telegram_id: int
    results: Optional[List[Dict[str, Any]]] = None
    
    def to_dict(self):
        return {
            "task_id": self.task_id,
            "status": self.status,
            "message": self.message,
            "telegram_id": self.telegram_id,
            "results": self.results
        }
