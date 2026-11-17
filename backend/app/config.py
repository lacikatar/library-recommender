from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Laci's Library"
    database_url: str = f"sqlite:///{BACKEND_DIR / 'library.db'}"
    catalogue_path: Path = BACKEND_DIR / "data" / "catalogue.json"
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    # Sessions. Set SECRET_KEY to a long random string anywhere but your laptop.
    secret_key: str = "dev-only-secret-change-me-before-you-deploy-this"
    session_days: int = 14
    cookie_secure: bool = False

    # Lending rules
    loan_days: int = 21
    max_active_loans: int = 5

    # Demo data created on first start
    seed_demo_data: bool = True

    # Optional LLM layer for the librarian. Leave the key empty to run without it.
    llm_provider: str = "anthropic"  # "anthropic" or "openai"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 20.0

    # Catalogue sync: new books from Open Library, gaps filled from Google Books.
    # 0 turns the schedule off; `python -m app.sync` still works by hand.
    sync_interval_hours: float = 0
    sync_subjects: str = (
        "fantasy,romance,mystery,thriller,science fiction,"
        "young adult fiction,historical fiction,horror"
    )
    sync_per_subject: int = 3  # new books per subject per run
    sync_since_years: int = 3  # only books first published in the last N years
    # Open Library asks apps to identify themselves; with an email you get 3x the rate limit.
    sync_contact_email: str = ""
    google_books_api_key: str = ""  # optional; works without one at low volume

    @property
    def sync_subject_list(self) -> list[str]:
        return [s.strip() for s in self.sync_subjects.split(",") if s.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
