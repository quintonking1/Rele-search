"""Settings loaded from .env (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    api_key: str
    embedding_model: str
    embedding_dim: int
    generation_model: str
    retrieval_model: str
    temperature: float
    top_k: int
    complaints_path: Path
    changelog_path: Path
    store_path: Path
    runs_dir: Path
    include_dates: bool


def load_config() -> Config:
    generation_model = os.getenv("GENERATION_MODEL", "gemini-3.6-flash")
    return Config(
        api_key=os.getenv("GOOGLE_API_KEY", ""),
        embedding_model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-2"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "768")),
        generation_model=generation_model,
        retrieval_model=os.getenv("RETRIEVAL_MODEL") or generation_model,
        temperature=float(os.getenv("GENERATION_TEMPERATURE", "0.0")),
        top_k=int(os.getenv("TOP_K", "8")),
        complaints_path=ROOT / os.getenv("COMPLAINTS_PATH", "data/tessera_complaints.json"),
        changelog_path=ROOT / os.getenv("CHANGELOG_PATH", "data/tessera_changelog.json"),
        store_path=ROOT / os.getenv("STORE_PATH", "data/store.json"),
        runs_dir=ROOT / os.getenv("RUNS_DIR", "runs"),
        include_dates=_bool(os.getenv("INCLUDE_DATES_IN_PROMPT", "true")),
    )
