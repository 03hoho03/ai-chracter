"""명세 한 권을 격리 DB 에 소설·화·개정으로 심는다. 반복마다 새로 심어 새 소설이 된다 — 추출 캐시가 소설 단위라 반복끼리
제안을 나눠 갖지 않는다.

화는 화 하나짜리 묶음에 든다(묶음 번호 = 화 번호). 그래서 탐침 화를 묶음 삭제로 지울 수 있다. 채팅 구간 칸은 합성 값이다 —
측정은 채팅 원문을 읽지 않는다. 회원은 소설마다 하나 만들고, 이메일은 예약 도메인(`.invalid`)이라 실제 주소와 겹치지 않는다."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Novel, NovelBatch, NovelChapter, User
from api.novelize.blocks import build_revision, fresh_ids

from novel_bible_eval.spec import ChapterSpec, NovelSpec

# 측정 회원이 동의한 것으로 치는 약관·처리방침 판. 동의 게이트를 타는 경로를 부르지 않으므로 값은 꼴만 맞으면 된다.
_LEGAL_VERSION = "2026-09-06"
EVAL_EMAIL_DOMAIN = "novel-bible-eval.invalid"


@dataclass(frozen=True)
class SeededChapter:
    ordinal: int
    chapter_id: uuid.UUID
    batch_id: uuid.UUID | None  # 묶음 없는 옛 화(사람 라벨용 사본)는 None
    revision_id: uuid.UUID
    block_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class SeededNovel:
    key: str
    novel_id: uuid.UUID
    chapters: tuple[SeededChapter, ...]


async def add_chapter(session: AsyncSession, novel_id: uuid.UUID, ordinal: int, spec: ChapterSpec) -> SeededChapter:
    now = datetime.now(UTC)
    segment = {
        "start_message_id": uuid.uuid4(), "start_message_created_at": now, "end_message_id": uuid.uuid4(),
        "end_message_created_at": now, "assistant_message_count": 1, "source_hash": "0" * 64,
    }
    batch = NovelBatch(novel_id=novel_id, ordinal=ordinal, target_episode_count=1, **segment)
    session.add(batch)
    await session.flush()
    chapter = NovelChapter(novel_id=novel_id, ordinal=ordinal, batch_id=batch.id, episode_index=0, **segment)
    session.add(chapter)
    await session.flush()
    revision = build_revision(
        chapter_id=chapter.id, revision_no=1, body=spec.body, source="manual_edit", block_ids=fresh_ids(spec.body)
    )
    session.add(revision)
    await session.flush()
    return SeededChapter(ordinal, chapter.id, batch.id, revision.id, tuple(revision.block_ids))


async def seed_novel(session: AsyncSession, spec: NovelSpec) -> SeededNovel:
    """회원·소설·기본 화 전부(flush). 커밋은 호출부가 한다."""
    agreed = datetime.now(UTC)
    user = User(
        email=f"eval-{uuid.uuid4()}@{EVAL_EMAIL_DOMAIN}", nickname="측정", birth_date=date(2000, 1, 1),
        terms_agreed_at=agreed, privacy_agreed_at=agreed, transfer_agreed_at=agreed,
        terms_version=_LEGAL_VERSION, privacy_version=_LEGAL_VERSION, transfer_version=_LEGAL_VERSION,
    )
    session.add(user)
    await session.flush()
    novel = Novel(
        user_id=user.id, content_id=uuid.uuid4(), content_type="character", content_title="합성 원작",
        character_name="합성 인물",
    )
    session.add(novel)
    await session.flush()
    chapters = [
        await add_chapter(session, novel.id, ordinal, chapter)
        for ordinal, chapter in enumerate(spec.chapters, start=1)
    ]
    return SeededNovel(spec.key, novel.id, tuple(chapters))
