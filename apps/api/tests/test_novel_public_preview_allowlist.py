"""노벨 미리보기 명단 — 스위치가 켜져 있어도 명단이 비어 있지 않으면 명단의 로그인 회원에게만 노벨이 열리고, 나머지(비로그인
포함)에게는 스위치를 끈 것과 같은 응답이 나간다. 명단이 비면 지금처럼 모두에게 열린다."""

import uuid

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import Settings, settings
from factories import PublicNovel, _login_as, _make_public_novel, _make_user, _make_user_with_clover_lot


@pytest.fixture(autouse=True)
def _novel_public_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)


async def _member(db_session: AsyncSession) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)
    await db_session.commit()
    return user.id


async def _novel(db_session: AsyncSession) -> PublicNovel:
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id, batches=(6, 2))
    await db_session.commit()
    return novel


def _reader_calls(novel: PublicNovel) -> list[tuple[str, str, dict[str, object] | None]]:
    """독자 라우트마다 하나씩 — 목록·홈 노벨·작품 정보·화·구매·읽은 자리·좋아요·댓글 목록·댓글 쓰기·노벨 신고."""
    chapter = f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[0]}"
    return [
        ("GET", "/webnovels", None),
        ("GET", "/webnovels/home-curation", None),
        ("GET", f"/webnovels/{novel.novel_id}", None),
        ("GET", chapter, None),
        ("POST", f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}/purchase", {"expectedPrice": 30}),
        ("PUT", f"{chapter}/reading-position", {"paragraphIndex": 0, "paragraphCount": 1, "edition": 1, "finished": False}),
        ("POST", f"/webnovels/{novel.novel_id}/like", None),
        ("GET", f"{chapter}/comments", None),
        ("POST", f"{chapter}/comments", {"body": "잘 읽었어요"}),
        ("POST", f"/webnovels/{novel.novel_id}/reports", {"reasonCategory": "spam"}),
    ]


async def _call(client: httpx.AsyncClient, method: str, path: str, body: dict[str, object] | None) -> httpx.Response:
    return await client.request(method, path, json=body)


async def test_only_listed_members_reach_reader_routes_while_the_list_is_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명단 회원은 독자 라우트를 모두 쓰고, 명단 밖 회원은 같은 라우트마다 스위치를 끈 것과 같은 404
    `NOVEL_PUBLIC_DISABLED` 를 no-store 로 받는다(작품 정보·화는 소장하지 않은 사람의 404)."""
    novel = await _novel(db_session)
    listed, outsider = await _member(db_session), await _member(db_session)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [listed])

    await _login_as(db_client, outsider)
    blocked = [await _call(db_client, *call) for call in _reader_calls(novel)]
    await _login_as(db_client, listed)
    allowed = [await _call(db_client, *call) for call in _reader_calls(novel)]

    assert [r.status_code for r in blocked] == [404] * len(blocked)
    assert [r.headers.get("cache-control") for r in blocked] == ["no-store"] * len(blocked)
    gate_codes = [r.json()["detail"]["code"] for r in blocked]
    assert gate_codes == [
        "NOVEL_PUBLIC_DISABLED",
        "NOVEL_PUBLIC_DISABLED",
        "NOVEL_NOT_FOUND",
        "NOVEL_CHAPTER_NOT_FOUND",
        *["NOVEL_PUBLIC_DISABLED"] * 6,
    ]
    assert [r.status_code for r in allowed] == [200, 200, 200, 200, 200, 204, 204, 200, 201, 200]


async def test_a_listed_member_who_owned_a_chapter_sees_reading_end_once_dropped_from_the_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명단에서 빠진 소장자는 스위치를 끈 것과 같이 "잠시 쉬는 중"(410 `service_off`)을 받는다."""
    novel = await _novel(db_session)
    buyer = await _member(db_session)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [buyer])
    await _login_as(db_client, buyer)
    chapter = f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}"
    assert (await db_client.post(f"{chapter}/purchase", json={"expectedPrice": 30})).status_code == 200

    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [uuid.uuid4()])
    resp = await db_client.get(chapter)

    assert (resp.status_code, resp.json()["detail"]) == (410, {"code": "NOVEL_READING_ENDED", "reason": "service_off"})


async def test_a_logged_out_visitor_gets_the_switch_off_response_while_the_list_is_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비로그인은 명단이 있는 동안 로그인 요구(401)가 아니라 꺼진 노벨의 404 를 받는다 — 노벨이 있다는 것부터 알리지 않는다."""
    await _novel(db_session)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [uuid.uuid4()])
    db_client.cookies.clear()

    resp = await db_client.get("/webnovels")

    assert (resp.status_code, resp.json()["detail"]) == (404, {"code": "NOVEL_PUBLIC_DISABLED"})


async def test_an_empty_list_opens_novels_to_every_member(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel = await _novel(db_session)
    anyone = await _member(db_session)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [])
    await _login_as(db_client, anyone)

    responses = [await _call(db_client, *call) for call in _reader_calls(novel)]

    assert [r.status_code for r in responses] == [200, 200, 200, 200, 200, 204, 204, 200, 201, 200]


@pytest.mark.parametrize(
    ("enabled", "allowlist", "expected"),
    [
        pytest.param(True, [], True, id="on-everyone"),
        pytest.param(True, [uuid.uuid4()], False, id="on-preview"),
        pytest.param(False, [], False, id="off"),
    ],
)
async def test_public_pricing_reports_novels_open_only_when_open_to_everyone(
    db_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    allowlist: list[uuid.UUID],
    expected: bool,
) -> None:
    """인증 없는 가격 응답은 누가 보는지 모르므로, 명단이 있는 동안은 꺼짐으로 낸다 — 탭·홈 섹션·가격 행이 모두에게 숨는다."""
    monkeypatch.setattr(settings, "novel_public_enabled", enabled)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", allowlist)

    resp = await db_client.get("/clover/pricing")

    assert resp.json()["novelPublicEnabled"] is expected


@pytest.mark.parametrize(
    ("enabled", "listed", "expected"),
    [
        pytest.param(True, True, True, id="listed"),
        pytest.param(True, False, False, id="not-listed"),
        pytest.param(False, True, False, id="switch-off"),
    ],
)
async def test_me_reports_whether_novels_are_open_to_this_member(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    listed: bool,
    expected: bool,
) -> None:
    member = await _member(db_session)
    monkeypatch.setattr(settings, "novel_public_enabled", enabled)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [member if listed else uuid.uuid4()])
    await _login_as(db_client, member)

    resp = await db_client.get("/me")

    assert resp.json()["novelPublicEnabled"] is expected


async def test_me_reports_novels_open_to_every_member_when_the_list_is_empty(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = await _member(db_session)
    monkeypatch.setattr(settings, "novel_public_preview_allowlist", [])
    await _login_as(db_client, member)

    resp = await db_client.get("/me")

    assert resp.json()["novelPublicEnabled"] is True


def test_the_list_env_is_comma_separated_and_rejects_a_non_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 는 따옴표 없는 쉼표 구분만 쓴다. 오타 난 id 를 조용히 버리면 운영자가 들어 있다고 믿는 계정이 막힌 채로
    남으므로 기동에서 멈춘다."""
    first, second = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("NOVEL_PUBLIC_PREVIEW_ALLOWLIST", f" {first} , ,{second},")
    assert Settings(_env_file=None).novel_public_preview_allowlist == [first, second]  # type: ignore[call-arg]

    monkeypatch.setenv("NOVEL_PUBLIC_PREVIEW_ALLOWLIST", f"{first},not-a-uuid")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
