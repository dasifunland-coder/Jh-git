"""외부 API 없이 돌아가는 테스트. 유튜브·OpenAI·Claude 호출은 가짜로 바꾼다."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import app as app_mod  # noqa: E402
import course  # noqa: E402
import transcript as tr  # noqa: E402
from config import Settings  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def settings(**kw):
    base = dict(
        anthropic_api_key="test", openai_api_key="sk-test", claude_model="claude-opus-5-5",
        stt_model="gpt-transcribe", stt_chunk_seconds=60, max_stt_minutes=90, app_token="",
        allowed_origins=[], yt_proxy_url="", ytdlp_cookies="",
    )
    base.update(kw)
    return Settings(**base)


# ------------------------------------------------------------- 링크·형식

@pytest.mark.parametrize("url,vid", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://example.com/watch?v=dQw4w9WgXcQ", None),
    ("not a url", None),
])
def test_parse_video_id(url, vid):
    assert tr.parse_video_id(url) == vid


def test_join_lines_groups_by_20s():
    pieces = [(0, "안녕"), (5, "하세요"), (21, "오늘은"), (30, "복리"), (3700, "끝")]
    out = tr.join_lines(pieces).splitlines()
    assert out == ["0:00 안녕 하세요", "0:21 오늘은 복리", "1:01:40 끝"]
    assert tr.fmt_time(3700) == "1:01:40"


# ------------------------------------------------------------- 자막

class FakeTranscript:
    def __init__(self, lang, generated, snippets):
        self.language_code, self.is_generated, self._s = lang, generated, snippets

    def fetch(self):
        return [SimpleNamespace(start=t, text=x, duration=1) for t, x in self._s]


def test_captions_prefers_manual_korean(monkeypatch):
    items = [
        FakeTranscript("en", False, [(0, "english manual")]),
        FakeTranscript("ko", True, [(0, "한국어 자동")]),
        FakeTranscript("ko", False, [(0, "한국어 수동")]),
    ]

    class FakeApi:
        def __init__(self, proxy_config=None):
            pass

        def list(self, vid):
            return iter(items)

    monkeypatch.setattr(tr, "YouTubeTranscriptApi", FakeApi)
    text, lang = tr.fetch_captions("dQw4w9WgXcQ", settings())
    assert lang == "ko" and "한국어 수동" in text


def test_captions_disabled_returns_none(monkeypatch):
    class FakeApi:
        def __init__(self, proxy_config=None):
            pass

        def list(self, vid):
            raise tr.TranscriptsDisabled(vid)

    monkeypatch.setattr(tr, "YouTubeTranscriptApi", FakeApi)
    assert tr.fetch_captions("dQw4w9WgXcQ", settings()) is None


def test_captions_network_error_is_clear(monkeypatch):
    import requests

    class FakeApi:
        def __init__(self, proxy_config=None):
            pass

        def list(self, vid):
            raise requests.exceptions.ProxyError("blocked")

    monkeypatch.setattr(tr, "YouTubeTranscriptApi", FakeApi)
    with pytest.raises(tr.TranscriptError, match="유튜브에 연결하지 못했어요"):
        tr.fetch_captions("dQw4w9WgXcQ", settings())


# ------------------------------------------------------------- 음성 인식 경로

async def test_falls_back_to_stt(monkeypatch):
    monkeypatch.setattr(tr, "fetch_meta", lambda vid, s: tr.VideoMeta(vid, title="t", duration=300))
    monkeypatch.setattr(tr, "fetch_captions", lambda vid, s: None)
    monkeypatch.setattr(tr, "download_audio_chunks", lambda vid, wd, s: ["a.mp3", "b.mp3"])

    async def fake_tx(chunks, s, progress=None):
        return "0:00 첫 조각\n1:00 둘째 조각"

    monkeypatch.setattr(tr, "transcribe_chunks", fake_tx)
    stages = []

    async def prog(stage, msg):
        stages.append(stage)

    res = await tr.get_transcript("dQw4w9WgXcQ", settings(), prog)
    assert res.source == "stt" and "둘째" in res.text
    assert stages == ["meta", "captions", "stt"]


async def test_no_openai_key_gives_clear_error(monkeypatch):
    monkeypatch.setattr(tr, "fetch_meta", lambda vid, s: tr.VideoMeta(vid))
    monkeypatch.setattr(tr, "fetch_captions", lambda vid, s: None)
    with pytest.raises(tr.TranscriptError, match="OPENAI_API_KEY"):
        await tr.get_transcript("dQw4w9WgXcQ", settings(openai_api_key=""))


async def test_too_long_for_stt(monkeypatch):
    monkeypatch.setattr(tr, "fetch_meta", lambda vid, s: tr.VideoMeta(vid, duration=200 * 60))
    monkeypatch.setattr(tr, "fetch_captions", lambda vid, s: None)
    with pytest.raises(tr.TranscriptError, match="90분"):
        await tr.get_transcript("dQw4w9WgXcQ", settings())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 필요")
def test_download_audio_chunks_splits_with_ffmpeg(monkeypatch, tmp_path):
    """yt-dlp만 가짜로 바꾸고, ffmpeg 분할은 실제로 실행한다."""
    import yt_dlp

    class FakeYDL:
        def __init__(self, opts):
            self.out = opts["outtmpl"].replace("%(ext)s", "m4a")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=150",
                            "-c:a", "aac", self.out], check=True)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    chunks = tr.download_audio_chunks("dQw4w9WgXcQ", str(tmp_path), settings(stt_chunk_seconds=60))
    assert len(chunks) == 3 and all(c.endswith(".mp3") for c in chunks)


async def test_transcribe_chunks_offsets(monkeypatch, tmp_path):
    files = []
    for i in range(3):
        p = tmp_path / f"c{i}.mp3"
        p.write_bytes(b"x")
        files.append(str(p))

    calls = []

    class FakeTx:
        async def create(self, **kw):
            calls.append(kw)
            name = Path(kw["file"].name).stem
            if kw["response_format"] == "verbose_json":
                return SimpleNamespace(text="", segments=[SimpleNamespace(start=5, text=f"{name} 문장")])
            return SimpleNamespace(text=f"{name} 내용")

    class FakeOpenAI:
        def __init__(self, api_key):
            self.audio = SimpleNamespace(transcriptions=FakeTx())

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)

    out = await tr.transcribe_chunks(files, settings(stt_chunk_seconds=60))
    assert out.splitlines() == ["0:00 c0 내용", "1:00 c1 내용", "2:00 c2 내용"]
    assert calls[0]["model"] == "gpt-transcribe"

    out = await tr.transcribe_chunks(files, settings(stt_chunk_seconds=60, stt_model="whisper-1"))
    assert out.splitlines()[0].startswith("0:05 c0 문장")
    assert "1:05 c1 문장" in out


# ------------------------------------------------------------- HTTP 엔드포인트

COURSE = {"title": "복리", "one_liner": "x", "difficulty": "입문", "estimated_minutes": 15, "summary": [],
          "chapters": [], "concepts": [], "lesson_path": [], "flashcards": [], "quiz": [], "related": [], "caveats": []}


@pytest.fixture
def client(monkeypatch):
    seen = {}

    async def fake_get(vid, s, progress=None):
        await progress("captions", "자막 찾는 중")
        return tr.TranscriptResult(text="0:00 내용", source="captions", meta=tr.VideoMeta(vid, title="영상"))

    async def fake_build(s, prompt, on_progress=None):
        seen["prompt"] = prompt
        await on_progress(10)
        return COURSE

    monkeypatch.setattr(tr, "get_transcript", fake_get)
    monkeypatch.setattr(tr, "fetch_meta", lambda vid, s: tr.VideoMeta(vid, title="메타 제목"))
    monkeypatch.setattr(course, "build_course", fake_build)
    c = TestClient(app_mod.app)
    c.seen = seen
    return c


def events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_analyze_from_url(client):
    r = client.post("/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ", "level": "중급", "minutes": 5})
    ev = events(r)
    assert [e["type"] for e in ev] == ["stage", "stage", "progress", "result"]
    res = ev[-1]
    assert res["data"]["title"] == "복리" and res["source"] == "captions" and res["videoId"] == "dQw4w9WgXcQ"
    assert "학습자 수준: 중급" in client.seen["prompt"] and "영상 제목: 영상" in client.seen["prompt"]


def test_analyze_pasted_transcript_uses_meta(client):
    r = client.post("/api/analyze", json={"url": "https://youtu.be/dQw4w9WgXcQ", "transcript": "0:00 붙여넣음"})
    res = events(r)[-1]
    assert res["source"] == "pasted" and "붙여넣음" in client.seen["prompt"] and "메타 제목" in client.seen["prompt"]


def test_analyze_validation(client):
    assert client.post("/api/analyze", json={}).status_code == 400
    assert client.post("/api/analyze", json={"url": "https://example.com"}).status_code == 400
    assert client.post("/api/analyze", json={"url": "dQw4w9WgXcQ", "minutes": 7}).status_code == 422


def test_analyze_error_event(client, monkeypatch):
    async def boom(vid, s, progress=None):
        raise tr.TranscriptError("자막이 없어요")

    monkeypatch.setattr(tr, "get_transcript", boom)
    ev = events(client.post("/api/analyze", json={"url": "dQw4w9WgXcQ"}))
    assert ev[-1] == {"type": "error", "message": "자막이 없어요"}


def test_token_required(client, monkeypatch):
    monkeypatch.setattr(app_mod, "settings", settings(app_token="secret"))
    assert client.post("/api/analyze", json={"url": "dQw4w9WgXcQ"}).status_code == 401
    ok = client.post("/api/analyze", json={"url": "dQw4w9WgXcQ"}, headers={"X-App-Token": "secret"})
    assert ok.status_code == 200
    assert client.get("/api/health").json()["needs_token"] is True


def test_ask_streams(client, monkeypatch):
    got = {}

    async def fake_stream(s, system, messages):
        got["messages"], got["system"] = messages, system
        for t in ["안녕", "하세요"]:
            yield t

    monkeypatch.setattr(course, "tutor_stream", fake_stream)
    r = client.post("/api/ask", json={"title": "복리", "transcript": "0:00 내용", "question": "뭐야?",
                                       "history": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]})
    assert r.text == "안녕하세요"
    assert got["messages"][-1] == {"role": "user", "content": "뭐야?"} and len(got["messages"]) == 3
    assert got["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "클립러닝" in r.text


def test_pwa_files_served(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/manifest+json")
    man = m.json()
    assert man["display"] == "standalone" and man["share_target"]["params"]["text"] == "text"
    for icon in man["icons"]:
        assert client.get("/" + icon["src"]).status_code == 200
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]


def test_course_schema_is_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(course.COURSE_SCHEMA)
