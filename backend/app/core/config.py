"""Settings, read once from environment variables (backend/.env is loaded if present)."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    helpdesk_base_url: str
    helpdesk_key: str
    candidate_email: str
    candidate_name: str
    llm_provider: str
    llm_model: str
    llm_api_key: str
    reply_threshold: float
    max_post_attempts: int
    faq_path: Path
    data_dir: Path
    log_dir: Path
    state_db: Path

    @property
    def helpdesk_configured(self) -> bool:
        return bool(self.helpdesk_base_url and self.helpdesk_key and self.candidate_email)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_provider)


@lru_cache
def get_settings() -> Settings:
    env = os.environ.get
    return Settings(
        helpdesk_base_url=env("HELPDESK_BASE_URL", "").rstrip("/"),
        helpdesk_key=env("HELPDESK_KEY", ""),
        candidate_email=env("CANDIDATE_EMAIL", ""),
        candidate_name=env("CANDIDATE_NAME", ""),
        llm_provider=env("LLM_PROVIDER", "").strip().lower(),
        llm_model=env("LLM_MODEL", ""),
        llm_api_key=env("LLM_API_KEY", ""),
        reply_threshold=float(env("REPLY_CONFIDENCE_THRESHOLD", "0.70")),
        max_post_attempts=int(env("MAX_POST_ATTEMPTS", "3")),
        faq_path=Path(env("FAQ_PATH", str(REPO_ROOT / "faq.md"))),
        data_dir=BACKEND_DIR / "data",
        log_dir=Path(env("LOG_DIR", str(BACKEND_DIR / "logs"))),
        state_db=Path(env("STATE_DB", str(BACKEND_DIR / "state" / "journal.db"))),
    )


def make_helpdesk(settings: Settings | None = None):
    from app.clients.helpdesk import HelpdeskClient

    s = settings or get_settings()
    if not s.helpdesk_configured:
        raise RuntimeError("Missing HELPDESK_BASE_URL / HELPDESK_KEY / CANDIDATE_EMAIL (see .env.example)")
    return HelpdeskClient(s.helpdesk_base_url, s.helpdesk_key, s.candidate_email, s.candidate_name or None)
