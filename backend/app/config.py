from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
FIXTURES_DIR = ROOT / "fixtures"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Intent Radar"
    database_url: str = f"sqlite:///{DATA_DIR / 'radar.db'}"
    searxng_url: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_url: str = "https://api.openai.com/v1"
    musespark_api_key: str = Field(default="", validation_alias=AliasChoices("MUSESPARK_API_KEY", "MODEL_API_KEY"))
    musespark_model: str = "muse-spark-1.2"
    musespark_url: str = "https://api.meta.ai/v1"
    default_country: str = "India"
    crawl_timeout_seconds: float = 12.0
    user_agent: str = "IntentRadar/0.1 (+https://localhost; sales-intelligence; respects robots.txt)"
    demo_mode: bool = False
    seed_demo_data: bool = False
    scan_max_pages: int = 5000
    scan_result_limit: int = 12
    scan_query_limit: int = 250
    crawl_delay_seconds: float = 0.4
    scan_interval_minutes: int = 240
    reddit_subreddits: str = "influencermarketing"
    reddit_watch_minutes: int = 15
    redis_url: str = "redis://127.0.0.1:6379/0"
    queue_database_url: str = "postgresql+psycopg://radar:radar@127.0.0.1:5433/radar"
    search_concurrency: int = 1000
    ingest_concurrency: int = 1000


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
