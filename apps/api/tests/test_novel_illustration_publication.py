"""소설 화 삽화의 공개 — 공개 계획이 얼릴 개정의 삽화를 심사하고(통과 기억·운영자 내림·원작 권한·장수 상한), 두 변경 판정이
그림만 바뀐 화를 "바뀜"으로 보고, 독자·어드민 화 읽기가 심사를 거친 판의 그림만 문단 번호로 싣고, 운영자가 그림 하나를 모든
판에서 내린다.

심사 LLM 은 가짜다(`_ScreenLLM`) — 글 심사(지시문 분리 구조화 호출)는 늘 통과시키고, 그림 심사(이미지를 싣는 구조화 호출)는
미리 정한 판정을 앞에서부터 돌려준다. 저장소 내려받기도 가짜다 — 키마다 다른 바이트를 주고, 같은 바이트가 필요하면 `same_bytes`
표에 적는다. 배치는 배치 API 대신 개정·배치 행을 직접 넣어 만든다(그림 권한 판정은 배치 쓰기 시험의 몫이다)."""

import hashlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.content.publish import PublishFilterResult
from api.core.config import settings
from api.db.models import AdminActionLog, Asset, AssetKind, AssetStatus, Content, ModerationStatus, Novel, User
from api.db.models.novel import (
    NovelChapter,
    NovelChapterEdition,
    NovelChapterIllustration,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelIllustrationScreenPass,
    NovelIllustrationTakedown,
    NovelScreening,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novel_public import illustration_screening
from api.novel_public.screening import NovelScreenResult
from api.novelize.blocks import build_revision, copied_ids, fresh_ids
from factories import (
    PublicNovel,
    Room,
    _add_batch,
    _clear_llm_override,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_public_novel,
    _make_user,
    _make_user_with_clover_lot,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_BODY = "첫 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다."


# ── 가짜 ────────────────────────────────────────────────────────────────────
class _ScreenLLM(LLMClient):
    """글 심사는 늘 통과. 그림 심사는 `image_results` 를 앞에서부터(예외면 낸다), 비면 통과. `during_image_call` 이 있으면
    그림 판정을 돌려주기 전에 부른다."""

    def __init__(self) -> None:
        self.image_results: list[PublishFilterResult | Exception] = []
        self.image_calls: list[tuple[str, list[tuple[bytes, str]], LLMCallContext]] = []
        self.text_calls: list[str] = []
        self.during_image_call: Callable[[], Awaitable[None]] | None = None

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("심사는 스트리밍 생성을 쓰지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: type[T], images: Any = None, *, usage: LLMCallContext
    ) -> T:
        assert response_schema is PublishFilterResult
        self.image_calls.append((prompt, list(images or []), usage))
        if self.during_image_call is not None:
            await self.during_image_call()
        result = self.image_results.pop(0) if self.image_results else PublishFilterResult(passed=True, reason=None)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, response_schema)
        return result

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        assert response_schema is NovelScreenResult
        self.text_calls.append(prompt)
        result = NovelScreenResult(passed=True, flagged_parts=[], reason=None)
        assert isinstance(result, response_schema)
        return result


@pytest.fixture
def llm() -> Iterator[_ScreenLLM]:
    fake = _ScreenLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


@pytest.fixture
def same_bytes(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """저장소 키 → 바이트. 표에 없는 키는 키 자체를 바이트로 준다(자산마다 다른 그림)."""
    table: dict[str, bytes] = {}

    def download(key: str) -> bytes:
        return table.get(key, key.encode())

    monkeypatch.setattr(illustration_screening, "download_object", download)
    return table


@pytest.fixture(autouse=True)
def _switches_on(monkeypatch: pytest.MonkeyPatch, same_bytes: dict[str, bytes]) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_illustrations_enabled", True)


# ── 준비 ────────────────────────────────────────────────────────────────────
@dataclass
class _Setup:
    room: Room
    novel_id: uuid.UUID
    chapters: list[NovelChapter]


async def _novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, chapters: int = 2
) -> _Setup:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    messages = await _room_messages(db_session, room.room_id)
    added = await _add_batch(db_session, novel_id, room, messages[0], messages[-1], episodes=chapters, body=_BODY)
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(synopsis="두 사람의 첫 만남."))
    await db_session.commit()
    return _Setup(room, novel_id, added)


async def _asset(db: AsyncSession, owner_id: uuid.UUID, *, prefix: str = "assets/generated/") -> Asset:
    kind = AssetKind.ORIGINAL if prefix == "assets/novel-illustration/" else AssetKind.GENERATED
    asset = Asset(
        owner_user_id=owner_id,
        storage_key=f"{prefix}{uuid.uuid4()}.webp",
        kind=kind,
        status=AssetStatus.READY,
        width=300,
        height=400,
    )
    db.add(asset)
    await db.commit()
    return asset


def _display_key(asset: Asset) -> str:
    return asset.storage_key.removesuffix(".webp") + "_display.webp"


