"""어드민 모델 배정 표 API — 실효 표 조회, 표 전체 저장, 이력 목록·상세, 이력으로 되돌리기.

판정·요약 모델 설정과 호출 위치 배정, 모델 id 는 `routing_env` 가 리터럴로 고정한다 — 로컬 `.env` 의 값에 따라 해석 결과가
달라지지 않게 한다. 체인 검사는 마이그레이션이 심은 활성 세트(두 레인 × gemini·sonnet·opus·haiku)를 그대로 쓴다.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import prompt_routing as admin_prompt_routing
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.prompt_routing import ALLOWED_ROUTE_PAIRS, route_chain_errors
from api.chat.prompt_routing_cache import PROMPT_ROUTES_CACHE_KEY, invalidate_prompt_routes, load_prompt_routes
from api.chat.prompt_stages import LANE_STAGES
from api.chat.turn_prompt import judgment_prompt_sets
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models.moderation import AdminActionLog
from api.db.models.prompt import PromptRoute, PromptRouteRevision, PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId
from api.llm.pricing import MODEL_PRICES, PRICES_AS_OF
from factories import _create_admin, _login_as, _login_as_admin, _make_user

_STAT_SITES_ON_ANTHROPIC = {
    "chat_stat_judgment": "anthropic",
    "preview_stat_judgment": "anthropic",
    "chat_scene_judgment": "anthropic",
    "preview_scene_judgment": "anthropic",
}

_ROUTING_ENV: dict[str, Any] = {
    "gemini_model_name": "test-gemini-base",
    "gemini_stat_judgment_model_name": "gemini-2.5-flash",
    "gemini_ending_judgment_model_name": None,
    "gemini_image_judgment_model_name": None,
    "anthropic_haiku_model_id": "claude-haiku-5-5",
    "anthropic_sonnet_model_id": "claude-sonnet-5-5",
    "anthropic_opus_model_id": "claude-opus-5-5",
    "anthropic_structured_effort": "low",
    "anthropic_direct_api_key": "sk-test",
    "stat_judgment_model": "gemini",
    "ending_judgment_model": "gemini",
    "image_judgment_model": "gemini",
    "memory_summary_model": "gemini",
    "memory_episode_model": "gemini",
    "memory_fact_model": "gemini",
    "llm_call_site_backends": _STAT_SITES_ON_ANTHROPIC,
}

_CELL_COUNT = sum(len(stages) for stages in LANE_STAGES.values()) * 2


@pytest.fixture
def routing_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in _ROUTING_ENV.items():
        monkeypatch.setattr(settings, name, value)
    return monkeypatch


@pytest.fixture
async def admin_id(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, payload)
    admin = payload["id"]
    assert isinstance(admin, uuid.UUID)
    return admin


def _row(
    stage: str,
    *,
    lane: str = "story",
    room_model: str = "opus",
    chain_model: str | None = "haiku",
    call_model: str = "haiku",
    backend: str = "anthropic",
) -> dict[str, Any]:
    return {
        "lane": lane,
        "roomModel": room_model,
        "stage": stage,
        "chainModel": chain_model,
        "callModel": call_model,
        "backend": backend,
    }


_STAT_ROW = _row("stat_judgment", chain_model="opus")
_FACT_ROW = _row("memory_fact", lane="character", chain_model="opus", call_model="gemini", backend="gemini")


async def _put(
    db_client: httpx.AsyncClient, rows: list[dict[str, Any]], base: str | None = None, note: str = ""
) -> httpx.Response:
    return await db_client.put("/admin/prompt-routing", json={"baseRevisionId": base, "note": note, "rows": rows})


async def _saved(db_client: httpx.AsyncClient, rows: list[dict[str, Any]], base: str | None = None) -> dict[str, Any]:
    resp = await _put(db_client, rows, base)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _cell(body: dict[str, Any], lane: str, room_model: str, stage: str) -> dict[str, Any]:
    cells: list[dict[str, Any]] = body["cells"]
    (cell,) = [c for c in cells if (c["lane"], c["roomModel"], c["stage"]) == (lane, room_model, stage)]
    return cell


async def _table(db_session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db_session.scalars(sa.select(PromptRoute))).all()
    return sorted(
        (
            {
                "lane": r.lane,
                "roomModel": r.room_model,
                "stage": r.stage,
                "chainModel": r.chain_model,
                "callModel": r.call_model,
                "backend": r.backend,
            }
            for r in rows
        ),
        key=lambda r: (r["lane"], r["roomModel"], r["stage"]),
    )


async def _revisions(db_session: AsyncSession) -> list[PromptRouteRevision]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptRouteRevision).order_by(PromptRouteRevision.number))).all())


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (r["lane"], r["roomModel"], r["stage"]))


# 경로의 이력 id 는 고정 값이다 — 모듈을 읽을 때마다 새로 만들면 병렬 실행의 워커마다 모은 테스트가 달라 수집이 깨진다.
_MISSING_REVISION = "00000000-0000-4000-8000-000000000001"
_ROUTES = [
    pytest.param("GET", "/admin/prompt-routing", None, id="get-table"),
    pytest.param("PUT", "/admin/prompt-routing", {"baseRevisionId": None, "rows": []}, id="save-table"),
    pytest.param("GET", "/admin/prompt-routing/revisions", None, id="list-revisions"),
    pytest.param("GET", f"/admin/prompt-routing/revisions/{_MISSING_REVISION}", None, id="get-revision"),
    pytest.param(
        "POST",
        f"/admin/prompt-routing/revisions/{_MISSING_REVISION}/restore",
        {"baseRevisionId": None},
        id="restore-revision",
    ),
]


@pytest.mark.parametrize(("method", "path", "json"), _ROUTES)
async def test_every_route_refuses_a_request_without_an_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession, method: str, path: str, json: dict[str, Any] | None
) -> None:
    assert (await db_client.request(method, path, json=json)).status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    # 이 회원 세션이 실제로 인증된다는 것을 먼저 고정해야, 무세션 401 과 구분되는 "회원 세션으로는 안 된다"가 남는다.
    assert (await db_client.get("/me")).status_code == 200
    assert (await db_client.request(method, path, json=json)).status_code == 401
    assert await _revisions(db_session) == []


async def test_an_empty_table_shows_every_cell_resolved_from_env_with_prices(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, admin_id: uuid.UUID
) -> None:
    resp = await db_client.get("/admin/prompt-routing")

    assert resp.status_code == 200
    body = resp.json()
    assert body["revisionId"] is None
    assert body["revisionNumber"] is None
    assert body["pricesAsOf"] == PRICES_AS_OF.isoformat()
    assert len(body["cells"]) == _CELL_COUNT
    assert {(c["effective"]["source"], c["configured"], c["skipped"]) for c in body["cells"]} <= {
        ("env", None, None),
        ("room", None, None),
    }
    assert {(p["kind"], p["model"], p["backend"]) for p in body["allowedPairs"]} == {
        (kind, model, backend) for kind, pairs in ALLOWED_ROUTE_PAIRS.items() for model, backend in pairs
    }

    stat = _cell(body, "story", "opus", "stat_judgment")
    assert stat["effective"] == {
        "chainModel": "gemini",
        "callModel": "gemini",
        "backend": "gemini",
        "source": "env",
        "sourceDetail": "STAT_JUDGMENT_MODEL",
    }
    price = MODEL_PRICES["gemini-2.5-flash"]
    assert stat["calls"] == [
        {
            "callSite": site,
            "backend": "gemini",
            "modelId": "gemini-2.5-flash",
            "price": {
                "inputUsdPerMillion": price.input_usd_per_million,
                "cachedInputUsdPerMillion": price.cached_input_usd_per_million,
                "outputUsdPerMillion": price.output_usd_per_million,
                "cacheWriteUsdPerMillion": price.cache_write_usd_per_million,
            },
        }
        for site in ("chat_stat_judgment", "preview_stat_judgment")
    ]
    # 단가 표에 없는 id 는 0 이 아니라 단가 없음이다.
    generate = _cell(body, "character", "gemini", "chat_generate")
    assert generate["effective"]["source"] == "room"
    assert generate["calls"] == [
        {"callSite": "chat_generate", "backend": "gemini", "modelId": "test-gemini-base", "price": None}
    ]


async def test_the_chain_list_follows_the_env_judgment_model(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, admin_id: uuid.UUID
) -> None:
    routing_env.setattr(settings, "stat_judgment_model", "haiku")

    body = (await db_client.get("/admin/prompt-routing")).json()

    chains = {(c["lane"], c["model"]): c["readBy"] for c in body["chains"]}
    assert chains[("story", "haiku")] == [
        {"roomModel": room, "stage": stage, "channels": [channel]}
        for room in ("gemini", "opus")
        for stage, channel in (("stat_judgment", "stat_rule_judgment"), ("scene_judgment", "scene_judgment"))
    ]
    assert ("character", "haiku") not in chains
    assert {"roomModel": "opus", "stage": "chat_generate", "channels": ["system", "generation"]} in chains[
        ("story", "opus")
    ]


async def test_saving_replaces_the_table_records_one_revision_and_shows_the_rows(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    db_session.add(
        PromptRoute(
            lane="story",
            room_model="gemini",
            stage="memory_fact",
            chain_model="gemini",
            call_model="gemini",
            backend="gemini",
        )
    )
    await db_session.commit()

    resp = await _put(db_client, [_STAT_ROW, _FACT_ROW], note="스탯 판정을 가벼운 모델로")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert await _table(db_session) == _sorted([_STAT_ROW, _FACT_ROW])
    (revision,) = await _revisions(db_session)
    assert (revision.number, revision.admin_id, revision.note, revision.restored_from_id) == (
        1,
        admin_id,
        "스탯 판정을 가벼운 모델로",
        None,
    )
    assert _sorted(revision.rows) == _sorted([_STAT_ROW, _FACT_ROW])
    assert (body["revisionId"], body["revisionNumber"]) == (str(revision.id), 1)

    stat = _cell(body, "story", "opus", "stat_judgment")
    assert stat["configured"] == _STAT_ROW
    assert stat["skipped"] is None
    assert stat["effective"] == {
        "chainModel": "opus",
        "callModel": "haiku",
        "backend": "anthropic",
        "source": "row",
        "sourceDetail": None,
    }
    assert [(c["callSite"], c["modelId"]) for c in stat["calls"]] == [
        ("chat_stat_judgment", "claude-haiku-5-5"),
        ("preview_stat_judgment", "claude-haiku-5-5"),
    ]
    assert stat["calls"][0]["price"]["outputUsdPerMillion"] == MODEL_PRICES["claude-haiku-5-5"].output_usd_per_million
    scene = _cell(body, "story", "opus", "scene_judgment")
    assert scene["configured"] is None
    assert (scene["effective"]["source"], scene["effective"]["sourceDetail"]) == ("inherited", "stat_judgment")
    # 다른 방 모델의 같은 단계는 행이 없어 env 그대로다.
    assert _cell(body, "story", "gemini", "stat_judgment")["effective"]["source"] == "env"


async def test_the_cache_is_cleared_only_after_the_save_commits(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    await load_prompt_routes(db_session)
    assert await redis_client.get(PROMPT_ROUTES_CACHE_KEY) is not None
    events: list[str] = []
    real_commit = db_session.commit

    async def recording_commit() -> None:
        events.append("commit")
        await real_commit()

    async def recording_invalidate() -> None:
        events.append("invalidate")
        await invalidate_prompt_routes()

    routing_env.setattr(db_session, "commit", recording_commit)
    routing_env.setattr(admin_prompt_routing, "invalidate_prompt_routes", recording_invalidate)

    resp = await _put(db_client, [_STAT_ROW])

    assert resp.status_code == 200, resp.text
    assert events[-2:] == ["commit", "invalidate"]
    assert events.count("invalidate") == 1
    assert await redis_client.get(PROMPT_ROUTES_CACHE_KEY) is None


async def test_a_redis_failure_after_the_commit_still_reports_the_save(
    routing_env: pytest.MonkeyPatch,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_invalidate() -> None:
        raise RedisError("down")

    routing_env.setattr(admin_prompt_routing, "invalidate_prompt_routes", failing_invalidate)

    with caplog.at_level(logging.WARNING, logger=admin_prompt_routing.__name__):
        resp = await _put(db_client, [_STAT_ROW])

    assert resp.status_code == 200, resp.text
    assert await _table(db_session) == [_STAT_ROW]
    assert any("무효화" in record.getMessage() for record in caplog.records)


async def _publish_story_haiku_set_with(db_session: AsyncSession, channels: list[str]) -> None:
    """이미 있는 체인보다 늦은 게시 시각으로, 주어진 채널만 가진 (story, haiku) 세트를 게시한다."""
    prompt_set = PromptSet(
        status="published",
        lane="story",
        model="haiku",
        user_label="사용자",
        story_assistant_label="서술자",
        story_example_label="예시",
        character_assistant_label="캐릭터",
        published_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    db_session.add(prompt_set)
    await db_session.flush()
    for order, channel in enumerate(channels):
        db_session.add(
            PromptSection(
                prompt_set_id=prompt_set.id,
                channel=channel,
                scope="both",
                slot="instruction",
                variant="",
                body="합성 문안",
                conditional=False,
                order=order,
            )
        )
    await db_session.commit()


async def _archive_character_sonnet(db_session: AsyncSession) -> None:
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.lane == "character", PromptSet.model == "sonnet").values(status="archived")
    )
    await db_session.commit()


async def _nothing(db_session: AsyncSession) -> None:
    return None


async def _stat_only_haiku_chain(db_session: AsyncSession) -> None:
    await _publish_story_haiku_set_with(db_session, ["stat_rule_judgment"])


@pytest.mark.parametrize(
    ("row", "rule", "setup"),
    [
        # 레인·단계 값은 요청 스키마를 통과하지만 캐릭터 레인에는 스탯 판정 단계가 없다.
        pytest.param(_row("stat_judgment", lane="character"), "unknown-stage", _nothing, id="stage-outside-its-lane"),
        pytest.param(
            _row("memory_fact", lane="character", chain_model="sonnet", call_model="gemini", backend="gemini"),
            "chain-not-published",
            _archive_character_sonnet,
            id="chain-without-a-published-set",
        ),
        pytest.param(
            _row("ending_judgment", chain_model="haiku", call_model="gemini", backend="gemini"),
            "chain-missing-channel",
            _stat_only_haiku_chain,
            id="chain-without-the-stage-channel",
        ),
        pytest.param(
            _row("memory_fact", chain_model="opus", call_model="sonnet", backend="bedrock"),
            "pair-not-allowed",
            _nothing,
            id="pair-outside-the-allowed-list",
        ),
        pytest.param(_row("ending_judgment"), "backend-mismatch", _nothing, id="env-routes-it-elsewhere"),
        pytest.param(
            _row("chat_generate", chain_model="opus", call_model="opus"),
            "generation-chain",
            _nothing,
            id="generation-row-with-a-chain",
        ),
        pytest.param(
            _row("chat_generate", chain_model=None, call_model="gemini", backend="gemini"),
            "generation-call-model",
            _nothing,
            id="generation-row-calling-another-model",
        ),
    ],
)
async def test_a_row_breaking_a_save_rule_is_refused_with_its_rule_and_cell(
    routing_env: pytest.MonkeyPatch,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    row: dict[str, Any],
    rule: str,
    setup: Any,
) -> None:
    await setup(db_session)

    resp = await _put(db_client, [_STAT_ROW, row])

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    cell = {"lane": row["lane"], "roomModel": row["roomModel"], "stage": row["stage"]}
    assert (detail["rule"], detail["row"]) == (rule, cell)
    assert detail["message"]
    assert [(e["rule"], e["row"]) for e in detail["errors"]] == [(rule, cell)]
    assert await _table(db_session) == []
    assert await _revisions(db_session) == []


async def test_every_broken_row_is_reported_not_only_the_first(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, admin_id: uuid.UUID
) -> None:
    resp = await _put(
        db_client,
        [_row("stat_judgment", lane="character"), _STAT_ROW, _row("ending_judgment")],
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["rule"] == "unknown-stage"
    assert [e["rule"] for e in detail["errors"]] == ["unknown-stage", "backend-mismatch"]


async def test_a_save_from_a_stale_revision_is_a_conflict(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    await _saved(db_client, [_STAT_ROW])

    resp = await _put(db_client, [])

    assert resp.status_code == 409
    assert resp.json()["detail"]["rule"] == "stale-revision"
    assert await _table(db_session) == [_STAT_ROW]
    assert len(await _revisions(db_session)) == 1


async def test_a_save_committed_while_another_is_being_checked_makes_the_other_a_conflict(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    first = await _saved(db_client, [_STAT_ROW])
    interleaved: list[int] = []

    async def chain_errors_with_a_save_in_between(db: AsyncSession, rows: Any) -> Any:
        # 같은 기준에서 출발한 다른 저장이 이 저장의 최신 이력 확인을 지난 뒤, 체인 검사 도중에 먼저 커밋된 상황을 만든다.
        if not interleaved:
            interleaved.append(1)
            other = await _put(db_client, [_FACT_ROW], first["revisionId"])
            interleaved.append(other.status_code)
        return await route_chain_errors(db, rows)

    routing_env.setattr(admin_prompt_routing, "route_chain_errors", chain_errors_with_a_save_in_between)

    resp = await _put(db_client, [_STAT_ROW], first["revisionId"])

    assert interleaved == [1, 200]
    assert resp.status_code == 409, resp.text
    # 먼저 커밋된 저장의 표가 남고, 뒤 저장이 그 표를 지우고 이력을 하나 더 쌓지 않는다.
    assert await _table(db_session) == [_FACT_ROW]
    assert [r.number for r in await _revisions(db_session)] == [1, 2]


async def test_saving_no_rows_empties_the_table_and_everything_resolves_from_env_again(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    first = await _saved(db_client, [_STAT_ROW, _FACT_ROW])

    body = await _saved(db_client, [], first["revisionId"])

    assert await _table(db_session) == []
    assert body["revisionNumber"] == 2
    assert {c["effective"]["source"] for c in body["cells"]} == {"env", "room"}
    assert [r.rows for r in await _revisions(db_session)][1] == []


async def test_restoring_writes_a_new_revision_from_the_old_snapshot(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    first = await _saved(db_client, [_STAT_ROW, _FACT_ROW])
    second = await _saved(db_client, [], first["revisionId"])

    resp = await db_client.post(
        f"/admin/prompt-routing/revisions/{first['revisionId']}/restore",
        json={"baseRevisionId": second["revisionId"], "note": "되돌림"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["revisionNumber"] == 3
    assert await _table(db_session) == _sorted([_STAT_ROW, _FACT_ROW])
    revisions = await _revisions(db_session)
    assert [r.number for r in revisions] == [1, 2, 3]
    assert (str(revisions[2].restored_from_id), revisions[2].note) == (first["revisionId"], "되돌림")
    assert _sorted(revisions[2].rows) == _sorted(revisions[0].rows)
    assert revisions[0].restored_from_id is None


async def test_restoring_checks_the_snapshot_again_against_the_env_of_now(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    first = await _saved(db_client, [_STAT_ROW])
    second = await _saved(db_client, [], first["revisionId"])
    routing_env.setattr(settings, "llm_call_site_backends", {})

    resp = await db_client.post(
        f"/admin/prompt-routing/revisions/{first['revisionId']}/restore",
        json={"baseRevisionId": second["revisionId"]},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "backend-mismatch"
    assert await _table(db_session) == []
    assert len(await _revisions(db_session)) == 2


async def test_restoring_a_snapshot_with_a_cell_the_code_no_longer_knows_is_refused(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    old = PromptRouteRevision(number=1, rows=[_row("memory_fact", lane="novel")], note="", admin_id=admin_id)
    db_session.add(old)
    await db_session.commit()

    resp = await db_client.post(
        f"/admin/prompt-routing/revisions/{old.id}/restore", json={"baseRevisionId": str(old.id)}
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["row"] == {"lane": "novel", "roomModel": "opus", "stage": "memory_fact"}
    assert resp.json()["detail"]["rule"] == "unknown-stage"


async def test_revisions_are_listed_newest_first_and_one_shows_its_rows(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    first = await _saved(db_client, [_STAT_ROW, _FACT_ROW])
    second = await _saved(db_client, [], first["revisionId"])

    listed = await db_client.get("/admin/prompt-routing/revisions")

    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [(i["id"], i["number"], i["rowCount"]) for i in items] == [
        (second["revisionId"], 2, 0),
        (first["revisionId"], 1, 2),
    ]
    assert items[1]["adminId"] == str(admin_id)

    detail = await db_client.get(f"/admin/prompt-routing/revisions/{first['revisionId']}")
    assert detail.status_code == 200
    assert _sorted(detail.json()["rows"]) == _sorted([_STAT_ROW, _FACT_ROW])
    assert detail.json()["droppedRowCount"] == 0


async def test_a_snapshot_row_the_code_no_longer_knows_is_left_out_of_the_detail_and_counted(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    old = PromptRouteRevision(
        number=1, rows=[_STAT_ROW, _row("memory_fact", call_model="retired-model")], note="", admin_id=admin_id
    )
    db_session.add(old)
    await db_session.commit()

    detail = await db_client.get(f"/admin/prompt-routing/revisions/{old.id}")

    assert detail.status_code == 200
    assert (detail.json()["rows"], detail.json()["droppedRowCount"], detail.json()["rowCount"]) == ([_STAT_ROW], 1, 2)


async def test_an_unknown_revision_is_not_found(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, admin_id: uuid.UUID
) -> None:
    missing = uuid.uuid4()

    assert (await db_client.get(f"/admin/prompt-routing/revisions/{missing}")).status_code == 404
    restore = await db_client.post(f"/admin/prompt-routing/revisions/{missing}/restore", json={"baseRevisionId": None})
    assert restore.status_code == 404


async def test_a_saved_row_the_env_no_longer_routes_shows_as_not_applied(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, admin_id: uuid.UUID
) -> None:
    await _saved(db_client, [_STAT_ROW])
    routing_env.setattr(settings, "llm_call_site_backends", {})

    body = (await db_client.get("/admin/prompt-routing")).json()

    stat = _cell(body, "story", "opus", "stat_judgment")
    assert stat["configured"] == _STAT_ROW
    assert stat["skipped"]["reason"] == "backend-mismatch"
    assert stat["skipped"]["stage"] == "stat_judgment"
    assert stat["effective"]["source"] == "env"
    # 물려받으려던 장면 헤더 칸도 같은 행을 건너뛴다.
    assert _cell(body, "story", "opus", "scene_judgment")["skipped"]["stage"] == "stat_judgment"


async def test_a_saved_row_does_not_change_which_judgment_sets_a_chat_turn_reads(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    """이 표를 읽는 채팅 코드는 아직 없다 — 행을 저장해도 턴이 고르는 판정 세트는 env 설정 그대로다."""
    routing_env.setattr(settings, "stat_judgment_model", "sonnet")
    gemini_set = await load_active_prompt_set(db_session, lane="story")

    async def load(model: PromptSetModelId) -> Any:
        return await load_active_prompt_set(db_session, lane="story", model=model)

    before = await judgment_prompt_sets(lane="story", gemini_set=gemini_set, load=load)
    await _saved(db_client, [_STAT_ROW])
    after = await judgment_prompt_sets(lane="story", gemini_set=gemini_set, load=load)

    assert after.stat[0].id == before.stat[0].id
    assert after.stat[0].model == "sonnet"


def _price_body(model_id: str) -> dict[str, float] | None:
    price = MODEL_PRICES.get(model_id)
    if price is None:
        return None
    return {
        "inputUsdPerMillion": price.input_usd_per_million,
        "cachedInputUsdPerMillion": price.cached_input_usd_per_million,
        "outputUsdPerMillion": price.output_usd_per_million,
        "cacheWriteUsdPerMillion": price.cache_write_usd_per_million,
    }


def _candidates(cell: dict[str, Any]) -> dict[tuple[str, str], list[tuple[str, str, dict[str, float] | None]]]:
    candidates: list[dict[str, Any]] = cell["candidates"]
    return {
        (c["model"], c["backend"]): [(call["callSite"], call["modelId"], call["price"]) for call in c["calls"]]
        for c in candidates
    }


async def test_every_cell_lists_the_model_id_and_price_of_each_pair_it_could_pick(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, admin_id: uuid.UUID
) -> None:
    """저장 전에 새로 고른 쌍의 단가를 화면이 보이려면 칸마다 고를 수 있는 쌍이 실제로 보낼 모델 id 와 단가가 있어야 한다.
    Gemini 판정은 판정 종류마다 모델명 설정이 달라 쌍만으로는 화면이 id 를 알 수 없다."""
    await _saved(db_client, [_STAT_ROW])

    body = (await db_client.get("/admin/prompt-routing")).json()

    stat_sites = ("chat_stat_judgment", "preview_stat_judgment")
    stat = _candidates(_cell(body, "story", "opus", "stat_judgment"))
    assert stat == {
        ("gemini", "gemini"): [(site, "gemini-2.5-flash", _price_body("gemini-2.5-flash")) for site in stat_sites],
        ("haiku", "anthropic"): [(site, "claude-haiku-5-5", _price_body("claude-haiku-5-5")) for site in stat_sites],
        ("sonnet", "anthropic"): [(site, "claude-sonnet-5-5", _price_body("claude-sonnet-5-5")) for site in stat_sites],
        ("opus", "anthropic"): [(site, "claude-opus-5-5", _price_body("claude-opus-5-5")) for site in stat_sites],
    }
    # 행이 있든 없든 후보는 같다 — 지금 운영 값이 아니라 그 쌍을 고르면 보낼 값이다.
    assert _candidates(_cell(body, "story", "gemini", "stat_judgment")) == stat
    # 판정 종류의 모델명 설정이 비면 기본 모델명이고, 단가 표에 없는 id 는 0 이 아니라 단가 없음이다.
    ending = _candidates(_cell(body, "story", "opus", "ending_judgment"))
    assert ending[("gemini", "gemini")] == [
        ("chat_ending_judgment", "test-gemini-base", None),
        ("preview_ending_judgment", "test-gemini-base", None),
    ]
    # 생성 칸은 방 모델로만 부르므로 후보가 그 방 모델의 쌍 하나다.
    assert _candidates(_cell(body, "character", "opus", "chat_generate")) == {
        ("opus", "anthropic"): [("chat_generate", "claude-opus-5-5", _price_body("claude-opus-5-5"))]
    }
    assert _candidates(_cell(body, "character", "gemini", "chat_generate")) == {
        ("gemini", "gemini"): [("chat_generate", "test-gemini-base", None)]
    }


async def _action_logs(db_session: AsyncSession) -> list[AdminActionLog]:
    db_session.expire_all()
    return list(
        (
            await db_session.scalars(
                sa.select(AdminActionLog).where(
                    AdminActionLog.action_type.in_(["prompt-routing-save", "prompt-routing-restore"])
                )
            )
        ).all()
    )


def _targets(log: AdminActionLog) -> tuple[uuid.UUID | None, ...]:
    return (
        log.target_user_id,
        log.target_content_id,
        log.target_chat_room_id,
        log.target_comment_id,
        log.target_novel_id,
    )


async def test_a_save_leaves_one_audit_row_with_its_note_and_no_target(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    await _put(db_client, [_STAT_ROW], note="스탯 판정을 가벼운 모델로")

    (log,) = await _action_logs(db_session)
    assert (log.action_type, log.admin_id, log.reason_text) == (
        "prompt-routing-save",
        admin_id,
        "스탯 판정을 가벼운 모델로",
    )
    assert _targets(log) == (None, None, None, None, None)


async def test_a_restore_leaves_its_own_audit_row(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    first = await _saved(db_client, [_STAT_ROW])
    second = await _saved(db_client, [], first["revisionId"])

    resp = await db_client.post(
        f"/admin/prompt-routing/revisions/{first['revisionId']}/restore",
        json={"baseRevisionId": second["revisionId"], "note": "되돌림"},
    )

    assert resp.status_code == 200, resp.text
    # 한 테스트 안에서는 `now()` 가 같아 시각으로 순서를 가를 수 없다 — 종류별로 센다.
    logs = await _action_logs(db_session)
    assert sorted((log.action_type, log.reason_text) for log in logs) == [
        ("prompt-routing-restore", "되돌림"),
        ("prompt-routing-save", ""),
        ("prompt-routing-save", ""),
    ]
    (restore,) = [log for log in logs if log.action_type == "prompt-routing-restore"]
    assert (restore.admin_id, _targets(restore)) == (admin_id, (None, None, None, None, None))


async def test_a_refused_or_conflicting_save_leaves_no_audit_row(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    refused = await _put(db_client, [_row("ending_judgment")])
    assert refused.status_code == 422
    assert await _action_logs(db_session) == []

    first = await _saved(db_client, [_STAT_ROW])
    stale = await _put(db_client, [])
    assert stale.status_code == 409
    assert len(await _action_logs(db_session)) == 1

    # 번호 경쟁: 검사 도중 다른 저장이 먼저 커밋되면 뒤 저장의 이력 행이 번호 유니크에 걸려 되감기고, 감사 행도 함께 사라져야 한다.
    raced: list[int] = []

    async def chain_errors_with_a_save_in_between(db: AsyncSession, rows: Any) -> Any:
        if not raced:
            raced.append(1)
            other = await _put(db_client, [_FACT_ROW], first["revisionId"])
            raced.append(other.status_code)
        return await route_chain_errors(db, rows)

    routing_env.setattr(admin_prompt_routing, "route_chain_errors", chain_errors_with_a_save_in_between)
    lost = await _put(db_client, [_STAT_ROW], first["revisionId"], note="경쟁에서 진 저장")

    assert (raced, lost.status_code) == ([1, 200], 409)
    logs = await _action_logs(db_session)
    assert len(logs) == 2
    assert "경쟁에서 진 저장" not in [log.reason_text for log in logs]


async def test_a_member_detail_does_not_read_audit_rows_without_a_target(
    routing_env: pytest.MonkeyPatch, db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID
) -> None:
    """감사 로그를 읽는 곳은 회원 상세 하나이고 그 회원이나 그 회원 작품이 대상인 행만 고른다. 그래서 대상 없는 배정 표 행은
    거기 실리지 않고, 이 조치 종류를 모르는 옛 이미지로 되돌려도 회원 상세 응답 검증이 깨지지 않는다 — 모르는 종류의 대상 없는
    행을 직접 심어 그 사실을 고정한다."""
    user = _make_user()
    db_session.add(user)
    db_session.add(AdminActionLog(admin_id=admin_id, action_type="an-action-this-code-does-not-know"))
    await db_session.commit()
    await _saved(db_client, [_STAT_ROW])

    resp = await db_client.get(f"/admin/users/{user.id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["actionLogs"] == []
