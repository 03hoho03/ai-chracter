"""스냅샷 — 소설의 편집 가능한 상태를 이름 붙여 떠 두고 그 상태로 되돌리기.

담는 것은 사용자가 고치는 값뿐이다: 소설 제목(과 사용자가 고친 시각)·소개·설정 노트, 인물 카드(이름·별칭·메모), 화마다 그때의
현재 개정 id·화 제목·요약·작가의 말. 등장 연결은 담지 않는다 — 본문과 함께 생성 출력에서 나온 사실이라 되돌릴 대상이 아니다.
payload 형식(`v` = 1):

    {v, title, titleEditedAt, synopsis, settingNotes,
     characters: [{id, name, aliases, memo}],
     chapters: [{chapterId, revisionId, title, summary, authorNote} | {chapterId, deleted: true}]}

`deleted` 항목은 그 뒤 마지막 묶음 삭제가 화를 지우며 줄여 놓은 것이다(`deletion.delete_batch`).

복원은 구조를 바꾸지 않고 내용만 되돌린다 — 스냅샷 뒤에 생긴 화는 지우지 않고(값을 치른 화가 사라지지 않게), 스냅샷의 화는
그때 본문을 새 개정으로 쌓는다(이력은 남는다). 여기 함수는 호출자가 사용자 행을 잠근 뒤 부르고, 커밋도 호출자가 한다. 이
모듈은 라우터를 import 하지 않는다."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterRevision,
    NovelCharacter,
    NovelSnapshot,
    NovelSnapshotKind,
)
from api.novelize.characters import clean_aliases, joined_memo, load_cards
from api.novelize.inputs import current_revision

PAYLOAD_VERSION = 1


class SnapshotLimitError(Exception):
    """이름 붙인 스냅샷만으로 상한이 찼다."""


async def build_payload(db: AsyncSession, novel_id: uuid.UUID) -> dict[str, Any]:
    """소설의 지금 상태를 payload 로. 화는 화 번호 순, 인물은 만든 순서다."""
    novel = await db.get_one(Novel, novel_id, populate_existing=True)
    latest = (
        select(NovelChapterRevision.chapter_id, NovelChapterRevision.id)
        .distinct(NovelChapterRevision.chapter_id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapterRevision.chapter_id, NovelChapterRevision.revision_no.desc())
    )
    revisions = dict((await db.execute(latest)).tuples().all())
    chapters = (
        await db.scalars(
            select(NovelChapter)
            .where(NovelChapter.novel_id == novel_id)
            .order_by(NovelChapter.ordinal)
            .execution_options(populate_existing=True)
        )
    ).all()
    return {
        "v": PAYLOAD_VERSION,
        "title": novel.title,
        "titleEditedAt": novel.title_edited_at.isoformat() if novel.title_edited_at is not None else None,
        "synopsis": novel.synopsis,
        "settingNotes": novel.setting_notes,
        "characters": [
            {"id": str(card.id), "name": card.name, "aliases": list(card.aliases), "memo": card.memo}
            for card in await load_cards(db, novel_id)
        ],
        "chapters": [
            {
                "chapterId": str(chapter.id),
                "revisionId": str(revisions[chapter.id]),
                "title": chapter.title,
                "summary": chapter.summary,
                "authorNote": chapter.author_note,
            }
            for chapter in chapters
            # 화 행과 첫 개정은 한 트랜잭션에서 함께 들어가므로 개정 없는 화는 없다.
            if chapter.id in revisions
        ],
    }


async def save_snapshot(db: AsyncSession, novel_id: uuid.UUID, *, name: str, kind: NovelSnapshotKind) -> NovelSnapshot:
    """지금 상태를 스냅샷으로 넣는다(flush). 상한에 닿아 있으면 가장 오래된 자동 스냅샷부터 지워 자리를 낸다. 이름 붙인
    것만으로 차 있으면 이름 붙인 저장은 `SnapshotLimitError` 이고, 복원 직전 자동 스냅샷은 그래도 넣는다 — 상한 때문에
    복원이 막히면 안 되기 때문이다. 그래서 소설 하나의 스냅샷은 상한보다 한 장 많을 수 있고, 그 한 장은 다음 저장이나
    복원 때 가장 오래된 자동 스냅샷으로 먼저 지워진다."""
    limit = settings.novelize_snapshot_limit
    count = int(
        await db.scalar(select(func.count()).select_from(NovelSnapshot).where(NovelSnapshot.novel_id == novel_id)) or 0
    )
    if count >= limit:
        autos = (
            await db.scalars(
                select(NovelSnapshot.id)
                .where(NovelSnapshot.novel_id == novel_id, NovelSnapshot.kind == "auto_before_restore")
                .order_by(NovelSnapshot.created_at, NovelSnapshot.id)
                .limit(count - limit + 1)
            )
        ).all()
        if autos:
            await db.execute(delete(NovelSnapshot).where(NovelSnapshot.id.in_(autos)))
            count -= len(autos)
    if count >= limit and kind == "manual":
        raise SnapshotLimitError
    snapshot = NovelSnapshot(novel_id=novel_id, name=name, kind=kind, payload=await build_payload(db, novel_id))
    db.add(snapshot)
    await db.flush()
    return snapshot


@dataclass(frozen=True)
class RestoreResult:
    auto_snapshot_id: uuid.UUID
    # 화나 그때 개정이 지워져 본문을 되돌리지 못한 화.
    skipped_chapter_ids: list[uuid.UUID]
    # 새 개정을 쌓은 화 — 커밋 뒤 이 화들의 낡은 AI 수정 미리보기를 비운다.
    restacked_chapter_ids: list[uuid.UUID]


async def restore_snapshot(db: AsyncSession, novel_id: uuid.UUID, snapshot: NovelSnapshot) -> RestoreResult:
    """`snapshot` 으로 되돌린다. 먼저 지금 상태를 자동 스냅샷으로 떠 둔다(되돌린 것을 다시 되돌릴 수 있게).

    잠금 순서는 사용자(호출자) → 화들 → 소설이다. 화를 하나씩 잠그며 개정을 쌓고, 소설 행은 화를 다 잠근 뒤 맨 끝에 한 번만
    고친다. 화마다 소설 수정 시각을 밀면 소설 행을 쥔 채 다음 화를 기다리게 되는데, 직접 수정은 화 → 소설 순서라 그 화를
    쥔 채 소설 행을 기다려 서로 교착한다. 작업 행은 잡지 않는다 — 낡은 AI 수정 미리보기는 커밋 뒤 호출자가 별도
    트랜잭션에서 비운다(적용이 작업 → 화 순서로 잡기 때문이다)."""
    payload = snapshot.payload
    auto = await save_snapshot(db, novel_id, name=f"「{snapshot.name}」 복원 직전", kind="auto_before_restore")
    skipped: list[uuid.UUID] = []
    restacked: list[uuid.UUID] = []
    for entry in payload["chapters"]:
        chapter_id = uuid.UUID(entry["chapterId"])
        if entry.get("deleted") or not await _restore_chapter(db, novel_id, chapter_id, entry, restacked):
            skipped.append(chapter_id)
    await _restore_characters(db, novel_id, payload["characters"])
    edited_at = payload["titleEditedAt"]
    await db.execute(
        update(Novel)
        .where(Novel.id == novel_id)
        .values(
            title=payload["title"],
            # 스냅샷 때 AI 가 쓴 제목이었으면 비워진 채로 돌아가, 다음 생성이 제목을 다시 쓸 수 있다.
            title_edited_at=datetime.fromisoformat(edited_at) if edited_at is not None else None,
            synopsis=payload["synopsis"],
            setting_notes=payload["settingNotes"],
            updated_at=func.now(),
        )
    )
    return RestoreResult(auto_snapshot_id=auto.id, skipped_chapter_ids=skipped, restacked_chapter_ids=restacked)


async def _restore_chapter(
    db: AsyncSession, novel_id: uuid.UUID, chapter_id: uuid.UUID, entry: dict[str, Any], restacked: list[uuid.UUID]
) -> bool:
    """화 하나를 되돌린다. 화나 그때 개정이 없으면 아무것도 바꾸지 않고 False. 화 행은 개정을 쌓는 다른 경로(직접 수정·
    되돌리기·적용)와 같은 잠금으로 잡는다 — 잡은 뒤에 현재 개정을 읽어야 그 사이 커밋된 개정 위에 번호를 잇는다. 지금 개정이
    이미 그때 개정이면 같은 본문을 한 번 더 쌓지 않는다."""
    locked = await db.scalar(
        select(NovelChapter.id)
        .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel_id)
        .with_for_update(key_share=True)
    )
    if locked is None:
        return False
    source = await db.scalar(
        select(NovelChapterRevision).where(
            NovelChapterRevision.id == uuid.UUID(entry["revisionId"]), NovelChapterRevision.chapter_id == chapter_id
        )
    )
    if source is None:
        return False
    current = await current_revision(db, chapter_id)
    assert current is not None  # 화 행과 첫 개정은 한 트랜잭션에서 함께 들어간다
    if current.id != source.id:
        db.add(
            NovelChapterRevision(
                chapter_id=chapter_id,
                revision_no=current.revision_no + 1,
                body=source.body,
                source="revert",
                reverted_from_revision_id=source.id,
            )
        )
        await db.flush()
        restacked.append(chapter_id)
    await db.execute(
        update(NovelChapter)
        .where(NovelChapter.id == chapter_id)
        .values(title=entry["title"], summary=entry["summary"], author_note=entry["authorNote"])
    )
    return True


async def _restore_characters(db: AsyncSession, novel_id: uuid.UUID, saved: list[dict[str, Any]]) -> None:
    """인물 카드를 되돌린다. 카드를 지우거나 새로 만들지 않는다(합치기·생성이 만든 구조는 그대로).

    - 스냅샷의 카드가 살아 있으면 이름·별칭·메모를 그때 값으로.
    - 그 뒤 합쳐져 사라진 카드는 그 이름을 별칭으로 가진 카드(남은 카드)에 메모를 돌려준다 — 남은 카드 자신의 그때 메모(그때
      없던 카드면 지금 메모) 뒤에 사라진 카드의 그때 메모를 `[이름] 메모` 꼴로 잇는다. 남은 카드의 별칭에서 합쳐 온 이름은
      빼지 않는다 — 빼면 그 이름이 다음 생성에서 새 카드로 갈라진다. 남은 카드를 찾지 못하면(별칭을 그 뒤 지웠다) 그 메모는
      되돌리지 않는다.
    - 그때 이름·별칭이 스냅샷에 없던 카드(그 뒤 생긴 카드)의 이름·별칭과 겹치면 그 카드의 이름·별칭은 지금 값으로 두고
      메모만 되돌린다 — 이름 ∪ 별칭은 소설 안에서 겹치면 안 된다."""
    cards = await load_cards(db, novel_id)
    alive = {card.id: card for card in cards}
    saved_by_id = {uuid.UUID(entry["id"]): entry for entry in saved}
    absorbed: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for saved_id, saved_entry in saved_by_id.items():
        if saved_id in alive:
            continue
        survivor = next((card for card in cards if saved_entry["name"] in card.aliases), None)
        if survivor is not None:
            absorbed.setdefault(survivor.id, []).append(saved_entry)

    targets: dict[uuid.UUID, tuple[str, list[str]]] = {}
    for card in cards:
        own = saved_by_id.get(card.id)
        if own is None:
            continue
        merged = [
            value
            for gone in absorbed.get(card.id, [])
            for value in (gone["name"], *gone["aliases"])
            if value in card.aliases
        ]
        targets[card.id] = (own["name"], clean_aliases(own["name"], [*own["aliases"], *merged]))
    # 이름을 지금 값으로 남기는 카드가 생기면 그 이름이 다른 카드의 목표와 겹칠 수 있어, 바뀌지 않을 때까지 다시 본다.
    while True:
        fixed = {value for card in cards if card.id not in targets for value in (card.name, *card.aliases)}
        clash = next((card_id for card_id, (name, aliases) in targets.items() if {name, *aliases} & fixed), None)
        if clash is None:
            break
        del targets[clash]

    renamed = [card_id for card_id, (name, _aliases) in targets.items() if alive[card_id].name != name]
    if renamed:
        # 이름 유니크는 문장마다 검사된다. 두 카드가 이름을 맞바꾸면 한 문장씩 고치는 사이 겹치므로, 바뀔 카드 이름을 먼저
        # 겹칠 수 없는 임시 값(카드 id)으로 비워 둔다.
        for card_id in renamed:
            await db.execute(update(NovelCharacter).where(NovelCharacter.id == card_id).values(name=str(card_id)))
    for card in cards:
        entry = saved_by_id.get(card.id)
        gone = absorbed.get(card.id, [])
        if entry is None and not gone:
            continue
        base = entry["memo"] if entry is not None else card.memo
        values: dict[str, object] = {
            "memo": joined_memo(base, [(item["name"], item["memo"]) for item in gone]),
            "updated_at": func.now(),
        }
        if card.id in targets:
            values["name"], values["aliases"] = targets[card.id]
        await db.execute(update(NovelCharacter).where(NovelCharacter.id == card.id).values(**values))