async def _current(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


# (문단 번호, 앞뒤, 그림, 출처[, 저장할 순서 값]) — 순서 값을 비우면 같은 자리 안 목록 순서다.
Spot = tuple[Any, ...]


async def _stack(
    db: AsyncSession, chapter: NovelChapter, spots: list[Spot], *, body: str | None = None, new_ids: bool = False
) -> NovelChapterRevision:
    """지금 개정 위에 새 개정(출처 `illustration`)을 쌓고 그 배치를 `spots` 로 쓴다. `new_ids` 면 문단 블록 id 를 새로 받는다."""
    current = await _current(db, chapter.id)
    text = current.body if body is None else body
    revision = build_revision(
        chapter_id=chapter.id,
        revision_no=current.revision_no + 1,
        body=text,
        source="illustration",
        block_ids=fresh_ids(text) if new_ids or body is not None else copied_ids(current),
    )
    db.add(revision)
    await db.flush()
    used: dict[tuple[int, str], int] = {}
    for spot in spots:
        paragraph, placement, asset, source = spot[:4]
        order = spot[4] if len(spot) > 4 else used.get((paragraph, placement), 0)
        used[(paragraph, placement)] = order + 1
        db.add(
            NovelChapterIllustration(
                revision_id=revision.id,
                anchor_block_id=revision.block_ids[paragraph],
                placement=placement,
                sort_order=order,
                asset_id=asset.id,
                source=source,
            )
        )
    await db.commit()
    return revision


async def _publish(
    db_client: httpx.AsyncClient, novel_id: uuid.UUID, chapter: NovelChapter, *, summary: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"chapterId": str(chapter.id)}
    if summary is not None:
        body["changeSummary"] = summary
    return await db_client.post(f"/novels/{novel_id}/publication", json=body)


async def _frozen(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterPublication | None:
    frozen: NovelChapterPublication | None = await db.scalar(
        sa.select(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter_id)
        .execution_options(populate_existing=True)
    )
    return frozen


async def _screenings(db: AsyncSession, novel_id: uuid.UUID) -> list[tuple[str, list[str]]]:
    rows = await db.execute(
        sa.select(NovelScreening.outcome, NovelScreening.flagged_parts)
        .where(NovelScreening.novel_id == novel_id)
        .order_by(NovelScreening.created_at, NovelScreening.id)
    )
    return [(outcome, list(parts)) for outcome, parts in rows.tuples()]


async def _status(db_client: httpx.AsyncClient, novel_id: uuid.UUID) -> dict[str, Any]:
    resp = await db_client.get(f"/novels/{novel_id}/publication")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


# ── 공개 심사 ────────────────────────────────────────────────────────────────
async def test_publishing_a_chapter_screens_its_pictures_once_and_marks_the_frozen_chapter_screened(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """얼릴 개정의 문단에 붙은 그림을 크게 그리는 변형으로 한 번에 심사하고, 통과하면 공개본·판에 심사 시각을 찍는다. 위치 확인
    필요인 그림은 독자에게 안 나가므로 심사하지 않는다. 깨지는 시나리오: 그림이 심사 없이 판에 얼거나, 심사 시각이 비어 켠 뒤에도
    그림이 안 보인다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    one = await _asset(db_session, setup.room.user_id)
    two = await _asset(db_session, setup.room.user_id, prefix="assets/novel-illustration/")
    unplaced = await _asset(db_session, setup.room.user_id)
    revision = await _stack(db_session, chapter, [(0, "after", one, "generated"), (2, "before", two, "upload")])
    db_session.add(
        NovelChapterIllustration(revision_id=revision.id, sort_order=0, asset_id=unplaced.id, source="generated")
    )
    await db_session.commit()

    resp = await _publish(db_client, setup.novel_id, chapter)

    assert resp.status_code == 200, resp.text
    (prompt, images, usage) = llm.image_calls[0]
    assert len(llm.image_calls) == 1
    assert [data for data, _ in images] == [_display_key(one).encode(), _display_key(two).encode()]
    assert usage.call_site == "novel_illustration_screen"
    assert "1문단 뒤" in prompt and "3문단 앞" in prompt
    frozen = await _frozen(db_session, chapter.id)
    assert frozen is not None and frozen.revision_id == revision.id
    assert frozen.illustrations_screened_at is not None
    edition = await db_session.get_one(NovelChapterEdition, (chapter.id, 1), populate_existing=True)
    assert edition.illustrations_screened_at == frozen.illustrations_screened_at
    passes = (await db_session.scalars(sa.select(NovelIllustrationScreenPass.content_sha256))).all()
    assert set(passes) >= {hashlib.sha256(_display_key(one).encode()).hexdigest()}
    recorded = {
        asset.id: asset.display_sha256
        for asset in (
            await db_session.scalars(
                sa.select(Asset)
                .where(Asset.id.in_([one.id, two.id, unplaced.id]))
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    assert recorded == {
        one.id: hashlib.sha256(_display_key(one).encode()).hexdigest(),
        two.id: hashlib.sha256(_display_key(two).encode()).hexdigest(),
        unplaced.id: None,
    }


async def test_a_rejected_picture_freezes_nothing_and_records_an_illustration_rejection(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """그림 심사가 거부하면 공개본·판을 쓰지 않고 거부 기록의 자리에 삽화를 남긴다. 깨지는 시나리오: 걸린 그림이 독자에게
    나간다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(1, "after", picture, "generated")])
    llm.image_results.append(PublishFilterResult(passed=False, reason="기준에 걸린다"))

    resp = await _publish(db_client, setup.novel_id, chapter)

    assert resp.status_code == 400
    assert resp.json()["detail"] == {"code": "NOVEL_SCREENING_REJECTED", "chapterOrdinal": 1, "flaggedParts": ["illustration"]}
    assert await _frozen(db_session, chapter.id) is None
    assert await _screenings(db_session, setup.novel_id) == [("rejected", ["illustration"])]
    assert (await _status(db_client, setup.novel_id))["lastScreening"]["flaggedParts"] == ["illustration"]
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(NovelIllustrationScreenPass))) == 0


@pytest.mark.parametrize("failure", ["llm", "download"])
async def test_a_screening_or_download_failure_is_503_and_writes_nothing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScreenLLM,
    failure: str,
) -> None:
    """심사 호출이나 그림 내려받기가 실패하면 판정이 없으므로 공개하지 않는다(fail-closed). 깨지는 시나리오: 장애 중에 미심사
    그림이 얼린다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "before", picture, "generated")])
    if failure == "llm":
        llm.image_results.append(LLMClientError("down"))
    else:
        from botocore.exceptions import ClientError

        def broken(key: str) -> bytes:
            raise ClientError({"Error": {"Code": "500"}}, "GetObject")

        monkeypatch.setattr(illustration_screening, "download_object", broken)

    resp = await _publish(db_client, setup.novel_id, chapter)

    assert (resp.status_code, resp.json()["detail"]["code"]) == (503, "NOVEL_SCREENING_UNAVAILABLE")
    assert await _frozen(db_session, chapter.id) is None
    assert await _screenings(db_session, setup.novel_id) == []


async def test_a_placement_change_while_screening_is_a_conflict_and_freezes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """심사를 기다리는 사이 그림을 바꾸면(새 개정) 심사한 그림과 얼릴 그림이 달라지므로 409 이고 아무것도 쓰지 않는다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    first = await _asset(db_session, setup.room.user_id)
    other = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", first, "generated")])

    async def swap() -> None:
        await _stack(db_session, chapter, [(0, "after", other, "generated")])

    llm.during_image_call = swap
    resp = await _publish(db_client, setup.novel_id, chapter)

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_PUBLISH_CONFLICT")
    assert await _frozen(db_session, chapter.id) is None


