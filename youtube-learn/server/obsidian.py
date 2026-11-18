"""Obsidian 보관함(vault) 폴더에 마크다운 노트를 쓴다.

Obsidian은 보관함 폴더의 .md 파일을 그대로 노트로 보여 주므로, 파일만 쓰면 바로 나타난다.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from config import Settings

BAD_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
MAX_NAME = 80


class ObsidianError(Exception):
    """사용자에게 보여 줄 한국어 메시지."""


def safe_name(title: str) -> str:
    """노트 제목을 Windows·Mac·Obsidian 모두에서 쓸 수 있는 파일 이름으로 바꾼다."""
    name = unicodedata.normalize("NFC", title or "")
    name = BAD_CHARS.sub(" ", name)
    name = re.sub(r"\.{2,}", " ", name)  # '..' 같은 상위 폴더 표기를 없앤다
    name = re.sub(r"\s+", " ", name).strip().strip(".").strip()
    return name[:MAX_NAME].strip() or "클립러닝 노트"


def _folder(settings: Settings) -> tuple[Path, Path]:
    if not settings.obsidian_vault:
        raise ObsidianError("서버에 Obsidian 보관함 위치가 없어요. .env의 OBSIDIAN_VAULT에 보관함 폴더 경로를 넣어 주세요.")
    vault = Path(settings.obsidian_vault).expanduser()
    if not vault.is_dir():
        raise ObsidianError(f"Obsidian 보관함 폴더를 찾을 수 없어요: {vault}")
    parts = [p for p in re.split(r"[\\/]", settings.obsidian_folder or "") if p.strip(" .")]
    sub = Path(*[safe_name(p) for p in parts])
    folder = (vault / sub).resolve()
    if vault.resolve() not in (folder, *folder.parents):
        raise ObsidianError("OBSIDIAN_FOLDER는 보관함 안의 폴더여야 해요.")
    return vault, folder


def write_note(settings: Settings, *, title: str, markdown: str, source: str) -> dict:
    """노트를 쓰고 {보관함 기준 상대 경로, 보관함 이름}을 돌려준다.

    같은 영상(source)으로 만든 노트가 이미 있으면 덮어쓰고, 이름만 같은 다른 노트가 있으면 (2), (3)… 을 붙인다.
    """
    vault, folder = _folder(settings)
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_name(title)
    marker = f"source: {source}" if source else None
    for i in range(1, 100):
        path = folder / (f"{base}.md" if i == 1 else f"{base} ({i}).md")
        if not path.exists():
            break
        if marker and marker in path.read_text(encoding="utf-8", errors="ignore"):
            break  # 같은 영상의 노트: 새 내용으로 바꾼다
    else:
        raise ObsidianError("같은 이름의 노트가 너무 많아요.")
    path.write_text(markdown, encoding="utf-8", newline="\n")
    return {"path": path.relative_to(vault.resolve()).as_posix(), "vault": vault.resolve().name}
