"""정본 기억 확정의 어드민 내부 입구 — 확정 하나를 받고 그 상태·개수를 돌려준다.

스위치가 꺼져 있으면 라우트가 없는 것과 같은 404 다(어드민 세션이어도). 켜져 있어도 확정이 만들 작업에 배정된 어댑터의 문안
체인에 그 채널이 없으면 503 이다 — 처리될 수 없는 확정을 쌓지 않는다. 응답에는 정본 기억 내용(사실 값·인용)을 싣지 않는다
— 상태와 개수뿐이다."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import load_active_prompt_set
from api.core.config import settings
from api.db.models import Novel
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleFinding, NovelBibleJob
from api.novel_bible import entry
from api.novel_bible.core.confirm import ConfirmConflictError, ConfirmResult
from api.novel_bible.registry import REGISTRY
from factories import _create_admin, _login_as, _login_as_admin
from novel_bible_fakes import FakeAdapter, FakeSlot, add_chapter, fake_registry, facts_slot, make_novel, plant_revision

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
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entry, "REGISTRY", fake_registry())
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
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entry, "REGISTRY", fake_registry())
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


async def _commits(db_session: AsyncSession, novel_id: str) -> int:
    return int(
        await db_session.scalar(
            select(func.count()).select_from(NovelBibleCommit).where(NovelBibleCommit.novel_id == uuid.UUID(novel_id))
        )
        or 0
    )


@pytest.mark.usefixtures("bible_on")
async def test_confirm_is_unavailable_while_an_assigned_chain_lacks_the_slot_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 실제 어댑터(코드 표의 Gemini)가 실제 소설 레인 Gemini 활성 세트를 읽는다 — 시드 세트를 정본 기억 채널만 뺀 채 더 늦게
    # 게시해, 배정된 체인의 활성 세트에 그 채널이 없게 만든다.
    active, sections = await load_active_prompt_set(db_session, lane="novel", model="gemini")
    assert active.published_at is not None
    without = PromptSet(
        version="9001", status="published", lane="novel", model="gemini", user_label=active.user_label,
        story_assistant_label=active.story_assistant_label, story_example_label=active.story_example_label,
        character_assistant_label=active.character_assistant_label,
        published_at=active.published_at + timedelta(seconds=1),
    )
    db_session.add(without)
    await db_session.flush()
    db_session.add_all(
        PromptSection(
            prompt_set_id=without.id, channel=s.channel, scope=s.scope, slot=s.slot, variant=s.variant, body=s.body,
            conditional=s.conditional, order=s.order,
        )
        for s in sections
        if not s.channel.startswith("novel_bible_")
    )
    await db_session.flush()
    slot = FakeSlot("facts", "facts.extract", "novel_bible_facts", frozenset({"fact"}))
    monkeypatch.setattr(entry, "REGISTRY", fake_registry(slot))
    await _admin(db_client, db_session)
    body = await _target(db_session)

    response = await db_client.post(_CONFIRM, json=body)

    assert response.status_code == 503
    assert await _commits(db_session, body["novelId"]) == 0


@pytest.mark.usefixtures("bible_on")
async def test_confirm_accepts_the_seeded_chain_with_the_real_registry_and_resolver(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # 바로 위 503 테스트의 짝 — 등록부와 해석기를 바꿔 끼우지 않아, 실제 추출 슬롯마다 실제 어댑터가 시드된 소설 레인 Gemini 활성
    # 세트를 읽는다. 작업은 만들어지기만 한다 — 이 테스트에는 작업을 처리할 워커가 없어 모델을 부르지 않는다.
    await _admin(db_client, db_session)
    body = await _target(db_session)

    response = await db_client.post(_CONFIRM, json=body)

    assert response.status_code == 202
    assert response.json()["created"] is True and response.json()["status"] == "pending"
    jobs = (
        await db_session.execute(
            select(NovelBibleJob.slot, NovelBibleJob.status, NovelBibleJob.attempts).where(
                NovelBibleJob.novel_id == uuid.UUID(body["novelId"])
            )
        )
    ).all()
    assert sorted(jobs) == [(slot, "queued", 0) for slot in sorted(REGISTRY.extracting)]


@pytest.mark.usefixtures("bible_on")
async def test_confirm_goes_ahead_when_every_assigned_chain_has_its_slot_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entry, "REGISTRY", fake_registry(facts_slot()))
    monkeypatch.setattr(entry, "build_resolver", lambda: FakeAdapter().resolver())
    await _admin(db_client, db_session)
    body = await _target(db_session)

    response = await db_client.post(_CONFIRM, json=body)

    assert response.status_code == 202
    assert await _commits(db_session, body["novelId"]) == 1