async def test_the_same_bytes_are_screened_once_per_model_and_prompt_version(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScreenLLM,
    same_bytes: dict[str, bytes],
) -> None:
    """통과한 바이트는 다른 자산이어도 다시 심사하지 않는다(같은 모델·같은 심사 문안 판). 모델이 바뀌거나, 다른 문안 판으로만
    통과한 기억이면 다시 심사한다. 깨지는 시나리오: 같은 그림을 화마다 다시 심사해 원가가 쌓이거나, 문안을 강화한 뒤에도 옛
    문안의 통과로 건너뛴다."""
    setup = await _novel(db_client, db_session, monkeypatch, chapters=3)
    first = await _asset(db_session, setup.room.user_id)
    copy = await _asset(db_session, setup.room.user_id, prefix="assets/novel-illustration/")
    third = await _asset(db_session, setup.room.user_id)
    for asset in (first, copy, third):
        same_bytes[_display_key(asset)] = b"same-picture"
    await _stack(db_session, setup.chapters[0], [(0, "after", first, "generated")])
    await _stack(db_session, setup.chapters[1], [(1, "after", copy, "upload")])
    await _stack(db_session, setup.chapters[2], [(2, "after", third, "generated")])
    sha = hashlib.sha256(b"same-picture").hexdigest()

    assert (await _publish(db_client, setup.novel_id, setup.chapters[0])).status_code == 200
    assert (await _publish(db_client, setup.novel_id, setup.chapters[1])).status_code == 200
    calls_after_copy = len(llm.image_calls)
    await db_session.execute(
        sa.update(NovelIllustrationScreenPass)
        .where(NovelIllustrationScreenPass.content_sha256 == sha)
        .values(prompt_version="an-older-prompt")
    )
    await db_session.commit()
    assert (await _publish(db_client, setup.novel_id, setup.chapters[2])).status_code == 200

    assert calls_after_copy == 1
    assert len(llm.image_calls) == 2
    monkeypatch.setattr(settings, "gemini_publish_filter_model_name", "another-model")
    await _stack(db_session, setup.chapters[2], [(0, "before", third, "generated")])
    assert (await _publish(db_client, setup.novel_id, setup.chapters[2])).status_code == 200
    assert len(llm.image_calls) == 3


async def test_a_taken_down_picture_blocks_publishing_before_the_pass_memory(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScreenLLM,
    same_bytes: dict[str, bytes],
) -> None:
    """운영자가 내린 바이트는 통과 기억이 있어도 공개를 막는다(다시 올린 새 자산도). 심사 호출 없이 거부로 남긴다. 깨지는
    시나리오: 내린 그림을 같은 파일로 다시 올려 공개하면 통과 기억 덕에 심사 없이 다시 나간다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    reupload = await _asset(db_session, setup.room.user_id, prefix="assets/novel-illustration/")
    same_bytes[_display_key(reupload)] = b"taken-down-picture"
    sha = hashlib.sha256(b"taken-down-picture").hexdigest()
    db_session.add(NovelIllustrationTakedown(content_sha256=sha, asset_id=uuid.uuid4(), reason="운영 정책 위반"))
    db_session.add(
        NovelIllustrationScreenPass(
            content_sha256=sha,
            model=settings.gemini_publish_filter_model_name or settings.gemini_model_name,
            prompt_version="any",
        )
    )
    await db_session.commit()
    await _stack(db_session, chapter, [(0, "after", reupload, "upload")])

    resp = await _publish(db_client, setup.novel_id, chapter)

    assert (resp.status_code, resp.json()["detail"]["flaggedParts"]) == (400, ["illustration"])
    assert llm.image_calls == []
    assert await _frozen(db_session, chapter.id) is None
    assert await _screenings(db_session, setup.novel_id) == [("rejected", ["illustration"])]


async def test_a_rejection_for_taken_down_bytes_names_the_pictures_that_carry_them(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScreenLLM,
    same_bytes: dict[str, bytes],
) -> None:
    """내린 바이트로 거부할 때 그 바이트를 담은 그림의 자산 id 를 한 번씩 싣는다(작가 화면이 어느 그림인지 가리킨다). 거부 기록은
    지금처럼 하나다. 깨지는 시나리오: 작가가 어느 그림을 떼야 하는지 몰라 다시 눌러 거부 상한을 또 쓴다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    fine = await _asset(db_session, setup.room.user_id)
    reupload = await _asset(db_session, setup.room.user_id, prefix="assets/novel-illustration/")
    same_bytes[_display_key(reupload)] = b"taken-down-picture"
    sha = hashlib.sha256(b"taken-down-picture").hexdigest()
    db_session.add(NovelIllustrationTakedown(content_sha256=sha, asset_id=uuid.uuid4(), reason="운영 정책 위반"))
    await db_session.commit()
    await _stack(
        db_session,
        chapter,
        [(0, "after", fine, "generated"), (1, "after", reupload, "upload"), (2, "before", reupload, "upload")],
    )

    resp = await _publish(db_client, setup.novel_id, chapter)

    assert resp.status_code == 400
    assert resp.json()["detail"] == {
        "code": "NOVEL_SCREENING_REJECTED",
        "chapterOrdinal": 1,
        "flaggedParts": ["illustration"],
        "takenDownAssetIds": [str(reupload.id)],
    }
    assert await _screenings(db_session, setup.novel_id) == [("rejected", ["illustration"])]
    # 거부돼도 내려받은 바이트의 sha 는 자산 행에 남는다 — 이미 얼린 다른 판의 그 자산도 읽기에서 내린 그림이 된다.
    assert (await db_session.get_one(Asset, reupload.id, populate_existing=True)).display_sha256 == sha


async def test_a_chapter_with_more_than_ten_placed_pictures_is_not_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """한 화의 삽화는 10장까지다 — 넘는 개정은 심사를 부르기 전에 409. 깨지는 시나리오: 상한 밖 장수가 심사 원가·독자 화면을
    키운다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    pictures = [await _asset(db_session, setup.room.user_id) for _ in range(11)]
    await _stack(db_session, chapter, [(index % 3, "after", picture, "generated") for index, picture in enumerate(pictures)])

    resp = await _publish(db_client, setup.novel_id, chapter)

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_ILLUSTRATION_LIMIT_EXCEEDED")
    assert (llm.image_calls, llm.text_calls) == ([], [])


async def test_attaching_an_eleventh_picture_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """붙이기도 같은 상한을 지킨다(위치 확인 필요인 그림도 센다 — 다시 놓으면 화에 나가는 그림이다)."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    pictures = [await _asset(db_session, setup.room.user_id) for _ in range(11)]
    current = await _stack(db_session, chapter, [(index % 3, "after", pictures[index], "generated") for index in range(10)])

    resp = await db_client.post(
        f"/novels/{setup.novel_id}/chapters/{chapter.id}/illustrations",
        json={
            "baseRevisionId": str(current.id),
            "anchorBlockId": str(current.block_ids[0]),
            "placement": "before",
            "assetId": str(pictures[10].id),
            "source": "generated",
        },
    )

    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "NOVEL_ILLUSTRATION_LIMIT_EXCEEDED")
    assert (await _current(db_session, chapter.id)).id == current.id


async def _hand_source_to(db: AsyncSession, novel_id: uuid.UUID, permission: str) -> Content:
    other = _make_user()
    db.add(other)
    await db.flush()
    novel = await db.get_one(Novel, novel_id)
    source = await db.get_one(Content, novel.content_id)
    source.creator_user_id = other.id
    source.novel_permission = permission  # type: ignore[assignment]
    await db.commit()
    return source


