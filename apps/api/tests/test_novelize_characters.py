"""소설 인물 카드 라우트 — 목록, 직접 추가, 이름·별칭·메모 고치기, 합치기.

이름과 별칭을 모은 공간은 소설 안에서 겹치지 않는다(생성 출력의 이름 하나가 카드 둘에 붙지 않게). 그 유일성은 DB 가
아니라 코드가 사용자 행 잠금 아래에서 지키므로, 겹침 거절과 합치기 뒤 생성 출력이 남는 카드에 붙는 것을 여기서 본다.
생성 저장과 합치기가 겹치는 경쟁은 `test_novelize_edit_races.py` 에 있다."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.db.models.novel import NovelChapter, NovelChapterCharacter, NovelCharacter, NovelJob
from api.novelize import runner
from api.novelize.billing import create_charged_job
from factories import (
    _NeverCalledLLMClient,
    _add_batch,
    _batch_output,
    _clear_llm_override,
    _FakeLLMClient,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")


@pytest.fixture(autouse=True)
def _no_model() -> Iterator[None]:
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


async def _card(
    db: AsyncSession, novel_id: uuid.UUID, name: str, *, aliases: list[str] | None = None, memo: str = ""
) -> NovelCharacter:
    card = NovelCharacter(novel_id=novel_id, name=name, aliases=aliases or [], memo=memo)
    db.add(card)
    await db.commit()
    return card


async def _cards(db: AsyncSession, novel_id: uuid.UUID) -> list[tuple[str, list[str], str]]:
    rows = await db.scalars(
        sa.select(NovelCharacter)
        .where(NovelCharacter.novel_id == novel_id)
        .order_by(NovelCharacter.name)
        .execution_options(populate_existing=True)
    )
    return [(card.name, list(card.aliases), card.memo) for card in rows.all()]


async def test_list_shows_cards_in_creation_order_with_the_episodes_they_appear_in(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapters = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=2)
    # 한 테스트 안에서는 `now()` 가 같은 값이라 만든 순서를 시각으로 따로 준다. 이름 순과 반대로 두어 정렬 기준을 가른다.
    seojin = await _card(db_session, novel_id, "서진")
    doyun = await _card(db_session, novel_id, "도윤", aliases=["윤이"], memo="소꿉친구")
    await db_session.execute(
        sa.update(NovelCharacter)
        .where(NovelCharacter.id == seojin.id)
        .values(created_at=sa.func.now() - sa.text("interval '1 minute'"))
    )
    db_session.add_all(
        [
            NovelChapterCharacter(chapter_id=chapters[1].id, character_id=doyun.id),
            NovelChapterCharacter(chapter_id=chapters[0].id, character_id=doyun.id),
        ]
    )
    await db_session.commit()

    resp = await db_client.get(f"/novels/{novel_id}/characters")

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [(c["name"], c["aliases"], c["memo"]) for c in items] == [("서진", [], ""), ("도윤", ["윤이"], "소꿉친구")]
    assert items[1]["chapterIds"] == [str(chapters[0].id), str(chapters[1].id)]
    assert (items[0]["id"], items[0]["chapterIds"]) == (str(seojin.id), [])


async def test_adding_a_card_by_name_is_idempotent_and_an_alias_of_another_card_is_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await _card(db_session, novel_id, "도윤", aliases=["윤이"])

    first = await db_client.put(f"/novels/{novel_id}/characters", json={"name": "  하늘 "})
    again = await db_client.put(f"/novels/{novel_id}/characters", json={"name": "하늘"})
    taken = await db_client.put(f"/novels/{novel_id}/characters", json={"name": "윤이"})

    assert first.status_code == 200, first.text
    assert sorted(c["name"] for c in again.json()["items"]) == ["도윤", "하늘"]
    assert taken.status_code == 409
    assert taken.json()["detail"] == {"code": "NOVEL_CHARACTER_NAME_TAKEN", "name": "윤이"}
    assert await _cards(db_session, novel_id) == [("도윤", ["윤이"], ""), ("하늘", [], "")]


async def test_editing_a_card_cleans_its_aliases_and_refuses_names_another_card_holds(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """별칭 하나가 다른 카드의 이름·별칭과 겹쳐도 409 이고 아무것도 바뀌지 않는다 — 겹치면 생성 출력의 그 이름이 어느
    카드에 붙을지 정해지지 않는다. 자기 이름과 같은 별칭·앞뒤 공백·중복은 서버가 걷어 낸다."""
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    doyun = await _card(db_session, novel_id, "도윤", aliases=["윤이"])
    seojin = await _card(db_session, novel_id, "서진", memo="옛 메모")
    url = f"/novels/{novel_id}/characters/{seojin.id}"

    edited = await db_client.patch(url, json={"aliases": ["서진", " 진이 ", "진이"], "memo": "  새 메모  "})
    alias_clash = await db_client.patch(url, json={"aliases": ["진이", "윤이"]})
    name_clash = await db_client.patch(url, json={"name": "도윤"})
    # 자기 별칭을 이름으로 올리면 그 값은 별칭에서 빠진다(겹침이 아니다).
    own_alias_as_name = await db_client.patch(f"/novels/{novel_id}/characters/{doyun.id}", json={"name": "윤이"})

    assert edited.status_code == 200, edited.text
    assert (alias_clash.status_code, alias_clash.json()["detail"]) == (
        409,
        {"code": "NOVEL_CHARACTER_NAME_TAKEN", "name": "윤이"},
    )
    assert name_clash.json()["detail"] == {"code": "NOVEL_CHARACTER_NAME_TAKEN", "name": "도윤"}
    assert own_alias_as_name.status_code == 200
    assert await _cards(db_session, novel_id) == [("서진", ["진이"], "새 메모"), ("윤이", [], "")]


async def test_a_card_of_another_novel_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _other_room, other_novel = await _novel_setup(db_client, db_session, monkeypatch)
    foreign = await _card(db_session, other_novel, "도윤")
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    mine = await _card(db_session, novel_id, "서진")

    patched = await db_client.patch(f"/novels/{novel_id}/characters/{foreign.id}", json={"memo": "x"})
    merged = await db_client.post(
        f"/novels/{novel_id}/characters/{mine.id}/merge", json={"intoCharacterId": str(foreign.id)}
    )

    assert (patched.status_code, patched.json()["detail"]) == (404, {"code": "NOVEL_CHARACTER_NOT_FOUND"})
    assert (merged.status_code, merged.json()["detail"]) == (404, {"code": "NOVEL_CHARACTER_NOT_FOUND"})


async def test_merging_moves_names_memo_and_appearances_into_the_surviving_card(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """흡수되는 카드의 이름·별칭은 남는 카드 별칭으로, 메모는 `[이름] 메모` 로 뒤에 붙고, 나온 화가 옮겨진다. 두 카드가
    같은 화에 함께 나왔으면 연결은 하나로 준다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first, second = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=2)
    doyun = await _card(db_session, novel_id, "도윤", memo="소꿉친구")
    yuni = await _card(db_session, novel_id, "윤이", aliases=["윤"], memo="가끔 이렇게 불린다")
    db_session.add_all(
        [
            NovelChapterCharacter(chapter_id=first.id, character_id=doyun.id),
            NovelChapterCharacter(chapter_id=first.id, character_id=yuni.id),
            NovelChapterCharacter(chapter_id=second.id, character_id=yuni.id),
        ]
    )
    await db_session.commit()

    resp = await db_client.post(
        f"/novels/{novel_id}/characters/{yuni.id}/merge", json={"intoCharacterId": str(doyun.id)}
    )

    assert resp.status_code == 200, resp.text
    (survivor,) = resp.json()["items"]
    assert (survivor["id"], survivor["aliases"]) == (str(doyun.id), ["윤이", "윤"])
    assert survivor["memo"] == "소꿉친구\n\n[윤이] 가끔 이렇게 불린다"
    assert survivor["chapterIds"] == [str(first.id), str(second.id)]
    assert await db_session.get(NovelCharacter, yuni.id, populate_existing=True) is None


