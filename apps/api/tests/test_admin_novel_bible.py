"""정본 기억 확정의 어드민 내부 입구 — 확정 하나를 받고 그 상태·개수를 돌려준다.

스위치가 꺼져 있으면 라우트가 없는 것과 같은 404 다(어드민 세션이어도). 응답에는 정본 기억 내용(사실 값·인용)을 싣지 않는다
— 상태와 개수뿐이다."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import Novel
from api.db.models.novel_bible import NovelBibleFinding, NovelBibleJob
from api.novel_bible import entry
from api.novel_bible.core.confirm import ConfirmConflictError, ConfirmResult
from factories import _create_admin, _login_as, _login_as_admin
from novel_bible_fakes import add_chapter, make_novel, plant_revision

_SECRET_SENTENCE = "합성 원고의 비밀 구절"
_CONFIRM = "/admin/novel-bible/confirmations"


@pytest.fixture
def bible_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_bible_enabled", True)


async def _admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    admin = await _create_admin(db_session)
    await _login_as_admin(db_client, admin)
    assert isinstance(admin["id"], uuid.UUID)
    return admin["id"]


async def _target(db_session: AsyncSession) -> dict[str, str]:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, f"사건: 만남\n\n{_SECRET_SENTENCE}")
    return {"novelId": str(novel.id), "chapterId": str(chapter.id), "revisionId": str(revision.id)}


async def test_confirm_is_not_found_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    body = await _target(db_session)
    # 꺼져 있으면 인증보다 먼저 404 다 — 라우트가 없는 것과 같다.
    assert (await db_client.post(_CONFIRM, json=body)).status_code == 404
    await _admin(db_client, db_session)

    assert (await db_client.post(_CONFIRM, json=body)).status_code == 404
    assert (await db_client.get(f"{_CONFIRM}/{uuid.uuid4()}")).status_code == 404


@pytest.mark.usefixtures("bible_on")
async def test_confirm_requires_an_admin_session(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    body = await _target(db_session)
    assert (await db_client.post(_CONFIRM, json=body)).status_code == 401
    novel = await db_session.get(Novel, uuid.UUID(body["novelId"]))
    assert novel is not None
    await _login_as(db_client, novel.user_id)
    assert (await db_client.post(_CONFIRM, json=body)).status_code == 401


@pytest.mark.usefixtures("bible_on")
async def test_confirm_accepts_a_revision_and_reconfirming_the_current_one_does_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client, db_session)
    body = await _target(db_session)

    response = await db_client.post(_CONFIRM, json=body)

    assert response.status_code == 202
    assert response.json()["created"] is True and response.json()["status"] == "extracting"

    other = await _target(db_session)
    planted = await plant_revision(
        db_session, uuid.UUID(other["novelId"]), uuid.UUID(other["chapterId"]), uuid.UUID(other["revisionId"])
    )
    again = await db_client.post(_CONFIRM, json=other)
    assert again.status_code == 202
    assert again.json() == {"commitId": str(planted.commit_id), "status": "committed", "created": False}


@pytest.mark.usefixtures("bible_on")
async def test_confirm_is_not_found_for_mismatched_or_hidden_targets(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client, db_session)
    body, other = await _target(db_session), await _target(db_session)

    mismatched = {**body, "revisionId": other["revisionId"]}
    assert (await db_client.post(_CONFIRM, json=mismatched)).status_code == 404
    await db_session.execute(
        update(Novel).where(Novel.id == uuid.UUID(body["novelId"])).values(hidden_at=datetime.now(UTC))
    )
    assert (await db_client.post(_CONFIRM, json=body)).status_code == 404


@pytest.mark.usefixtures("bible_on")
async def test_confirm_conflict_is_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _admin(db_client, db_session)
    body = await _target(db_session)

    async def conflicting(*args: object, **kwargs: object) -> ConfirmResult:
        raise ConfirmConflictError

    monkeypatch.setattr(entry, "confirm_chapter", conflicting)
    assert (await db_client.post(_CONFIRM, json=body)).status_code == 409


@pytest.mark.usefixtures("bible_on")
async def test_status_reports_counts_without_bible_content(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _admin(db_client, db_session)
    body = await _target(db_session)
    planted = await plant_revision(
        db_session, uuid.UUID(body["novelId"]), uuid.UUID(body["chapterId"]), uuid.UUID(body["revisionId"])
    )
    novel_id = uuid.UUID(body["novelId"])
    db_session.add_all(
        [
            NovelBibleJob(
                novel_id=novel_id, commit_id=planted.commit_id, slot="facts", status="succeeded", attempts=2,
                proposal={"items": [{"quote": _SECRET_SENTENCE}]},
            ),
            NovelBibleFinding(
                novel_id=novel_id, commit_id=planted.commit_id, severity="warning", rule="onset_unstated",
                payload={"note": _SECRET_SENTENCE},
            ),
        ]
    )
    await db_session.flush()

    response = await db_client.get(f"{_CONFIRM}/{planted.commit_id}")

    assert response.status_code == 200
    assert response.json() == {
        "commitId": str(planted.commit_id),
        "status": "committed",
        "failureCode": None,
        "revisionNo": planted.revision_no,
        "slots": [{"slot": "facts", "status": "succeeded", "attempts": 2, "failureCode": None}],
        "blockingCount": 0,
        "warningCount": 1,
    }
    assert _SECRET_SENTENCE not in response.text
    assert (await db_client.get(f"{_CONFIRM}/{uuid.uuid4()}")).status_code == 404