async def test_an_original_picture_needs_the_originals_public_permission_unless_the_serial_is_locked(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """남의 원작 그림이 든 화는 원작의 소설화 허락이 공개가 아니면 공개하지 않는다. 내 그림·업로드만이면 그대로 공개한다. 연재권
    잠금이 효력이 있으면(정책 스위치 켜짐) 글과 같이 원작 그림도 계속 낸다. 깨지는 시나리오: 비공개 소장만 허락한 원작의 그림이
    노벨에 나가거나, 잠긴 소설이 다음 화를 못 낸다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    first, second = setup.chapters
    assert (await _publish(db_client, setup.novel_id, first)).status_code == 200
    assert (await _publish(db_client, setup.novel_id, second)).status_code == 200
    source = await _hand_source_to(db_session, setup.novel_id, "private")
    original = await _asset(db_session, source.creator_user_id, prefix="assets/situational-image/")
    mine = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, second, [(0, "after", original, "original")])
    await _stack(db_session, first, [(0, "after", mine, "generated")])

    refused = await _publish(db_client, setup.novel_id, second)
    own_only = await _publish(db_client, setup.novel_id, first)
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)
    locked = await _publish(db_client, setup.novel_id, second, summary="그림을 더했어요")

    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "NOVEL_ILLUSTRATION_ORIGINAL_NOT_PUBLISHABLE")
    assert own_only.status_code == 200
    assert locked.status_code == 200, locked.text
    assert len(llm.image_calls) == 2


async def test_an_original_picture_readers_already_see_keeps_going_out_after_the_permission_drops(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """원작 허락이 공개일 때 심사를 거쳐 나간 원작 그림은 허락이 비공개로 바뀐 뒤에도 그 화를 고쳐 다시 내면 그대로 나간다(글이
    이미 공개한 것을 이어 가는 것과 같다). 새로 붙인 원작 그림만 막는다. 깨지는 시나리오: 독자가 계속 보는 그림 때문에 오타 하나
    고친 다시 공개가 거절된다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    source = await _hand_source_to(db_session, setup.novel_id, "public")
    shown = await _asset(db_session, source.creator_user_id, prefix="assets/situational-image/")
    extra = await _asset(db_session, source.creator_user_id, prefix="assets/situational-image/")
    await _stack(db_session, chapter, [(0, "after", shown, "original")])
    assert (await _publish(db_client, setup.novel_id, chapter)).status_code == 200
    source.novel_permission = "private"
    await db_session.commit()

    await _stack(db_session, chapter, [(0, "after", shown, "original")], body="고친 첫 문단.\n\n둘째 문단이다.")
    typo_fix = await _publish(db_client, setup.novel_id, chapter)
    await _stack(db_session, chapter, [(0, "after", shown, "original"), (1, "before", extra, "original")])
    added = await _publish(db_client, setup.novel_id, chapter)

    assert typo_fix.status_code == 200, typo_fix.text
    assert (added.status_code, added.json()["detail"]["code"]) == (409, "NOVEL_ILLUSTRATION_ORIGINAL_NOT_PUBLISHABLE")


async def test_a_takedown_during_screening_is_seen_after_locking(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScreenLLM,
    same_bytes: dict[str, bytes],
) -> None:
    """심사를 기다리는 사이 운영자가 그 바이트를 내리면, 심사가 통과해도 잠근 뒤 다시 보고 거부한다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    same_bytes[_display_key(picture)] = b"reported-picture"
    await _stack(db_session, chapter, [(0, "after", picture, "generated")])

    async def take_down() -> None:
        db_session.add(
            NovelIllustrationTakedown(
                content_sha256=hashlib.sha256(b"reported-picture").hexdigest(), asset_id=picture.id, reason="신고"
            )
        )
        await db_session.commit()

    llm.during_image_call = take_down
    resp = await _publish(db_client, setup.novel_id, chapter)

    assert (resp.status_code, resp.json()["detail"]["flaggedParts"]) == (400, ["illustration"])
    assert resp.json()["detail"]["takenDownAssetIds"] == [str(picture.id)]
    assert await _frozen(db_session, chapter.id) is None


# ── 변경 판정 ────────────────────────────────────────────────────────────────
async def test_a_picture_only_change_is_a_changed_chapter_in_status_and_republishing_makes_a_new_edition(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """글은 같고 그림만 바뀐 공개 화는 작가 상태의 "바뀐 공개 화"이고, 다시 공개하면 새 판이 된다 — 글은 다시 심사하지 않고
    그림만 심사한다. 깨지는 시나리오: 그림만 바꾼 화는 다시 공개를 눌러도 아무것도 쓰이지 않는다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    assert (await _publish(db_client, setup.novel_id, chapter)).status_code == 200
    text_calls = len(llm.text_calls)
    picture = await _asset(db_session, setup.room.user_id)
    revision = await _stack(db_session, chapter, [(1, "before", picture, "generated")])

    changed = (await _status(db_client, setup.novel_id))["changedChapterOrdinals"]
    resp = await _publish(db_client, setup.novel_id, chapter)

    assert changed == [1]
    assert resp.status_code == 200, resp.text
    frozen = await _frozen(db_session, chapter.id)
    assert frozen is not None and (frozen.edition, frozen.revision_id) == (2, revision.id)
    assert len(llm.text_calls) == text_calls
    assert len(llm.image_calls) == 1
    assert (await _status(db_client, setup.novel_id))["changedChapterOrdinals"] == []


async def test_two_revisions_showing_the_same_pictures_are_not_a_change(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """화면이 같으면 바뀌지 않은 화다 — 문단 블록 id 가 새로 바뀌었거나, 뗀 뒤 남은 그림의 순서 값만 다른 개정. 출처가
    다르면(원작 이미지 표시가 달라진다) 바뀐 화다. 깨지는 시나리오: 화면이 같은데 변경 요약을 요구하고 판이 올라간다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(1, "after", picture, "generated")])
    assert (await _publish(db_client, setup.novel_id, chapter)).status_code == 200

    await _stack(db_session, chapter, [(1, "after", picture, "generated", 1)], new_ids=True)
    unchanged = (await _status(db_client, setup.novel_id))["changedChapterOrdinals"]
    again = await _publish(db_client, setup.novel_id, chapter)
    frozen = await _frozen(db_session, chapter.id)
    await _stack(db_session, chapter, [(1, "after", picture, "upload")])
    by_source = (await _status(db_client, setup.novel_id))["changedChapterOrdinals"]

    assert unchanged == []
    assert again.status_code == 200
    assert frozen is not None and frozen.edition == 1
    assert by_source == [1]


async def test_with_the_switch_off_pictures_are_frozen_unscreened_and_stay_hidden_until_republished(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """스위치가 꺼진 동안의 공개는 그림을 심사하지 않고(원작 권한도 보지 않는다) 심사 시각을 비운 채 얼린다 — 독자에게 안
    보이므로 미심사 공개가 아니다. 켠 뒤에는 그 화가 "바뀐 공개 화"로 보이고 다시 공개하면 심사를 거쳐 그림이 열린다. 깨지는
    시나리오: 꺼진 동안 승계된 그림이 심사 없이 판에 얼었다가 켜는 순간 독자에게 나간다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", picture, "generated")])
    monkeypatch.setattr(settings, "novel_illustrations_enabled", False)

    off = await _publish(db_client, setup.novel_id, chapter)
    frozen_off = await _frozen(db_session, chapter.id)
    assert frozen_off is not None
    screened_off = frozen_off.illustrations_screened_at
    changed_off = (await _status(db_client, setup.novel_id))["changedChapterOrdinals"]
    monkeypatch.setattr(settings, "novel_illustrations_enabled", True)
    changed_on = (await _status(db_client, setup.novel_id))["changedChapterOrdinals"]
    on = await _publish(db_client, setup.novel_id, chapter)
    frozen_on = await _frozen(db_session, chapter.id)

    assert off.status_code == 200
    assert screened_off is None
    assert changed_off == []
    assert changed_on == [1]
    assert on.status_code == 200
    assert len(llm.image_calls) == 1
    assert frozen_on is not None and frozen_on.edition == 2 and frozen_on.illustrations_screened_at is not None


async def test_republishing_text_with_the_switch_off_clears_the_screened_mark(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """켜진 동안 심사해 얼린 화를 꺼진 동안 글만 고쳐 다시 내면, 새로 얼린 개정의 그림은 심사하지 않았으므로 표시를 비운다.
    깨지는 시나리오: 앞 판의 심사 표시가 남아 꺼진 동안 바뀐 그림이 켜는 순간 독자에게 나간다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    other = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", picture, "generated")])
    assert (await _publish(db_client, setup.novel_id, chapter)).status_code == 200
    screened = await _frozen(db_session, chapter.id)
    assert screened is not None and screened.illustrations_screened_at is not None
    await _stack(db_session, chapter, [(0, "after", other, "generated")], body="새 첫 문단.\n\n둘째.")
    monkeypatch.setattr(settings, "novel_illustrations_enabled", False)

    resp = await _publish(db_client, setup.novel_id, chapter)

    frozen = await _frozen(db_session, chapter.id)
    assert resp.status_code == 200
    assert frozen is not None and frozen.edition == 2 and frozen.illustrations_screened_at is None
    edition = await db_session.get_one(NovelChapterEdition, (chapter.id, 2), populate_existing=True)
    assert edition.illustrations_screened_at is None


async def test_a_republish_by_code_that_does_not_know_the_screened_mark_hides_the_pictures_and_shows_as_changed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _ScreenLLM
) -> None:
    """심사 시각을 모르는 코드(되돌린 이미지)가 다시 내면 개정·판·공개 시각만 바뀌고 앞 판의 심사 시각이 남는다. 공개 시각과 다른
    심사 시각은 심사하지 않은 판으로 본다 — 독자에게 그림이 없고, 작가 상태에는 바뀐 화로 보여 다시 공개하면 심사를 거친다.
    깨지는 시나리오: 되돌린 동안 붙인 미심사 그림이 남은 시각 덕에 다시 올린 뒤 독자에게 나간다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    first = await _asset(db_session, setup.room.user_id)
    unscreened = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", first, "generated")])
    assert (await _publish(db_client, setup.novel_id, chapter)).status_code == 200
    revision = await _stack(db_session, chapter, [(0, "after", unscreened, "generated")])
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter.id)
        .values(
            revision_id=revision.id,
            edition=NovelChapterPublication.edition + 1,
            published_at=NovelChapterPublication.published_at + sa.text("interval '1 second'"),
        )
    )
    await db_session.commit()

    changed = (await _status(db_client, setup.novel_id))["changedChapterOrdinals"]
    reader = await _reader(db_session)
    shown = await _read(db_client, f"/webnovels/{setup.novel_id}/chapters/{chapter.id}", reader)

    assert changed == [1]
    assert shown["illustrations"] == []


# ── 독자·어드민 읽기 ─────────────────────────────────────────────────────────
async def _public(db: AsyncSession) -> PublicNovel:
    publisher = _make_user()
    db.add(publisher)
    await db.flush()
    novel = await _make_public_novel(db, publisher.id)
    await db.commit()
    return novel


async def _freeze_pictures(
    db: AsyncSession, novel: PublicNovel, ordinal: int, spots: list[Spot], *, screened: bool = True, edition: int = 1
) -> NovelChapterRevision:
    """공개 화 `ordinal` 에 `spots` 를 붙인 개정을 얼린다(공개본과 그 판 행). `screened` 면 심사 시각을 찍는다."""
    chapter = await db.get_one(NovelChapter, novel.chapter_ids[ordinal - 1])
    revision = await _stack(db, chapter, spots, body=_BODY)
    mark = sa.func.now() if screened else None
    await db.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == chapter.id)
        .values(revision_id=revision.id, edition=edition, illustrations_screened_at=mark)
    )
    frozen = await _frozen(db, chapter.id)
    assert frozen is not None
    db.add(
        NovelChapterEdition(
            chapter_id=chapter.id,
            edition=edition,
            novel_id=novel.novel_id,
            revision_id=revision.id,
            title=frozen.title,
            author_note=frozen.author_note,
            published_at=frozen.published_at,
            illustrations_screened_at=frozen.illustrations_screened_at,
        )
    )
    await db.commit()
    return revision


