"""Claude로 스크립트를 학습 코스로 바꾸고, 튜터 질문에 답한다."""
from __future__ import annotations

import json
from typing import AsyncIterator, Awaitable, Callable

import anthropic
from anthropic import AsyncAnthropic

from config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
_I = {"type": "integer"}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


COURSE_SCHEMA = _obj({
    "title": _S,
    "one_liner": _S,
    "difficulty": {"type": "string", "enum": ["입문", "중급", "고급"]},
    "estimated_minutes": _I,
    "summary": _arr(_S),
    "chapters": _arr(_obj({"time": _S, "title": _S, "gist": _S})),
    "concepts": _arr(_obj({"term": _S, "explanation": _S, "analogy": _S})),
    "lesson_path": _arr(_obj({"step_title": _S, "minutes": _I, "content": _S, "check_question": _S, "check_answer": _S})),
    "flashcards": _arr(_obj({"front": _S, "back": _S})),
    "quiz": _arr(_obj({"question": _S, "choices": _arr(_S), "answer_index": _I, "explanation": _S})),
    "related": _arr(_obj({"topic": _S, "why": _S, "search_query": _S})),
    "caveats": _arr(_S),
})

COURSE_SYSTEM = """당신은 유튜브 영상을 짧고 효과적인 학습 코스로 바꾸는 학습 설계자입니다.
학습자는 영상 내용을 "이해하고 기억하는 것"이 목표입니다. 요약에서 멈추지 말고, 떠올리기(퀴즈·카드)와 다음 학습까지 설계하세요.

작성 원칙
- 모든 출력은 자연스러운 한국어로 씁니다. 전문 용어는 처음 나올 때 원어를 괄호로 덧붙입니다. 영상이 다른 언어여도 한국어로 씁니다.
- 학습자 수준과 학습 시간에 분량을 맞춥니다. lesson_path의 minutes 합은 학습 시간과 비슷해야 합니다.
- 영상에 실제로 나온 내용을 중심으로 하고, 이해에 꼭 필요한 배경지식은 보충하되 영상 밖 내용임을 문장에서 드러냅니다.
- 스크립트는 자동 자막이나 음성 인식 결과일 수 있어 오타·잘못 들은 단어가 섞여 있습니다. 맥락으로 바로잡아 이해하고, 틀린 표기를 그대로 옮기지 마세요.
- chapters의 time은 스크립트의 타임스탬프(예: "3:25", "1:02:10")를 그대로 씁니다. 타임스탬프를 알 수 없으면 빈 문자열로 둡니다.
- lesson_path 각 단계의 content는 3~6문단의 짧은 레슨입니다. 예시를 하나 이상 넣으세요. check_question은 그 단계의 핵심을 스스로 설명하게 하는 질문, check_answer는 모범 답안입니다.
- concepts는 4~8개, flashcards는 8~14장, quiz는 5~8문항(보기 4개, answer_index는 0부터)으로 만듭니다. 퀴즈는 단순 암기보다 이해를 확인하게 하고, 오답 보기도 그럴듯하게 만듭니다. 정답 위치는 고르게 섞습니다.
- related는 4~6개로, 이 영상 다음에 공부하면 좋은 주제와 이유, 유튜브에서 쓸 검색어를 줍니다.
- caveats에는 영상 속 주장 중 사실 확인이 필요하거나, 오래되었거나, 논쟁적인 부분을 적습니다. 없으면 빈 배열입니다."""


class CourseError(Exception):
    """사용자에게 보여 줄 한국어 메시지."""


def make_client(settings: Settings) -> AsyncAnthropic:
    # 키가 없으면 SDK 기본 인증 순서(환경 변수, ant 로그인 프로필 등)를 따른다
    return AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else AsyncAnthropic()


def course_prompt(*, transcript: str, level: str, minutes: int, title: str = "", channel: str = "",
                  description: str = "", source: str = "") -> str:
    src_note = {
        "captions": "유튜브 자막",
        "stt": "음성 인식으로 받아 적은 스크립트 (고유명사 오류 가능)",
        "pasted": "사용자가 붙여넣은 스크립트",
    }.get(source, "스크립트")
    head = [f"학습자 수준: {level}", f"학습 시간: 약 {minutes}분"]
    if title:
        head.append(f"영상 제목: {title}")
    if channel:
        head.append(f"채널: {channel}")
    parts = ["\n".join(head)]
    if description:
        parts.append(f"<description>\n{description}\n</description>")
    parts.append(f"아래는 영상의 {src_note}입니다. 이 내용을 바탕으로 학습 코스를 만들어 주세요.\n\n<transcript>\n{transcript}\n</transcript>")
    return "\n\n".join(parts)


async def build_course(settings: Settings, prompt: str, on_progress: Callable[[int], Awaitable[None]] | None = None) -> dict:
    client = make_client(settings)
    chars = 0
    try:
        async with client.beta.messages.stream(
            model=settings.claude_model,
            max_tokens=64000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": COURSE_SCHEMA}},
            system=COURSE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                chars += len(text)
                if on_progress:
                    await on_progress(chars)
            msg = await stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise CourseError("서버의 Claude API 키가 올바르지 않아요.") from e
    except anthropic.RateLimitError as e:
        raise CourseError("요청이 많아 잠시 막혔어요. 1분쯤 뒤에 다시 시도해 주세요.") from e
    except anthropic.BadRequestError as e:
        raise CourseError(f"요청이 거부됐어요: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise CourseError("Claude 서버에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise CourseError("Claude API에 연결하지 못했어요.") from e

    if msg.stop_reason == "refusal":
        raise CourseError("이 영상 내용은 분석할 수 없다는 응답을 받았어요.")
    if msg.stop_reason == "max_tokens":
        raise CourseError("결과가 너무 길어 잘렸어요. 학습 시간을 줄여 다시 시도해 주세요.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise CourseError("결과를 읽지 못했어요. 한 번 더 시도해 주세요.") from e


def tutor_system(*, title: str, transcript: str, level: str) -> list[dict]:
    text = f"""당신은 친절한 1:1 튜터입니다. 학습자는 아래 유튜브 영상을 공부하고 있습니다 (수준: {level}).
영상 내용을 근거로 한국어로 답하세요. 짧고 명확하게, 필요하면 예시를 드세요. 마크다운 기호(#, ** 등)는 쓰지 말고 평범한 문장과 줄바꿈으로 씁니다.
영상에 없는 내용을 보충할 때는 "영상 밖 내용이지만"이라고 밝힙니다. 해당 시점이 있으면 타임스탬프를 알려 주세요.

영상 제목: {title}
<transcript>
{transcript}
</transcript>"""
    # 같은 영상으로 여러 번 질문하므로 스크립트 부분을 캐시한다
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


async def tutor_stream(settings: Settings, *, system: list[dict], messages: list[dict]) -> AsyncIterator[str]:
    client = make_client(settings)
    try:
        async with client.beta.messages.stream(
            model=settings.claude_model,
            max_tokens=8000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "low"},
            system=system,
            messages=messages,
        ) as stream:
            got = False
            async for text in stream.text_stream:
                got = True
                yield text
            msg = await stream.get_final_message()
            if msg.stop_reason == "refusal" and not got:
                yield "이 질문에는 답하기 어려워요. 다른 방식으로 물어봐 주세요."
    except anthropic.RateLimitError:
        yield "\n[요청이 많아 잠시 막혔어요. 잠시 후 다시 물어봐 주세요.]"
    except anthropic.APIError:
        yield "\n[답변 중 오류가 났어요. 다시 시도해 주세요.]"
