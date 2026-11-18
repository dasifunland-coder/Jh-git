"""Claude로 스크립트를 학습 코스로 바꾸고, 튜터 질문에 답한다."""
from __future__ import annotations

import json
from typing import AsyncIterator, Awaitable, Callable

import anthropic
from anthropic import AsyncAnthropic

from config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
COST_MARK = "\x1e"  # 튜터 답변 스트림 끝의 비용 정보 구분 문자


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
    "nuggets": _arr(_obj({"fact": _S, "time": _S})),
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
- nuggets는 "깨알 정보" 8~15개입니다. 영상에 나온 구체적인 숫자, 사실, 실전 팁, 예시, 의외의 포인트처럼 메모해 둘 가치가 있는 것을 한 문장씩 씁니다. summary와 겹치는 큰 흐름이 아니라 구체적인 디테일이어야 하고, 각 항목은 앞뒤 맥락 없이 읽어도 이해되게 씁니다. time은 그 내용이 나온 타임스탬프이며 모르면 빈 문자열입니다.
- chapters의 time은 스크립트의 타임스탬프(예: "3:25", "1:02:10")를 그대로 씁니다. 타임스탬프를 알 수 없으면 빈 문자열로 둡니다.
- lesson_path 각 단계의 content는 3~6문단의 짧은 레슨입니다. 예시를 하나 이상 넣으세요. check_question은 그 단계의 핵심을 스스로 설명하게 하는 질문, check_answer는 모범 답안입니다.
- concepts는 4~8개, flashcards는 8~14장, quiz는 5~8문항(보기 4개, answer_index는 0부터)으로 만듭니다. 퀴즈는 단순 암기보다 이해를 확인하게 하고, 오답 보기도 그럴듯하게 만듭니다. 정답 위치는 고르게 섞습니다.
- related는 4~6개로, 이 영상 다음에 공부하면 좋은 주제와 이유, 유튜브에서 쓸 검색어를 줍니다.
- caveats에는 영상 속 주장 중 사실 확인이 필요하거나, 오래되었거나, 논쟁적인 부분을 적습니다. 없으면 빈 배열입니다."""


class CourseError(Exception):
    """사용자에게 보여 줄 한국어 메시지."""


# 100만 토큰당 달러 (입력, 출력, 캐시 쓰기, 캐시 읽기). 2026-11 기준 공개 가격.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-fable-5-2": (8.00, 40.00, 10.00, 0.20),
}


def usage_cost(model: str, usage, usd_krw: float = 0) -> dict:
    """응답의 usage로 토큰 수와 예상 비용을 계산한다. 모르는 모델이면 usd는 None."""
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    p = PRICES.get(model)
    usd = None
    if p:
        usd = round((inp * p[0] + out * p[1] + cw * p[2] + cr * p[3]) / 1_000_000, 4)
    return {
        "model": model, "input": inp, "output": out, "cache_write": cw, "cache_read": cr,
        "usd": usd, "krw": round(usd * usd_krw) if usd is not None and usd_krw else None,
    }


def cost_line(label: str, c: dict) -> str:
    tokens = f"입력 {c['input'] + c['cache_write'] + c['cache_read']:,} / 출력 {c['output']:,} 토큰"
    if c["usd"] is None:
        return f"[비용] {label}: {tokens} (모델 {c['model']}의 가격을 몰라 금액은 계산하지 않음)"
    won = f", 약 {c['krw']:,}원" if c.get("krw") else ""
    return f"[비용] {label}: {tokens} → 약 ${c['usd']:.3f}{won}"


NO_KEY_MESSAGE = (
    "서버에 Claude API 키가 없어요. server 폴더의 .env 파일에서 ANTHROPIC_API_KEY= 뒤에 키를 넣고 저장한 뒤, "
    "서버를 껐다가(Ctrl+C) 다시 켜 주세요."
)


def make_client(settings: Settings) -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise CourseError(NO_KEY_MESSAGE)
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


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


async def build_course(settings: Settings, prompt: str,
                       on_progress: Callable[[int], Awaitable[None]] | None = None) -> tuple[dict, dict]:
    """학습 코스(JSON)와 이번 호출의 토큰·비용을 돌려준다."""
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
        cost = usage_cost(settings.claude_model, msg.usage, settings.usd_krw)
        print(cost_line("학습 코스 생성", cost), flush=True)
    except anthropic.AuthenticationError as e:
        raise CourseError("서버의 Claude API 키가 올바르지 않아요.") from e
    except anthropic.RateLimitError as e:
        raise CourseError("요청이 많아 잠시 막혔어요. 1분쯤 뒤에 다시 시도해 주세요.") from e
    except anthropic.BadRequestError as e:
        raise CourseError(f"요청이 거부됐어요: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise CourseError("Claude 서버에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise CourseError("Claude API에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.") from e
    except anthropic.AnthropicError as e:
        raise CourseError(f"Claude 호출 중 오류가 났어요: {e}") from e

    if msg.stop_reason == "refusal":
        raise CourseError("이 영상 내용은 분석할 수 없다는 응답을 받았어요.")
    if msg.stop_reason == "max_tokens":
        raise CourseError("결과가 너무 길어 잘렸어요. 학습 시간을 줄여 다시 시도해 주세요.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    try:
        return json.loads(text), cost
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
    try:
        client = make_client(settings)
    except CourseError as e:
        yield str(e)
        return
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
            cost = usage_cost(settings.claude_model, msg.usage, settings.usd_krw)
            print(cost_line("튜터 답변", cost), flush=True)
            # 답변 끝에 비용 정보를 붙인다. 화면은 이 구분 문자 뒤를 잘라 비용 표시에 쓴다.
            yield COST_MARK + json.dumps(cost)
    except anthropic.RateLimitError:
        yield "\n[요청이 많아 잠시 막혔어요. 잠시 후 다시 물어봐 주세요.]"
    except anthropic.APIError:
        yield "\n[답변 중 오류가 났어요. 다시 시도해 주세요.]"