def _path(novel: PublicNovel, ordinal: int) -> str:
    return f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[ordinal - 1]}"


async def _read(client: httpx.AsyncClient, path: str, reader: uuid.UUID) -> dict[str, Any]:
    await _login_as(client, reader)
    resp = await client.get(path)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _shown(chapter: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (item["paragraphIndex"], item["placement"], item["order"], item["source"], item["url"] is not None, item["withheld"])
        for item in chapter["illustrations"]
    ]


async def _reader(db: AsyncSession) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db, clover_balance=100)
    await db.commit()
    return user.id


async def test_a_reader_sees_the_screened_pictures_by_paragraph_with_the_original_ones_flagged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """독자 화 응답은 심사를 거친 판의 그림을 문단 번호·앞뒤·자리 안 순서·출처와 주소·크기로 싣는다. 위치 확인 필요인 그림은
    싣지 않는다."""
    novel = await _public(db_session)
    mine = await _asset(db_session, novel.publisher_id)
    original = await _asset(db_session, novel.publisher_id, prefix="assets/situational-image/")
    await _freeze_pictures(db_session, novel, 1, [(0, "after", mine, "generated"), (0, "after", original, "original")])
    reader = await _reader(db_session)

    chapter = await _read(db_client, _path(novel, 1), reader)

    assert _shown(chapter) == [(0, "after", 0, "generated", True, None), (0, "after", 1, "original", True, None)]
    assert (chapter["illustrations"][0]["width"], chapter["illustrations"][0]["height"]) == (300, 400)
    assert chapter["illustrations"][0]["url"].split("?")[0].endswith("_display.webp")


