#!/usr/bin/env python3
"""yt2claude — 유튜브 영상을 Claude가 바로 쓸 수 있는 지식 자료로 바꿔주는 도구.

사용 예:
    python yt2claude.py "https://youtu.be/VIDEO_ID"                 # 요약 + Skill 생성
    python yt2claude.py URL --format claude-md                      # CLAUDE.md 붙여넣기용
    python yt2claude.py URL --format project                        # Claude 프로젝트 지식 파일
    python yt2claude.py URL --format all                            # 세 가지 모두
    python yt2claude.py URL --transcript-only                       # API 키 없이 자막만 추출

출력은 기본적으로 ./output/<영상 제목>/ 아래에 저장됩니다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MODEL = "claude-opus-5-5"
DEFAULT_LANGS = ["ko", "en"]

# ---------------------------------------------------------------------------
# 1. 유튜브에서 정보 가져오기
# ---------------------------------------------------------------------------

_ID_PATTERNS = [
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})",
    r"^([A-Za-z0-9_-]{11})$",
]


def extract_video_id(url_or_id: str) -> str:
    s = url_or_id.strip()
    for pat in _ID_PATTERNS:
        m = re.search(pat, s)
        if m:
            return m.group(1)
    raise ValueError(f"유튜브 영상 ID를 찾을 수 없습니다: {url_or_id}")


def fetch_metadata(video_id: str) -> dict:
    """oEmbed로 제목/채널명을 가져온다 (API 키 불필요)."""
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
        f"https://www.youtube.com/watch?v={video_id}"
    )
    meta = {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": video_id, "channel": "알 수 없음"}
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
        meta["title"] = data.get("title", video_id)
        meta["channel"] = data.get("author_name", "알 수 없음")
    except Exception as e:  # 메타데이터는 없어도 진행 가능
        print(f"[경고] 영상 정보를 가져오지 못했습니다: {e}", file=sys.stderr)
    return meta


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fetch_transcript(video_id: str, languages: list[str]) -> tuple[str, str]:
    """자막을 가져와 '[mm:ss] 문장' 형태 텍스트와 언어 코드를 돌려준다.

    선호 언어 자막이 없으면 가능한 자막 아무거나(자동 생성 포함) 가져온다.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=languages)
    except Exception:
        transcripts = list(api.list(video_id))
        if not transcripts:
            raise RuntimeError("이 영상에는 사용할 수 있는 자막이 없습니다.")
        fetched = transcripts[0].fetch()

    # 약 30초 단위로 묶어서 타임스탬프를 남긴다 (토큰 절약 + 출처 표시)
    lines, buf, start = [], [], None
    for snip in fetched:
        text = snip.text.replace("\n", " ").strip()
        if not text:
            continue
        if start is None:
            start = snip.start
        buf.append(text)
        if snip.start - start >= 30:
            lines.append(f"[{fmt_ts(start)}] {' '.join(buf)}")
            buf, start = [], None
    if buf:
        lines.append(f"[{fmt_ts(start or 0)}] {' '.join(buf)}")
    return "\n".join(lines), fetched.language_code


# ---------------------------------------------------------------------------
# 2. Claude로 정리하기
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """당신은 영상 내용을 다른 AI 어시스턴트(Claude)가 참고 자료로 활용할 수 있도록 \
정리하는 지식 큐레이터입니다. 영상 자막(타임스탬프 포함)을 받아 정확하고 재사용 가능한 지식 문서로 바꿉니다.

원칙:
- 자막에 실제로 나온 내용만 씁니다. 추측이나 외부 지식은 넣지 않으며, 불확실하면 그렇다고 표시합니다.
- 핵심 주장·방법·수치·도구 이름·단계는 빠짐없이 구체적으로 남깁니다. 잡담과 광고는 버립니다.
- 중요한 내용에는 [mm:ss] 타임스탬프를 붙여 원문 위치를 알 수 있게 합니다.
- 자동 생성 자막의 오타는 문맥상 명확할 때만 바로잡습니다.
- 출력 언어: {lang}."""

USER_PROMPT = """아래 유튜브 영상 자막을 정리해 주세요.

제목: {title}
채널: {channel}
URL: {url}

<transcript>
{transcript}
</transcript>

다음 JSON 필드를 채워 주세요.
- skill_name: 이 지식을 Claude Skill로 만들 때 쓸 영문 소문자-하이픈 이름 (예: "react-performance-tips")
- skill_description: Claude가 언제 이 지식을 불러와야 하는지 알려주는 한두 문장 (무엇에 대한 것인지 + 어떤 요청일 때 쓰는지)
- one_line_summary: 영상 한 줄 요약
- knowledge_markdown: 마크다운 본문. 다음 섹션을 포함하세요:
  ## 개요 / ## 핵심 내용 (주제별 소제목, 타임스탬프 포함) / ## 실천 가이드 (따라 할 수 있는 단계·체크리스트, 해당될 때만) /
  ## 용어 및 도구 / ## 주의사항·한계 / ## Claude 적용 지침 (이 지식을 바탕으로 Claude가 답변하거나 작업할 때 따를 규칙을 "- ~한다" 형식으로)
- claude_md_rules: CLAUDE.md에 그대로 붙여넣을 짧은 규칙 목록 (마크다운 불릿 5~15개)"""

SCHEMA = {
    "type": "object",
    "properties": {
        "skill_name": {"type": "string"},
        "skill_description": {"type": "string"},
        "one_line_summary": {"type": "string"},
        "knowledge_markdown": {"type": "string"},
        "claude_md_rules": {"type": "string"},
    },
    "required": ["skill_name", "skill_description", "one_line_summary",
                 "knowledge_markdown", "claude_md_rules"],
    "additionalProperties": False,
}


