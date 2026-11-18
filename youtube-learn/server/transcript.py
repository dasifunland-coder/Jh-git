"""유튜브 영상의 스크립트를 가져온다.

1순위: 유튜브 자막 (사람이 만든 자막 > 자동 생성 자막). 무료이고 빠르다.
2순위: 자막이 없으면 yt-dlp로 오디오만 받아 OpenAI 음성 인식으로 받아 적는다.
"""
from __future__ import annotations

import asyncio
import glob
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import requests
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from config import Settings

PREFERRED_LANGS = ["ko", "en"]
ID_RE = re.compile(r"^[\w-]{11}$")

Progress = Callable[[str, str], Awaitable[None]]


class TranscriptError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 한국어 메시지를 담는다."""


@dataclass
class VideoMeta:
    video_id: str
    title: str = ""
    channel: str = ""
    duration: int = 0  # 초
    description: str = ""


@dataclass
class TranscriptResult:
    text: str
    source: str  # "captions" | "stt"
    language: str = ""
    meta: VideoMeta | None = None
    notes: list[str] = field(default_factory=list)


def parse_video_id(url: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    s = (url or "").strip()
    if ID_RE.match(s):
        return s
    try:
        u = urlparse(s)
    except ValueError:
        return None
    host = (u.hostname or "").removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        vid = u.path.lstrip("/")[:11]
        return vid if ID_RE.match(vid) else None
    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        v = parse_qs(u.query).get("v", [""])[0][:11]
        if ID_RE.match(v):
            return v
        m = re.search(r"/(shorts|embed|live|v)/([\w-]{11})", u.path)
        if m:
            return m.group(2)
    return None


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def join_lines(pieces: list[tuple[float, str]], every: float = 20.0) -> str:
    """(시작 초, 문장) 목록을 약 20초 단위 줄로 묶어 '0:00 내용' 형태로 만든다."""
    lines: list[str] = []
    buf: list[str] = []
    start = None
    for t, txt in pieces:
        txt = " ".join(txt.split())
        if not txt:
            continue
        if start is not None and t - start >= every:
            lines.append(f"{fmt_time(start)} {' '.join(buf)}")
            buf, start = [], None
        if start is None:
            start = t
        buf.append(txt)
    if buf and start is not None:
        lines.append(f"{fmt_time(start)} {' '.join(buf)}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 영상 정보

def _ydl_opts(settings: Settings, **extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    if settings.yt_proxy_url:
        opts["proxy"] = settings.yt_proxy_url
    if settings.ytdlp_cookies:
        opts["cookiefile"] = settings.ytdlp_cookies
    opts.update(extra)
    return opts


def fetch_meta(video_id: str, settings: Settings) -> VideoMeta:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ydl_opts(settings)) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception:  # 영상 정보는 없어도 진행할 수 있다
        return VideoMeta(video_id=video_id)
    return VideoMeta(
        video_id=video_id,
        title=info.get("title") or "",
        channel=info.get("channel") or info.get("uploader") or "",
        duration=int(info.get("duration") or 0),
        description=(info.get("description") or "")[:3000],
    )


# ---------------------------------------------------------------- 1순위: 자막

def fetch_captions(video_id: str, settings: Settings) -> tuple[str, str] | None:
    """자막이 있으면 (스크립트, 언어 코드), 없으면 None."""
    proxy = None
    if settings.yt_proxy_url:
        proxy = GenericProxyConfig(http_url=settings.yt_proxy_url, https_url=settings.yt_proxy_url)
    api = YouTubeTranscriptApi(proxy_config=proxy)
    try:
        tlist = api.list(video_id)
    except requests.RequestException as e:
        raise TranscriptError(
            "서버가 유튜브에 연결하지 못했어요. 서버의 인터넷 연결이나 프록시 설정(YT_PROXY_URL)을 확인해 주세요."
        ) from e
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except CouldNotRetrieveTranscript as e:
        # IP 차단·연령 제한 등: 음성 인식으로 넘어가 본다
        name = type(e).__name__
        if name in ("IpBlocked", "RequestBlocked"):
            return None
        if name in ("VideoUnavailable", "InvalidVideoId"):
            raise TranscriptError("영상을 찾을 수 없어요. 링크를 확인해 주세요.") from e
        return None

    transcripts = list(tlist)
    if not transcripts:
        return None

    def rank(t) -> tuple[int, int]:
        lang = PREFERRED_LANGS.index(t.language_code) if t.language_code in PREFERRED_LANGS else len(PREFERRED_LANGS)
        return (1 if t.is_generated else 0, lang)

    best = sorted(transcripts, key=rank)[0]
    try:
        fetched = best.fetch()
    except requests.RequestException as e:
        raise TranscriptError("서버가 유튜브에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.") from e
    except CouldNotRetrieveTranscript:
        return None  # 자막 목록은 있지만 내려받기가 막힘: 음성 인식으로 넘어간다
    pieces = [(s.start, s.text) for s in fetched]
    text = join_lines(pieces)
    return (text, best.language_code) if text.strip() else None


# ---------------------------------------------------------------- 2순위: 음성 인식

def download_audio_chunks(video_id: str, workdir: str, settings: Settings) -> list[str]:
    """오디오를 받아 음성 인식용 작은 mp3 조각(모노 16kHz)으로 나눈다."""
    import yt_dlp

    if not shutil.which("ffmpeg"):
        raise TranscriptError("서버에 ffmpeg가 설치되어 있지 않아 음성 인식을 할 수 없어요.")
    opts = _ydl_opts(
        settings,
        skip_download=False,
        format="bestaudio/best",
        outtmpl=os.path.join(workdir, "source.%(ext)s"),
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except Exception as e:
        raise TranscriptError(
            "영상 오디오를 내려받지 못했어요. 유튜브가 서버 접속을 막았을 수 있어요. "
            "(README의 프록시·쿠키 설정 참고)"
        ) from e
    src = next(iter(glob.glob(os.path.join(workdir, "source.*"))), None)
    if not src:
        raise TranscriptError("영상 오디오를 내려받지 못했어요.")
    out = os.path.join(workdir, "chunk%04d.mp3")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", src,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        "-f", "segment", "-segment_time", str(settings.stt_chunk_seconds), "-reset_timestamps", "1", out,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise TranscriptError("오디오 변환에 실패했어요.")
    return sorted(glob.glob(os.path.join(workdir, "chunk*.mp3")))


async def transcribe_chunks(chunks: list[str], settings: Settings, progress: Progress | None = None) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.stt_model
    want_segments = model == "whisper-1"  # 문장 단위 타임스탬프는 whisper-1만 돌려준다
    sem = asyncio.Semaphore(4)
    done = 0

    async def one(i: int, path: str) -> list[tuple[float, str]]:
        nonlocal done
        offset = i * settings.stt_chunk_seconds
        async with sem:
            with open(path, "rb") as f:
                if want_segments:
                    r = await client.audio.transcriptions.create(
                        model=model, file=f, response_format="verbose_json", timestamp_granularities=["segment"],
                    )
                    pieces = [(offset + s.start, s.text) for s in (r.segments or [])] or [(offset, r.text)]
                else:
                    r = await client.audio.transcriptions.create(model=model, file=f, response_format="json")
                    pieces = [(offset, r.text)]
        done += 1
        if progress:
            await progress("stt", f"음성 인식 중… ({done}/{len(chunks)})")
        return pieces

    results = await asyncio.gather(*(one(i, p) for i, p in enumerate(chunks)))
    pieces = [p for chunk in results for p in chunk]
    # 조각 단위 타임스탬프뿐이면 조각마다 한 줄, 문장 단위면 20초 단위로 묶는다
    return join_lines(pieces, every=20.0 if want_segments else 0.0)


# ---------------------------------------------------------------- 전체 흐름

async def get_transcript(video_id: str, settings: Settings, progress: Progress | None = None) -> TranscriptResult:
    async def say(stage: str, msg: str):
        if progress:
            await progress(stage, msg)

    await say("meta", "영상 정보를 확인하고 있어요")
    meta = await asyncio.to_thread(fetch_meta, video_id, settings)

    await say("captions", "유튜브 자막을 찾고 있어요")
    caps = await asyncio.to_thread(fetch_captions, video_id, settings)
    if caps:
        text, lang = caps
        return TranscriptResult(text=text, source="captions", language=lang, meta=meta)

    if not settings.openai_api_key:
        raise TranscriptError(
            "이 영상에는 자막이 없어요. 음성 인식을 쓰려면 서버에 OPENAI_API_KEY를 설정하거나, 스크립트를 직접 붙여넣어 주세요."
        )
    if meta.duration and meta.duration > settings.max_stt_minutes * 60:
        raise TranscriptError(
            f"자막이 없는 {meta.duration // 60}분짜리 영상이에요. 음성 인식은 {settings.max_stt_minutes}분 이하 영상만 지원해요."
        )

    await say("stt", "자막이 없어 음성을 받아 적고 있어요")
    workdir = tempfile.mkdtemp(prefix="cliplearn-")
    try:
        chunks = await asyncio.to_thread(download_audio_chunks, video_id, workdir, settings)
        if not chunks:
            raise TranscriptError("영상에서 오디오를 찾지 못했어요.")
        text = await transcribe_chunks(chunks, settings, progress)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if not text.strip():
        raise TranscriptError("음성에서 말소리를 찾지 못했어요.")
    notes = ["자막이 없어 음성 인식으로 만든 스크립트예요. 고유명사가 틀릴 수 있어요."]
    return TranscriptResult(text=text, source="stt", meta=meta, notes=notes)