@pytest.mark.parametrize("case", ["switch_off", "unscreened", "locked"])
async def test_a_reader_gets_no_pictures_when_the_switch_is_off_the_edition_is_unscreened_or_the_chapter_is_locked(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """스위치가 꺼졌거나, 그 판이 삽화를 심사하지 않았거나, 소장하지 않은 유료 화면 그림이 없다."""
    novel = await _public(db_session)
    picture = await _asset(db_session, novel.publisher_id)
    ordinal = 6 if case == "locked" else 1
    await _freeze_pictures(db_session, novel, ordinal, [(0, "after", picture, "generated")], screened=case != "unscreened")
    if case == "switch_off":
        monkeypatch.setattr(settings, "novel_illustrations_enabled", False)

    chapter = await _read(db_client, _path(novel, ordinal), await _reader(db_session))

    assert chapter["illustrations"] == []


async def test_a_buyer_reading_the_bought_edition_sees_its_pictures_and_the_latest_shows_the_new_ones(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """산 사람이 산 때의 판(1판)을 고르면 그 판의 그림을, 기본(지금 판)은 바꾼 그림을 본다."""
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)
    novel = await _public(db_session)
    old = await _asset(db_session, novel.publisher_id)
    new = await _asset(db_session, novel.publisher_id)
    await _freeze_pictures(db_session, novel, 6, [(0, "before", old, "generated")])
    buyer = await _reader(db_session)
    await _login_as(db_client, buyer)
    bought = await db_client.post(f"{_path(novel, 6)}/purchase", json={"expectedPrice": 30})
    assert bought.status_code == 200, bought.text
    await _freeze_pictures(db_session, novel, 6, [(0, "after", new, "upload")], edition=2)

    latest = await _read(db_client, _path(novel, 6), buyer)
    first = await _read(db_client, f"{_path(novel, 6)}?edition=1", buyer)

    assert (latest["edition"], _shown(latest)) == (2, [(0, "after", 0, "upload", True, None)])
    assert (first["edition"], _shown(first)) == (1, [(0, "before", 0, "generated", True, None)])


async def test_an_operator_restricted_original_withholds_only_its_pictures_and_a_withdrawn_creator_keeps_them(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """운영자가 원작을 이용제한하면(판매만 멈추기로 해 소장자는 계속 읽는다) 그 원작 그림 자리에 사유만 남고 다른 그림·글은
    그대로다. 원작자가 탈퇴한 것만으로는 원작 그림을 빼지 않는다."""
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)
    novel = await _public(db_session)
    mine = await _asset(db_session, novel.publisher_id)
    original = await _asset(db_session, novel.publisher_id, prefix="assets/situational-image/")
    await _freeze_pictures(db_session, novel, 6, [(0, "after", original, "original"), (0, "after", mine, "generated")])
    buyer = await _reader(db_session)
    await _login_as(db_client, buyer)
    assert (await db_client.post(f"{_path(novel, 6)}/purchase", json={"expectedPrice": 30})).status_code == 200
    creator = (await db_session.get_one(Content, novel.content_id)).creator_user_id

    await db_session.execute(sa.update(User).where(User.id == creator).values(deleted_at=sa.func.now()))
    await db_session.commit()
    withdrawn = await _read(db_client, _path(novel, 6), buyer)
    await db_session.execute(
        sa.update(Content)
        .where(Content.id == novel.content_id)
        .values(moderation_status=ModerationStatus.RESTRICTED, novel_buyers_kept=True)
    )
    await db_session.commit()
    restricted = await _read(db_client, _path(novel, 6), buyer)

    assert _shown(withdrawn) == [(0, "after", 0, "original", True, None), (0, "after", 1, "generated", True, None)]
    assert _shown(restricted) == [
        (0, "after", 0, "original", False, "original_restricted"),
        (0, "after", 1, "generated", True, None),
    ]
    assert restricted["paragraphs"] == withdrawn["paragraphs"]


async def test_an_original_restricted_only_by_its_creators_suspension_keeps_its_pictures(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """원작자 정지로 원작이 일괄 제한된 것은 원작자 탈퇴처럼 원작 그림을 그대로 보인다(소장자 열람이 정지 제한을 정상과 같이
    보는 것과 같다). 그림을 비우는 것은 운영자가 그 원작 작품을 직접 제한했을 때뿐이다. 깨지는 시나리오: 원작자 계정 정지 하나로
    남의 유료 소설의 그림이 모두 빈 자리가 된다."""
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)
    novel = await _public(db_session)
    original = await _asset(db_session, novel.publisher_id, prefix="assets/situational-image/")
    await _freeze_pictures(db_session, novel, 6, [(0, "after", original, "original")])
    buyer = await _reader(db_session)
    await _login_as(db_client, buyer)
    assert (await db_client.post(f"{_path(novel, 6)}/purchase", json={"expectedPrice": 30})).status_code == 200
    await db_session.execute(
        sa.update(Content)
        .where(Content.id == novel.content_id)
        .values(moderation_status=ModerationStatus.RESTRICTED, restricted_by_suspension=True)
    )
    await db_session.commit()

    suspended = await _read(db_client, _path(novel, 6), buyer)

    assert _shown(suspended) == [(0, "after", 0, "original", True, None)]


async def test_the_admin_chapter_view_carries_the_pictures_readers_get_with_their_asset_ids(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = await _public(db_session)
    picture = await _asset(db_session, novel.publisher_id)
    await _freeze_pictures(db_session, novel, 1, [(2, "before", picture, "generated")])
    await _login_as_admin(db_client, await _create_admin(db_session))
    path = f"/admin/novels/{novel.novel_id}/chapters/{novel.chapter_ids[0]}"

    shown = (await db_client.get(path)).json()["illustrations"]
    monkeypatch.setattr(settings, "novel_illustrations_enabled", False)
    off = (await db_client.get(path)).json()["illustrations"]

    assert [(item["paragraphIndex"], item["placement"], item["assetId"], item["withheld"]) for item in shown] == [
        (2, "before", str(picture.id), None)
    ]
    assert off == []


# ── 운영자 내림 ──────────────────────────────────────────────────────────────
async def test_an_operator_takes_a_picture_down_from_every_edition_and_its_bytes_cannot_come_back(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _ScreenLLM,
    same_bytes: dict[str, bytes],
) -> None:
    """내림은 그 그림의 바이트 sha 를 남기고 통과 기억을 지운다. 모든 판의 그 자리는 운영자 사유만 남고 글은 그대로다. 같은
    그림을 두 번 내리면 409, 배치에 쓰인 적 없는 자산은 404, 사유가 비면 422. 감사 로그에 남는다."""
    novel = await _public(db_session)
    picture = await _asset(db_session, novel.publisher_id)
    same_bytes[_display_key(picture)] = b"bad-picture"
    sha = hashlib.sha256(b"bad-picture").hexdigest()
    await _freeze_pictures(db_session, novel, 1, [(0, "after", picture, "generated")])
    await _freeze_pictures(db_session, novel, 2, [(1, "after", picture, "generated")])
    db_session.add(NovelIllustrationScreenPass(content_sha256=sha, model="m", prompt_version="p"))
    await db_session.commit()
    stranger = await _asset(db_session, novel.publisher_id)
    admin = await _create_admin(db_session)
    await _login_as_admin(db_client, admin)
    url = f"/admin/novel-illustrations/{picture.id}/takedown"

    blank = await db_client.post(url, json={"reason": "  "})
    done = await db_client.post(url, json={"reason": "운영정책 위반 그림"})
    twice = await db_client.post(url, json={"reason": "다시"})
    unused = await db_client.post(f"/admin/novel-illustrations/{stranger.id}/takedown", json={"reason": "x"})
    reader = await _reader(db_session)
    first = await _read(db_client, _path(novel, 1), reader)
    second = await _read(db_client, _path(novel, 2), reader)

    assert blank.status_code == 422
    assert done.status_code == 200, done.text
    assert (twice.status_code, twice.json()["detail"]["code"]) == (409, "NOVEL_ILLUSTRATION_ALREADY_TAKEN_DOWN")
    assert (unused.status_code, unused.json()["detail"]["code"]) == (404, "NOVEL_ILLUSTRATION_NOT_FOUND")
    row = await db_session.get_one(NovelIllustrationTakedown, sha)
    assert (row.asset_id, row.reason) == (picture.id, "운영정책 위반 그림")
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(NovelIllustrationScreenPass)) == 0
    for chapter in (first, second):
        (item,) = chapter["illustrations"]
        assert (item["url"], item["withheld"], item["withheldReason"]) == (None, "taken_down", "운영정책 위반 그림")
    assert first["paragraphs"] == ["첫 문단이다.", "둘째 문단이다.", "셋째 문단이다."]
    logged = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(AdminActionLog)
        .where(AdminActionLog.action_type == "novel-illustration-takedown")
    )
    assert logged == 1