def summarize_with_claude(meta: dict, transcript: str, out_lang: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        # 안전 분류기가 거절할 경우 서버가 다른 모델로 자동 재시도
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT.format(lang=out_lang),
        messages=[{"role": "user", "content": USER_PROMPT.format(transcript=transcript, **meta)}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 영상의 정리를 거절했습니다.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("출력이 너무 길어 잘렸습니다. 더 짧은 영상으로 시도해 주세요.")
    text = "".join(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# ---------------------------------------------------------------------------
# 3. Claude에 적용할 수 있는 형태로 저장
# ---------------------------------------------------------------------------

def slugify(s: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:64].strip("-")
    return s or fallback


def safe_dirname(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\n\r\t]+', "_", s).strip()[:80] or "video"


def source_block(meta: dict) -> str:
    return f"> 출처: [{meta['title']}]({meta['url']}) — {meta['channel']}\n"


def write_skill(out: Path, meta: dict, r: dict) -> Path:
    name = slugify(r["skill_name"], f"youtube-{meta['video_id'].lower()}")
    d = out / "skill" / name
    d.mkdir(parents=True, exist_ok=True)
    desc = r["skill_description"].replace("\n", " ").replace('"', "'")
    (d / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{desc}"\n---\n\n'
        f"# {meta['title']}\n\n{source_block(meta)}\n"
        f"**요약:** {r['one_line_summary']}\n\n{r['knowledge_markdown']}\n\n"
        "## 원문 자막\n더 자세한 내용이 필요하면 같은 폴더의 `transcript.md`를 읽는다.\n",
        encoding="utf-8",
    )
    return d


def write_outputs(out: Path, meta: dict, transcript: str, lang: str,
                  result: dict | None, fmt: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []

    transcript_md = (f"# {meta['title']} — 자막 ({lang})\n\n{source_block(meta)}\n{transcript}\n")
    t = out / "transcript.md"
    t.write_text(transcript_md, encoding="utf-8")
    written.append(t)

    if result is None:
        return written

    if fmt in ("skill", "all"):
        d = write_skill(out, meta, result)
        (d / "transcript.md").write_text(transcript_md, encoding="utf-8")
        written.append(d / "SKILL.md")

    if fmt in ("project", "all"):
        p = out / "knowledge.md"
        p.write_text(f"# {meta['title']}\n\n{source_block(meta)}\n"
                     f"**요약:** {result['one_line_summary']}\n\n{result['knowledge_markdown']}\n",
                     encoding="utf-8")
        written.append(p)

    if fmt in ("claude-md", "all"):
        p = out / "CLAUDE.md.snippet"
        p.write_text(f"## 참고 지식: {meta['title']}\n{source_block(meta)}\n"
                     f"{result['claude_md_rules']}\n", encoding="utf-8")
        written.append(p)

    (out / "result.json").write_text(json.dumps({"meta": meta, **result}, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    return written


HOWTO = """
── Claude에 적용하는 방법 ──────────────────────────────
• Skill (Claude Code):   skill/<이름>/ 폴더를 ~/.claude/skills/ 또는 프로젝트의 .claude/skills/ 로 복사
• Skill (claude.ai):     skill/<이름>/ 폴더를 zip으로 묶어 설정 → 기능(Capabilities) → Skills 에서 업로드
• 프로젝트 지식:          knowledge.md 를 claude.ai 프로젝트의 'Project knowledge'에 업로드
• CLAUDE.md:             CLAUDE.md.snippet 내용을 프로젝트 CLAUDE.md 끝에 붙여넣기
• 그냥 대화에서:          knowledge.md 나 transcript.md 를 대화창에 첨부
──────────────────────────────────────────────────────
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="유튜브 영상을 Claude용 지식 자료로 변환")
    ap.add_argument("urls", nargs="+", help="유튜브 URL 또는 영상 ID (여러 개 가능)")
    ap.add_argument("--format", choices=["skill", "project", "claude-md", "all"], default="all",
                    help="출력 형식 (기본: all)")
    ap.add_argument("--langs", default=",".join(DEFAULT_LANGS),
                    help="선호 자막 언어, 쉼표 구분 (기본: ko,en)")
    ap.add_argument("--out-lang", default="한국어", help="정리 결과 언어 (기본: 한국어)")
    ap.add_argument("--out", default="output", help="출력 폴더 (기본: ./output)")
    ap.add_argument("--transcript-only", action="store_true",
                    help="Claude API를 쓰지 않고 자막만 저장 (API 키 불필요)")
    args = ap.parse_args()

    failures = 0
    for u in args.urls:
        try:
            vid = extract_video_id(u)
            meta = fetch_metadata(vid)
            print(f"▶ {meta['title']} ({meta['channel']})")
            transcript, lang = fetch_transcript(vid, [l.strip() for l in args.langs.split(",") if l.strip()])
            print(f"  자막 {len(transcript):,}자 확보 (언어: {lang})")

            result = None
            if not args.transcript_only:
                print(f"  Claude({MODEL})로 정리 중…")
                result = summarize_with_claude(meta, transcript, args.out_lang)

            out = Path(args.out) / safe_dirname(meta["title"])
            for p in write_outputs(out, meta, transcript, lang, result, args.format):
                print(f"  ✓ {p}")
        except Exception as e:
            failures += 1
            print(f"  ✗ 실패 ({u}): {e}", file=sys.stderr)

    print(HOWTO)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