async def test_merging_into_a_card_without_a_memo_does_not_leave_a_blank_head(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    doyun = await _card(db_session, novel_id, "도윤")
    yuni = await _card(db_session, novel_id, "윤이", memo="메모")
    blank = await _card(db_session, novel_id, "윤", memo="  ")

    await db_client.post(f"/novels/{novel_id}/characters/{yuni.id}/merge", json={"intoCharacterId": str(doyun.id)})
    await db_client.post(f"/novels/{novel_id}/characters/{blank.id}/merge", json={"intoCharacterId": str(doyun.id)})
    itself = await db_client.post(
        f"/novels/{novel_id}/characters/{doyun.id}/merge", json={"intoCharacterId": str(doyun.id)}
    )

    assert await _cards(db_session, novel_id) == [("도윤", ["윤이", "윤"], "[윤이] 메모")]
    assert (itself.status_code, itself.json()["detail"]) == (422, {"code": "NOVEL_CHARACTER_MERGE_SELF"})


async def test_after_a_merge_the_generated_name_of_the_absorbed_card_links_to_the_surviving_card(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """합치기의 목적 — 생성 출력이 흡수된 카드 이름을 다시 내도 새 카드를 만들지 않고 남는 카드에 붙는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    doyun = await _card(db_session, novel_id, "도윤")
    yuni = await _card(db_session, novel_id, "윤이")
    merged = await db_client.post(
        f"/novels/{novel_id}/characters/{yuni.id}/merge", json={"intoCharacterId": str(doyun.id)}
    )
    assert merged.status_code == 200, merged.text
    messages = await _room_messages(db_session, room.room_id)
    job = await create_charged_job(
        db_session,
        job=NovelJob(
            novel_id=novel_id,
            user_id=room.user_id,
            kind="chapter_generate",
            start_message_id=messages[0].id,
            start_message_created_at=messages[0].created_at,
            end_message_id=room.turns[1][1].id,
            end_message_created_at=room.turns[1][1].created_at,
            episode_count_target=1,
        ),
        expected_cost=40,
        now=datetime.now(UTC),
    )
    body = "비가 내리는 저녁이었다. " * 30
    output = _batch_output(body).replace("등장인물: 서진, 도윤", "등장인물: 윤이")

    # 작업 실행이 여는 세션은 SAVEPOINT 로 붙인다 — 실행 경로의 롤백이 테스트 셋업까지 지우지 않게.
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    await runner.run_job(factory, _FakeLLMClient(tokens=[output]), job.id)

    chapter = await db_session.scalar(sa.select(NovelChapter).where(NovelChapter.novel_id == novel_id))
    assert chapter is not None
    linked = await db_session.scalars(
        sa.select(NovelChapterCharacter.character_id).where(NovelChapterCharacter.chapter_id == chapter.id)
    )
    assert linked.all() == [doyun.id]
    assert [name for name, _aliases, _memo in await _cards(db_session, novel_id)] == ["도윤"]