async def test_taking_down_a_file_withholds_every_asset_that_carries_it_and_the_second_asset_is_already_down(
    db_client: httpx.AsyncClient, db_session: AsyncSession, same_bytes: dict[str, bytes]
) -> None:
    """같은 파일을 두 자산(A·B)으로 올려 두 노벨에 공개한 뒤 A 를 내리면, B 를 담은 노벨의 독자·어드민 화면에서도 B 자리가 A 의
    사유로 빈다(공개 심사가 B 의 바이트 sha 를 자산 행에 적어 둔다). B 를 내리면 이미 내려간 파일이라 새 행 없이 성공하고 감사
    로그에 B 조치가 한 줄 남는다. 깨지는 시나리오: A 를 내려도 B 는 독자에게 계속 보이고, B 를 내리려 하면 409 로 막혀 노벨 전체
    이용제한밖에 길이 없다."""
    first = await _public(db_session)
    second = await _public(db_session)
    a = await _asset(db_session, first.publisher_id)
    b = await _asset(db_session, second.publisher_id)
    same_bytes[_display_key(a)] = b"same-file"
    same_bytes[_display_key(b)] = b"same-file"
    await _freeze_pictures(db_session, first, 1, [(0, "after", a, "generated")])
    await _freeze_pictures(db_session, second, 1, [(1, "before", b, "generated")])
    sha = hashlib.sha256(b"same-file").hexdigest()
    # 공개 심사가 내려받으며 적어 둔 값(공개 경로가 적는 것은 공개 심사 시험이 본다).
    await db_session.execute(sa.update(Asset).where(Asset.id == b.id).values(display_sha256=sha))
    await db_session.commit()
    await _login_as_admin(db_client, await _create_admin(db_session))

    down_a = await db_client.post(f"/admin/novel-illustrations/{a.id}/takedown", json={"reason": "운영정책 위반 그림"})
    admin_view = (await db_client.get(f"/admin/novels/{second.novel_id}/chapters/{second.chapter_ids[0]}")).json()
    down_b = await db_client.post(f"/admin/novel-illustrations/{b.id}/takedown", json={"reason": "같은 그림 신고"})
    reader_view = await _read(db_client, _path(second, 1), await _reader(db_session))

    assert down_a.status_code == 200, down_a.text
    assert down_b.status_code == 200, down_b.text
    assert down_b.json()["alreadyTakenDown"] is True and down_a.json()["alreadyTakenDown"] is False
    assert down_b.json()["takenDownAt"] == down_a.json()["takenDownAt"]
    for view in (admin_view, reader_view):
        (item,) = view["illustrations"]
        assert (item["url"], item["withheld"], item["withheldReason"]) == (None, "taken_down", "운영정책 위반 그림")
    rows = (await db_session.execute(sa.select(NovelIllustrationTakedown.asset_id))).scalars().all()
    assert rows == [a.id]
    logged = (
        await db_session.execute(
            sa.select(AdminActionLog.target_user_id, AdminActionLog.reason_text)
            .where(AdminActionLog.action_type == "novel-illustration-takedown")
        )
    ).tuples().all()
    assert sorted(logged) == sorted([(first.publisher_id, "운영정책 위반 그림"), (second.publisher_id, "같은 그림 신고")])
    assert (await db_session.get_one(Asset, a.id, populate_existing=True)).display_sha256 == sha


# ── 작가 읽기 ────────────────────────────────────────────────────────────────
async def _owner_chapter(client: httpx.AsyncClient, novel_id: uuid.UUID, chapter: NovelChapter) -> dict[str, Any]:
    resp = await client.get(f"/novels/{novel_id}/chapters/{chapter.id}")
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()["revision"]
    return body


def _owner_shown(revision: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (item["assetId"], item["url"] is not None, item["withheld"], item["withheldReason"])
        for item in [*revision["illustrations"], *revision["unplacedIllustrations"]]
    ]


