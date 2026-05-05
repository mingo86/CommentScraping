"""
Config - Gestione configurazione da file JSON o env vars.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    # Piattaforme da monitorare
    platforms: list[str] = field(default_factory=lambda: ["instagram", "facebook", "tiktok", "youtube"])

    # Scraping
    headless: bool = True
    proxy: Optional[str] = None              # es. "http://user:pass@host:port"
    max_comments_per_post: int = 20000
    scroll_pause_ms: int = 1500

    # Classifier
    use_llm: bool = True
    anthropic_api_key: Optional[str] = None
    keywords_path: str = "keywords.json"

    # YouTube Data API (opzionale)
    youtube_api_key: Optional[str] = None

    # Output
    output_dir: str = "output"
    screenshots_dir: str = "screenshots"
    db_path: str = "monitor.db"

    @classmethod
    def from_file(cls, path: str) -> "Config":
        cfg = cls()
        if Path(path).exists():
            with open(path) as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)

        # Override da env vars
        if key := os.getenv("ANTHROPIC_API_KEY"):
            cfg.anthropic_api_key = key
        if key := os.getenv("YOUTUBE_API_KEY"):
            cfg.youtube_api_key = key
        if proxy := os.getenv("SCRAPER_PROXY"):
            cfg.proxy = proxy

        return cfg

    def to_file(self, path: str):
        import dataclasses
        with open(path, "w") as f:
            json.dump(dataclasses.asdict(self), f, indent=2)
