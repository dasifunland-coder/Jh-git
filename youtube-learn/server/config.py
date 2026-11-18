"""환경 변수로 서버 설정을 읽는다. (.env 파일이 있으면 같이 읽음)"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    openai_api_key: str
    claude_model: str
    stt_model: str
    stt_chunk_seconds: int
    max_stt_minutes: int
    app_token: str
    allowed_origins: list[str]
    yt_proxy_url: str
    ytdlp_cookies: str


def load_settings() -> Settings:
    _load_dotenv(Path(__file__).with_name(".env"))
    env = os.environ.get
    return Settings(
        anthropic_api_key=env("ANTHROPIC_API_KEY", ""),
        openai_api_key=env("OPENAI_API_KEY", ""),
        claude_model=env("CLAUDE_MODEL", "claude-opus-5-5"),
        stt_model=env("STT_MODEL", "gpt-transcribe"),
        stt_chunk_seconds=int(env("STT_CHUNK_SECONDS", "180")),
        max_stt_minutes=int(env("MAX_STT_MINUTES", "90")),
        app_token=env("APP_TOKEN", ""),
        allowed_origins=[o.strip() for o in env("ALLOWED_ORIGINS", "").split(",") if o.strip()],
        yt_proxy_url=env("YT_PROXY_URL", ""),
        ytdlp_cookies=env("YTDLP_COOKIES", ""),
    )