async def test_the_author_sees_a_taken_down_picture_withheld_with_its_reason_matched_by_its_bytes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    same_bytes: dict[str, bytes],
) -> None:
    """운영자가 내린 그림은 작가의 화·개정 응답에서도 주소 없이 사유만 남는다. 다시 공개가 바이트로 막으므로 같은 파일을 다시
    올린 새 자산도, 위치 확인 필요인 그림도 같이 보인다. 깨지는 시나리오: 작가에게는 그림이 그대로 보여 다시 공개를 누르고,
    어느 그림인지 모르는 거부로 하루 거부 상한을 쓴다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    taken = await _asset(db_session, setup.room.user_id)
    reupload = await _asset(db_session, setup.room.user_id, prefix="assets/novel-illustration/")
    fine = await _asset(db_session, setup.room.user_id)
    same_bytes[_display_key(taken)] = b"bad-picture"
    same_bytes[_display_key(reupload)] = b"bad-picture"
    revision = await _stack(
        db_session,
        chapter,
        [(0, "after", taken, "generated"), (1, "after", reupload, "upload"), (1, "after", fine, "generated")],
    )
    db_session.add(NovelChapterIllustration(revision_id=revision.id, sort_order=0, asset_id=taken.id, source="generated"))
    db_session.add(
        NovelIllustrationTakedown(
            content_sha256=hashlib.sha256(b"bad-picture").hexdigest(), asset_id=taken.id, reason="운영정책 위반 그림"
        )
    )
    await db_session.commit()

    current = await _owner_chapter(db_client, setup.novel_id, chapter)
    by_id = await db_client.get(f"/novels/{setup.novel_id}/chapters/{chapter.id}/revisions/{revision.id}")

    expected = [
        (str(taken.id), False, "taken_down", "운영정책 위반 그림"),
        (str(reupload.id), False, "taken_down", "운영정책 위반 그림"),
        (str(fine.id), True, None, None),
        (str(taken.id), False, "taken_down", "운영정책 위반 그림"),
    ]
    assert _owner_shown(current) == expected
    assert by_id.status_code == 200, by_id.text
    assert _owner_shown(by_id.json()) == expected


@pytest.mark.parametrize("case", ["operator", "suspension"])
async def test_the_author_sees_original_pictures_withheld_while_an_operator_restricts_the_original(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """운영자가 원작을 직접 이용제한하면 작가 화면에서도 원작 그림 자리만 비고(독자와 같은 규칙), 작가 자신의 그림은 그대로다.
    원작자 정지로 걸린 일괄 제한은 독자처럼 원작 그림을 그대로 보인다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    novel = await db_session.get_one(Novel, setup.novel_id)
    original = await _asset(db_session, setup.room.user_id, prefix="assets/situational-image/")
    mine = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", original, "original"), (0, "after", mine, "generated")])
    await db_session.execute(
        sa.update(Content)
        .where(Content.id == novel.content_id)
        .values(moderation_status=ModerationStatus.RESTRICTED, restricted_by_suspension=case == "suspension")
    )
    await db_session.commit()

    shown = _owner_shown(await _owner_chapter(db_client, setup.novel_id, chapter))

    if case == "operator":
        assert shown == [(str(original.id), False, "original_restricted", None), (str(mine.id), True, None, None)]
    else:
        assert shown == [(str(original.id), True, None, None), (str(mine.id), True, None, None)]


async def test_the_author_read_downloads_no_picture_while_nothing_is_taken_down(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """내린 그림이 하나도 없으면 작가 읽기는 그림을 내려받지 않는다 — 작가 화면의 응답은 편집할 때마다 나가므로 저장소 왕복을
    더하지 않는다. 내림이 하나라도 생기면 바이트로 대조한다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    picture = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", picture, "generated")])
    fetched: list[str] = []

    def download(key: str) -> bytes:
        fetched.append(key)
        return key.encode()

    monkeypatch.setattr(illustration_screening, "download_object", download)

    clean = _owner_shown(await _owner_chapter(db_client, setup.novel_id, chapter))
    db_session.add(NovelIllustrationTakedown(content_sha256="0" * 64, asset_id=uuid.uuid4(), reason="다른 그림"))
    await db_session.commit()
    after_a_takedown = _owner_shown(await _owner_chapter(db_client, setup.novel_id, chapter))
    sha = hashlib.sha256(_display_key(picture).encode()).hexdigest()
    await db_session.execute(sa.update(Asset).where(Asset.id == picture.id).values(display_sha256=sha))
    await db_session.commit()
    recorded = _owner_shown(await _owner_chapter(db_client, setup.novel_id, chapter))

    assert clean == after_a_takedown == recorded == [(str(picture.id), True, None, None)]
    # 바이트 sha 가 적힌 뒤에는 행의 값으로 대조하고 내려받지 않는다.
    assert fetched == [_display_key(picture)]


async def test_the_author_sees_an_asset_whose_file_was_taken_down_as_another_asset_without_downloading(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """공개 심사를 거쳐 바이트 sha 가 자산 행에 적힌 그림(B)은, 같은 파일이 다른 자산(A)으로 내려가 있으면 작가 화면에서도 A 의
    사유로 빈다 — 자산 행의 값으로 잇고 내려받지 않는다. 깨지는 시나리오: 작가 화면이 B 를 그대로 보여 주거나, 응답마다 그림을
    내려받는다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    b = await _asset(db_session, setup.room.user_id)
    sha = hashlib.sha256(b"same-file").hexdigest()
    await db_session.execute(sa.update(Asset).where(Asset.id == b.id).values(display_sha256=sha))
    db_session.add(NovelIllustrationTakedown(content_sha256=sha, asset_id=uuid.uuid4(), reason="운영정책 위반 그림"))
    await db_session.commit()
    await _stack(db_session, chapter, [(0, "after", b, "generated")])
    fetched: list[str] = []

    def download(key: str) -> bytes:
        fetched.append(key)
        return key.encode()

    monkeypatch.setattr(illustration_screening, "download_object", download)

    shown = _owner_shown(await _owner_chapter(db_client, setup.novel_id, chapter))

    assert shown == [(str(b.id), False, "taken_down", "운영정책 위반 그림")]
    assert fetched == []


async def test_a_storage_failure_on_the_author_read_still_withholds_the_taken_down_asset_itself(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    same_bytes: dict[str, bytes],
) -> None:
    """작가 읽기에서 그림을 못 내려받아도 응답은 나간다(편집 결과를 돌려주는 자리라 저장소 장애로 실패시키지 않는다). 그때는
    내린 그 자산만 자산 id 로 비운다."""
    setup = await _novel(db_client, db_session, monkeypatch)
    chapter = setup.chapters[0]
    taken = await _asset(db_session, setup.room.user_id)
    reupload = await _asset(db_session, setup.room.user_id)
    await _stack(db_session, chapter, [(0, "after", taken, "generated"), (0, "after", reupload, "generated")])
    sha = hashlib.sha256(_display_key(taken).encode()).hexdigest()
    db_session.add(NovelIllustrationTakedown(content_sha256=sha, asset_id=taken.id, reason="신고"))
    await db_session.commit()
    from botocore.exceptions import ClientError

    def broken(key: str) -> bytes:
        raise ClientError({"Error": {"Code": "500"}}, "GetObject")

    monkeypatch.setattr(illustration_screening, "download_object", broken)

    shown = _owner_shown(await _owner_chapter(db_client, setup.novel_id, chapter))

    assert shown == [(str(taken.id), False, "taken_down", "신고"), (str(reupload.id), True, None, None)]
