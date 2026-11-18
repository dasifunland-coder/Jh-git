"""클립러닝 서버.

- GET  /             앱 화면 (../index.html)
- GET  /api/health   서버 상태와 사용 가능한 기능
- POST /api/analyze  링크 → (자막 또는 음성 인식) → Claude 학습 코스. 진행 상황을 NDJSON으로 흘려보낸다.
- POST /api/ask      AI 튜터 답변을 글자 단위로 흘려보낸다.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import course
import transcript as tr
from config import load_settings

log = logging.getLogger("cliplearn")
settings = load_settings()
APP_HTML = Path(__file__).resolve().parent.parent / "index.html"
MAX_TRANSCRIPT_CHARS = 600_000

app = FastAPI(title="ClipLearn", docs_url=None, redoc_url=None)
if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-App-Token"],
    )


def check_token(x_app_token: str = Header(default="")) -> None:
    if settings.app_token and not hmac.compare_digest(x_app_token, settings.app_token):
        raise HTTPException(status_code=401, detail="접속 암호가 맞지 않아요.")


@app.get("/")
def index():
    return FileResponse(APP_HTML, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "server": True,
        "stt": bool(settings.openai_api_key),
        "stt_model": settings.stt_model if settings.openai_api_key else None,
        "max_stt_minutes": settings.max_stt_minutes,
        "needs_token": bool(settings.app_token),
    }


class AnalyzeIn(BaseModel):
    url: str = ""
    transcript: str = Field(default="", max_length=MAX_TRANSCRIPT_CHARS)
    level: Literal["입문", "중급", "고급"] = "입문"
    minutes: Literal[5, 15, 30] = 15


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


@app.post("/api/analyze", dependencies=[Depends(check_token)])
async def analyze(body: AnalyzeIn):
    video_id = tr.parse_video_id(body.url) if body.url else None
    pasted = body.transcript.strip()
    if body.url and not video_id:
        raise HTTPException(400, "유튜브 링크 형식이 아니에요.")
    if not video_id and not pasted:
        raise HTTPException(400, "유튜브 링크나 스크립트 중 하나는 넣어 주세요.")

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def stage(name: str, message: str):
        await queue.put(_line({"type": "stage", "stage": name, "message": message}))

    async def work():
        try:
            meta = tr.VideoMeta(video_id=video_id or "")
            notes: list[str] = []
            if pasted:
                source, text = "pasted", pasted
                if video_id:
                    await stage("meta", "영상 정보를 확인하고 있어요")
                    meta = await asyncio.to_thread(tr.fetch_meta, video_id, settings)
            else:
                res = await tr.get_transcript(video_id, settings, stage)
                source, text, notes = res.source, res.text, res.notes
                meta = res.meta or meta

            await stage("analyze", "내용을 분석해 학습 코스를 만들고 있어요")
            prompt = course.course_prompt(
                transcript=text, level=body.level, minutes=body.minutes,
                title=meta.title, channel=meta.channel, description=meta.description, source=source,
            )

            async def on_progress(chars: int):
                await queue.put(_line({"type": "progress", "chars": chars}))

            data = await course.build_course(settings, prompt, on_progress)
            await queue.put(_line({
                "type": "result", "data": data, "videoId": video_id, "source": source,
                "transcript": text, "notes": notes,
                "meta": {"title": meta.title, "channel": meta.channel, "duration": meta.duration},
            }))
        except (tr.TranscriptError, course.CourseError) as e:
            await queue.put(_line({"type": "error", "message": str(e)}))
        except Exception:
            log.exception("analyze failed")
            await queue.put(_line({"type": "error", "message": "서버에서 알 수 없는 오류가 났어요."}))
        finally:
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(work())
        try:
            while (item := await queue.get()) is not None:
                yield item
        finally:
            if not task.done():  # 사용자가 취소하면 작업도 멈춘다
                task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class ChatMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class AskIn(BaseModel):
    title: str = Field(default="", max_length=500)
    transcript: str = Field(max_length=MAX_TRANSCRIPT_CHARS)
    level: str = Field(default="입문", max_length=10)
    history: list[ChatMsg] = Field(default_factory=list, max_length=40)
    question: str = Field(min_length=1, max_length=4000)


@app.post("/api/ask", dependencies=[Depends(check_token)])
async def ask(body: AskIn):
    system = course.tutor_system(title=body.title, transcript=body.transcript, level=body.level)
    messages = [m.model_dump() for m in body.history] + [{"role": "user", "content": body.question}]
    gen = course.tutor_stream(settings, system=system, messages=messages)
    return StreamingResponse((t.encode("utf-8") async for t in gen), media_type="text/plain; charset=utf-8")


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
