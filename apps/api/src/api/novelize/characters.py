"""인물 카드 고치기·합치기와, 스냅샷 복원이 함께 쓰는 메모 잇기 규칙.

이름과 별칭을 모은 공간은 소설 안에서 겹치지 않는다 — 생성 출력의 등장 인물 이름 하나가 카드 둘에 붙으면 안 되기
때문이다. DB 는 `(novel_id, name)` 유니크만 막으므로 별칭까지의 유일성은 코드가 지키고, 카드를 고치는 모든 경로(생성 결과
저장의 인물 붙이기, 여기의 추가·수정·합치기, 스냅샷 복원)가 **사용자 행 잠금** 아래에서 돈다. 잠금을 쥐지 않고 고치면
생성 저장이 합치기 전 카드 목록을 읽고 흡수될 카드에 이름을 붙이거나, 같은 이름의 카드를 하나 더 만든다.

여기 함수는 호출자가 사용자 행을 잠근 뒤 부른다. 커밋도 호출자가 한다. 이 모듈은 라우터를 import 하지 않는다."""

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import Uuid, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelChapterCharacter, NovelCharacter


class CharacterNameTakenError(Exception):
    """이름이나 별칭이 같은 소설의 다른 카드 것과 겹친다. `name` 은 겹친 값이다."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def clean_aliases(name: str, aliases: Iterable[str]) -> list[str]:
    """별칭 목록을 저장할 모양으로 — 앞뒤 공백을 걷고, 빈 값·중복·이름과 같은 값을 뺀다(처음 나온 순서 유지)."""
    cleaned: list[str] = []
    for alias in aliases:
        value = alias.strip()
        if value and value != name and value not in cleaned:
            cleaned.append(value)
    return cleaned


def joined_memo(base: str, absorbed: Sequence[tuple[str, str]]) -> str:
    """남는 카드 메모 뒤에 흡수된 카드 메모를 `[이름] 메모` 꼴로 빈 줄 하나를 두고 잇는다. 빈 메모는 잇지 않는다 — 이름만
    남은 머리 줄은 다음 묶음 입력에 실려도 쓸 정보가 없다. 합치기와 스냅샷 복원이 같은 꼴을 써야 복원한 메모가 합쳤을
    때의 메모와 같은 모양이 된다."""
    parts = [base] if base.strip() else []
    parts.extend(f"[{name}] {memo}" for name, memo in absorbed if memo.strip())
    return "\n\n".join(parts)


async def load_cards(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelCharacter]:
    """소설의 카드를 만든 순서대로."""
    rows = await db.scalars(
        select(NovelCharacter)
        .where(NovelCharacter.novel_id == novel_id)
        .order_by(NovelCharacter.created_at, NovelCharacter.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


def _assert_free(cards: Sequence[NovelCharacter], names: Iterable[str], *, except_id: uuid.UUID | None) -> None:
    taken = {value for card in cards if card.id != except_id for value in (card.name, *card.aliases)}
    for value in names:
        if value in taken:
            raise CharacterNameTakenError(value)


async def add_character(db: AsyncSession, novel_id: uuid.UUID, name: str) -> None:
    """`name` 카드가 있게 한다. 같은 이름의 카드가 있으면 그대로 두고, 다른 카드의 별칭이면 겹침 오류다."""
    cards = await load_cards(db, novel_id)
    if any(card.name == name for card in cards):
        return
    _assert_free(cards, [name], except_id=None)
    db.add(NovelCharacter(novel_id=novel_id, name=name))
    await db.flush()


async def update_character(
    db: AsyncSession,
    card: NovelCharacter,
    *,
    name: str | None,
    aliases: list[str] | None,
    memo: str | None,
) -> None:
    """보낸 칸만 바꾼다. 이름을 바꾸면서 별칭은 보내지 않았으면, 지금 별칭에서 새 이름과 같은 값을 뺀다."""
    new_name = name if name is not None else card.name
    new_aliases = clean_aliases(new_name, aliases if aliases is not None else card.aliases)
    cards = await load_cards(db, card.novel_id)
    _assert_free(cards, [new_name, *new_aliases], except_id=card.id)
    values: dict[str, object] = {"name": new_name, "aliases": new_aliases, "updated_at": func.now()}
    if memo is not None:
        values["memo"] = memo
    await db.execute(update(NovelCharacter).where(NovelCharacter.id == card.id).values(**values))


async def merge_characters(db: AsyncSession, absorbed: NovelCharacter, into: NovelCharacter) -> None:
    """`absorbed` 를 `into` 로 합친다. 흡수되는 카드의 이름·별칭이 남는 카드의 별칭이 되므로 그 뒤 생성 출력이 같은 이름을
    내면 남는 카드에 붙는다. 메모는 `joined_memo` 꼴로 잇고, 등장 화를 옮긴 뒤 흡수되는 카드를 지운다.

    두 카드의 이름 공간은 이미 서로 겹치지 않으므로(사용자 잠금 아래에서 늘 지킨다) 별칭을 합쳐도 다른 카드와 겹치지
    않는다. 두 카드가 같은 화에 함께 나왔으면 그 화의 연결은 하나로 줄어든다."""
    aliases = clean_aliases(into.name, [*into.aliases, absorbed.name, *absorbed.aliases])
    memo = joined_memo(into.memo, [(absorbed.name, absorbed.memo)])
    await db.execute(
        insert(NovelChapterCharacter)
        .from_select(
            ["chapter_id", "character_id"],
            select(NovelChapterCharacter.chapter_id, literal(into.id, Uuid)).where(
                NovelChapterCharacter.character_id == absorbed.id
            ),
        )
        .on_conflict_do_nothing()
    )
    await db.execute(delete(NovelChapterCharacter).where(NovelChapterCharacter.character_id == absorbed.id))
    await db.execute(delete(NovelCharacter).where(NovelCharacter.id == absorbed.id))
    await db.execute(
        update(NovelCharacter)
        .where(NovelCharacter.id == into.id)
        .values(aliases=aliases, memo=memo, updated_at=func.now())
    )
