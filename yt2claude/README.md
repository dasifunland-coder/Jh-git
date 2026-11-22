# yt2claude — 유튜브 영상 → Claude 지식 변환기

유튜브 링크를 넣으면 자막을 가져와 Claude로 정리하고, **Claude에 바로 적용할 수 있는 형태**로 저장합니다.

| 출력 파일 | 용도 |
|---|---|
| `skill/<이름>/SKILL.md` | Claude Skill. 관련 질문이 나오면 Claude가 알아서 불러와 사용 |
| `knowledge.md` | claude.ai 프로젝트 지식(Project knowledge)에 업로드하거나 대화에 첨부 |
| `CLAUDE.md.snippet` | Claude Code의 `CLAUDE.md`에 붙여넣을 규칙 목록 |
| `transcript.md` | 타임스탬프가 붙은 원문 자막 |

## 설치

```bash
pip install -r yt2claude/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # 또는 `ant auth login`
```

## 사용법

```bash
# 기본: 세 가지 형식 모두 생성 → ./output/<영상 제목>/
python yt2claude/yt2claude.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 여러 영상을 한 번에
python yt2claude/yt2claude.py URL1 URL2 URL3

# 형식 하나만
python yt2claude/yt2claude.py URL --format skill        # skill | project | claude-md | all

# API 키 없이 자막만 (자막을 직접 Claude 대화창에 붙여넣을 때)
python yt2claude/yt2claude.py URL --transcript-only

# 영어 자막 우선, 결과는 영어로
python yt2claude/yt2claude.py URL --langs en,ko --out-lang English
```

## Claude에 적용하기

- **Claude Code**: `output/<제목>/skill/<이름>/` 폴더를 `~/.claude/skills/`(전체) 또는 프로젝트의 `.claude/skills/`로 복사
- **claude.ai**: 스킬 폴더를 zip으로 묶어 설정 → Capabilities → Skills에서 업로드하거나, `knowledge.md`를 프로젝트 지식에 추가
- **CLAUDE.md**: `CLAUDE.md.snippet` 내용을 붙여넣기

## API 키 없이 Claude Code에서 쓰기

이 저장소에는 `.claude/skills/youtube-to-claude/` 스킬이 들어 있습니다. 이 저장소에서 Claude Code를 열고
"이 영상 정리해서 스킬로 만들어줘 https://youtu.be/..." 라고 말하면, 스크립트로 자막만 받고 정리는 Claude Code가 직접 합니다.

## 참고

- 자막(수동 또는 자동 생성)이 있는 영상만 처리할 수 있습니다.
- 모델은 `claude-opus-5-5`를 사용하며, 안전 분류기가 요청을 거절하면 서버에서 다른 모델로 자동 재시도합니다(`fallbacks: "default"`).
- 유튜브가 클라우드 서버 IP를 차단하는 경우가 있으니, 개인 PC에서 실행하는 것을 권장합니다.
