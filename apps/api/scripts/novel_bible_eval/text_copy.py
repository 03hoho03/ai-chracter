"""사람 라벨 원고 — 텍스트 파일 폴더에서 격리 DB 안에 새 소설 사본을 만든다. 어댑터마다 사본 하나를 따로 둔다: 추출 캐시와 확정이
소설 단위라, 같은 소설로 두 번째 어댑터를 돌리면 확정 입구가 같은 개정을 그대로 돌려 첫 어댑터의 작업을 모은다.

폴더 꼴: 화마다 `01.txt`…`NN.txt`(번호는 1부터 빠짐없이, UTF-8, 빈 줄로 문단을 가름 — 앱이 개정 본문을 문단으로 나누는 규칙 그대로),
선택 `meta.txt` 의 첫 줄이 제목(없으면 폴더 이름). 그 밖의 파일은 읽지 않는다. 원고는 커밋하지 않는 로컬 폴더에만 둔다.

사본에는 원작·채팅 방·장면 구성안이 없다. 소설의 원작 칸은 행이 없는 id 라 원작 정본을 읽지 않고, 방이 없어 플레이 사실이 없고,
장면 행이 없어 화 전체가 장면 하나로 읽힌다 — 실제 공개 소설을 원작·대화 없이 잰다. 화는 합성 세트와 같은 심기로 놓는다(화
하나짜리 묶음, 고정 기준 시각에서 화 번호 차례로 오르는 구간)."""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Novel
from api.novelize.text import split_paragraphs

from novel_bible_eval.seed import SeededChapter, _member, add_chapter
from novel_bible_eval.spec import ChapterSpec

_CHAPTER_FILE = re.compile(r"^(\d+)\.txt$")


@dataclass(frozen=True)
class TextNovel:
    title: str
    chapters: tuple[tuple[str, ...], ...]  # 화마다 문단


def read_text_dir(folder: Path) -> TextNovel:
    """번호가 빠졌거나 겹치거나 문단이 없는 화가 있으면 거절한다 — 그대로 심으면 화 번호가 원고와 어긋나 라벨이 엉뚱한 화를
    가리킨다."""
    numbered: dict[int, Path] = {}
    for path in sorted(folder.iterdir()):
        found = _CHAPTER_FILE.match(path.name)
        if found is None:
            continue
        number = int(found.group(1))
        if number in numbered:
            raise ValueError(f"{numbered[number].name} 와 {path.name} 가 같은 화 번호로 겹친다")
        numbered[number] = path
    if not numbered:
        raise ValueError(f"{folder} 에 화 파일(01.txt 꼴)이 없다")
    missing = sorted(set(range(1, max(numbered) + 1)) - set(numbered))
    if missing:
        raise ValueError(f"빠진 화가 있다: {missing}")
    chapters = []
    for number in sorted(numbered):
        # BOM 을 걷는다 — 남으면 첫 문단 머리에 보이지 않는 글자가 붙는다. CRLF 는 텍스트 모드 읽기가 줄바꿈 하나로 바꾼다.
        text = numbered[number].read_text(encoding="utf-8-sig")
        paragraphs = split_paragraphs(text)
        if not paragraphs:
            raise ValueError(f"{numbered[number].name} 에 문단이 없다")
        chapters.append(tuple(paragraphs))
    meta = folder / "meta.txt"
    lines = meta.read_text(encoding="utf-8-sig").splitlines() if meta.exists() else []
    title = lines[0].strip() if lines and lines[0].strip() else folder.name
    return TextNovel(title=title, chapters=tuple(chapters))


async def copy_text_novel(session: AsyncSession, text: TextNovel) -> tuple[uuid.UUID, tuple[SeededChapter, ...]]:
    """사본 하나(flush) — 측정 회원·소설·화마다 첫 개정. 커밋은 호출부가 한다."""
    reader = await _member(session, "측정")
    novel = Novel(
        user_id=reader.id, chat_room_id=None, content_id=uuid.uuid4(), content_type="story",
        content_title=text.title, title=text.title,
    )
    session.add(novel)
    await session.flush()
    chapters = [
        await add_chapter(session, novel.id, ordinal, ChapterSpec(paragraphs=list(paragraphs)))
        for ordinal, paragraphs in enumerate(text.chapters, start=1)
    ]
    return novel.id, tuple(chapters)
