---
name: youtube-to-claude
description: "유튜브 영상 URL을 받아 자막을 추출하고, 내용을 정리해 Claude가 재사용할 수 있는 Skill/프로젝트 지식/CLAUDE.md 규칙으로 만든다. 사용자가 유튜브 링크를 주며 정리·요약·학습·스킬화를 요청할 때 사용한다."
---

# YouTube → Claude 지식 변환

API 키 없이 Claude Code 안에서 동작하는 버전이다. 자막 추출은 스크립트가 하고, 정리는 Claude(지금 이 세션)가 직접 한다.

## 절차

1. 자막 추출 (의존성이 없으면 먼저 `pip install youtube-transcript-api`):
   ```bash
   python <이 스킬 폴더>/scripts/yt2claude.py "<URL>" --transcript-only --out output
   ```
   `<이 스킬 폴더>`는 이 SKILL.md가 있는 폴더다. `output/<영상 제목>/transcript.md` 가 생긴다. 실패하면(자막 없음, 비공개 영상 등) 이유를 사용자에게 알리고 멈춘다.

2. `transcript.md`를 끝까지 읽는다. 길어도 잘라 읽지 말고 나눠서 전부 읽는다.

3. 같은 폴더에 다음 파일을 작성한다. 자막에 나온 내용만 쓰고, 중요한 내용에는 `[mm:ss]` 타임스탬프를 붙인다.
   - `knowledge.md` — 섹션: 개요 / 핵심 내용(주제별, 타임스탬프) / 실천 가이드(해당 시) / 용어 및 도구 / 주의사항·한계 / Claude 적용 지침("- ~한다" 규칙)
   - `skill/<영문-하이픈-이름>/SKILL.md` — frontmatter에 `name`, `description`(무엇에 관한 지식이고 어떤 요청에서 불러와야 하는지). 본문은 knowledge.md 내용 + 출처 링크. `transcript.md`도 같은 폴더에 복사한다.
   - `CLAUDE.md.snippet` — CLAUDE.md에 붙여넣을 규칙 5~15개.

4. 사용자에게 한국어로 한 줄 요약과 적용 방법을 알려준다:
   - Claude Code: `skill/<이름>/` 을 `~/.claude/skills/` 또는 `.claude/skills/` 로 복사
   - claude.ai: 스킬 폴더를 zip으로 묶어 Skills에 업로드, 또는 `knowledge.md`를 프로젝트 지식에 업로드
   - 사용자가 원하면 이 저장소의 `.claude/skills/` 에 바로 설치해 준다.
