"""측정 하네스가 main 의 앱 함수와 같은 계약으로 도는지 — 앱이 바꾼 시그니처·스위치·전역 상태를 하네스가 조용히 놓치면 측정이 오류
없이 무효가 된다(임베딩 회상 갈래가 명사 단독으로 재지거나, 지식 범위 재계산이 서버와 다른 장면 인물을 센다).

인물 이름과 문장은 이 테스트를 위해 지어낸 것이다."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_fold
from api.chat.memory_vector import embed_query
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    PromptNames,
    SceneJudgmentResult,
    StatRuleJudgmentResult,
)
from api.chat.voyage_backoff import VOYAGE_BACKOFF_KEY
from api.db.models import ChatMessage, ChatMessageRole, LegalDocument
from api.db.models.chat import ChatMemoryFact
from api.legal import documents
from api.legal.dependencies import reconsent_required_units
from api.llm.client import LLMCallContext, LLMCallSite
from api.llm.voyage import VoyageEmbeddingClient
from factories import _make_memory_fact, _make_published, _make_user
from memory_eval import checkpoint, knowledge_recompute as kr, two_series
from memory_eval import trajectory_replay as tr
from memory_eval.embed_catchup import LedgerVoyageClient
from memory_eval.embed_offline import EmbeddingTable, text_sha
from memory_eval.fake_llm import FakeMemoryLLM
from memory_eval.ledger import Ledger
from memory_eval.offline_embedding import OfflineQueryEmbeddingClient, embeds_recall
from memory_eval.room import ensure_current_consent
from memory_eval.runtime import ARMS

ROOM, SNAP = uuid.uuid4(), uuid.uuid4()


# ---------------------------------------------------------------- 접기의 글쓰기 모델


class _NoSession:
    async def __aenter__(self) -> "_NoSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_fold_both_hands_the_writing_model_to_the_app_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_fold(*args: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    async def no_snapshot(db: Any, room_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(memory_fold, "fold_memory", fake_fold)
    monkeypatch.setattr(two_series, "current_snapshot", no_snapshot)
    out = await two_series.fold_both(
        lambda: _NoSession(),  # type: ignore[arg-type]
        FakeMemoryLLM(),
        room_id=ROOM,
        user_id=uuid.uuid4(),
        prompt_set=object(),  # type: ignore[arg-type]
        sections=[],
        is_story_chat=True,
        names=PromptNames(persona_name=None, char_name=None),
        series=None,
        writing_model="opus",
    )
    assert seen["writing_model"] == "opus"
    assert out == {"folded": False, "bSummary": False}


# ---------------------------------------------------------------- 질의 임베딩 클라이언트


def _table(text: str) -> EmbeddingTable:
    return EmbeddingTable(model="voyage-4-lite", dims=2, vectors={("query", text_sha(text)): [0.6, 0.8]})


async def test_offline_query_client_accepts_the_retry_delays_the_app_passes() -> None:
    client = OfflineQueryEmbeddingClient(_table("지어낸 질문"))
    vectors, tokens = await client.embed_with_usage(
        ["지어낸 질문"], input_type="query", call_site="memory_query_embedding", retry_delays=()
    )
    assert vectors == [[0.6, 0.8]] and tokens == 0


async def test_app_query_embedding_through_the_offline_client_is_ok_not_a_swallowed_failure() -> None:
    result = await embed_query(
        OfflineQueryEmbeddingClient(_table("지어낸 질문")), "지어낸 질문", timeout_seconds=5, room_id=ROOM
    )
    assert result.record["outcome"] == "ok"
    assert result.vector is not None and result.vector.vector == [0.6, 0.8]


async def test_ledger_voyage_client_forwards_retry_delays(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    seen: dict[str, Any] = {}

    async def fake_super(self: Any, texts: Any, *, input_type: str, call_site: str, retry_delays: Any = None) -> Any:
        seen["retry_delays"] = retry_delays
        return [[0.0, 1.0]], 3

    monkeypatch.setattr(VoyageEmbeddingClient, "embed_with_usage", fake_super)
    client = LedgerVoyageClient(
        ledger=Ledger(tmp_path / "ledger.jsonl"), stage="s-embed", api_key="k", model="voyage-4-lite", dims=2
    )
    await client.embed_with_usage(["글"], input_type="query", call_site="memory_query_embedding", retry_delays=())
    assert seen["retry_delays"] == ()


# ---------------------------------------------------------------- 궤적 재조립의 질의 임베딩 단언


def _embedding_arm() -> str:
    return next(a for a in ARMS if embeds_recall(a) and ARMS[a].get("memory_episodes_recall"))


def _plain_arm() -> str:
    return next(a for a in ARMS if not embeds_recall(a))


def _point(arm: str, turn: int, outcome: str | None, seen: int = 1) -> dict[str, Any]:
    return {"arm": arm, "turn": turn, "queryOutcome": outcome, "snapshotsSeen": seen}


def test_replay_accepts_points_whose_query_embedding_was_ok() -> None:
    arm = _embedding_arm()
    points = [
        _point(arm, 31, "ok"),
        _point(arm, 32, "ok"),
        _point(arm, 2, None, seen=0),
        _point(_plain_arm(), 31, None),
    ]
    assert tr.require_query_embedded(points) == {"expected": 2, "ok": 2}


@pytest.mark.parametrize("outcome", ["failed", "timeout", None])
def test_replay_stops_when_an_embedding_arm_point_was_not_embedded(outcome: str | None) -> None:
    arm = _embedding_arm()
    with pytest.raises(SystemExit, match="명사 단독"):
        tr.require_query_embedded([_point(arm, 31, "ok"), _point(arm, 32, outcome)])


# ---------------------------------------------------------------- 전역 Voyage 멈춤 키


class _FakeRedis:
    def __init__(self, keys: set[str]) -> None:
        self.keys = keys

    async def scan_iter(self, match: str) -> AsyncIterator[str]:
        prefix = match.rstrip("*")
        for key in sorted(self.keys):
            if key.startswith(prefix):
                yield key

    async def delete(self, key: str) -> int:
        if key in self.keys:
            self.keys.remove(key)
            return 1
        return 0

    async def exists(self, key: str) -> int:
        return int(key in self.keys)

    async def aclose(self) -> None:
        return None


def _patch_redis(monkeypatch: pytest.MonkeyPatch, keys: set[str]) -> _FakeRedis:
    from redis.asyncio import Redis

    fake = _FakeRedis(keys)
    monkeypatch.setattr(Redis, "from_url", staticmethod(lambda *a, **k: fake))
    return fake


async def test_restore_clears_the_global_voyage_backoff_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_redis(monkeypatch, {VOYAGE_BACKOFF_KEY, f"chat_room:turn_lock:{ROOM}", "other-room-key"})
    deleted = await checkpoint.clear_room_redis_keys(ROOM)
    assert VOYAGE_BACKOFF_KEY in deleted
    assert fake.keys == {"other-room-key"}


async def test_probe_guard_refuses_when_the_voyage_backoff_key_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_redis(monkeypatch, {VOYAGE_BACKOFF_KEY})
    with pytest.raises(SystemExit, match=VOYAGE_BACKOFF_KEY):
        await checkpoint.require_no_voyage_backoff()


async def test_probe_guard_passes_without_the_voyage_backoff_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_redis(monkeypatch, set())
    await checkpoint.require_no_voyage_backoff()


# ---------------------------------------------------------------- 지식 범위 재계산의 대사 따옴표 이름


def _fact(known_by: list[str]) -> ChatMemoryFact:
    return _make_memory_fact(
        ROOM, SNAP, id=uuid.uuid4(), kind="fact", subject="갑돌", object=None, attribute="숨긴 일",
        fact_key="fact|갑돌|숨긴 일", value="값", known_by=known_by,
    )  # fmt: skip


def _msg(role: ChatMessageRole, content: str, seconds: int) -> ChatMessage:
    at = datetime(2026, 10, 16, tzinfo=UTC) + timedelta(seconds=seconds)
    return ChatMessage(id=uuid.uuid4(), chat_room_id=ROOM, role=role, content=content, created_at=at)


@pytest.mark.parametrize(("ignore_quoted", "dropped"), [(True, True), (False, False)])
def test_recompute_counts_quoted_reply_names_the_way_the_server_does(ignore_quoted: bool, dropped: bool) -> None:
    secret = _fact(["을순"])
    history = [
        _msg(ChatMessageRole.ASSISTANT, "오프닝", 0),
        _msg(ChatMessageRole.USER, "앞 질문", 1),
        # 아는 사람의 이름이 대사 따옴표 안에만 나온다 — 서버는 지식 범위 필터를 켠 턴에 이 이름을 장면 인물로 세지 않는다.
        _msg(ChatMessageRole.ASSISTANT, '갑돌이 말했다. "을순이 그러던데."', 2),
    ]
    out = kr.recompute_turn(
        [secret], history=history, user_content="그래서?", names=PromptNames(persona_name="나", char_name=None),
        user_label="사용자", ignore_quoted_reply_names=ignore_quoted,
    )  # fmt: skip
    assert (str(secret.id) in out["droppedSecret"]) is dropped
    assert ("을순" in out["scenePeople"]) is not ignore_quoted


def test_quoted_name_flag_follows_the_arm_knowledge_filter_switch() -> None:
    assert kr.ignores_quoted_reply_names({"memory_knowledge_filter": True, "memory_facts_inject": False}) is True
    assert kr.ignores_quoted_reply_names({"memory_facts_inject": True}) is False


# ---------------------------------------------------------------- 가짜 LLM 의 턴 판정 스키마


def _usage() -> LLMCallContext:
    return LLMCallContext(call_site=get_args(LLMCallSite)[0], user_id=None, room_id=None)


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        (SceneJudgmentResult, {"place": None, "time": None}),
        (StatRuleJudgmentResult, {"fired_rule_ids": []}),
        (EndingJudgmentResult, {"triggered": False}),
        (ImageMatchJudgmentResult, {"matched_image_entity_id": None}),
    ],
)
async def test_fake_llm_answers_the_turn_judgment_schemas_with_no_change(schema: Any, expected: dict[str, Any]) -> None:
    result = await FakeMemoryLLM().generate_structured("판정 프롬프트", schema, usage=_usage())
    assert result.model_dump() == expected


# ---------------------------------------------------------------- 재동의 게이트


async def test_consent_alignment_brings_the_measurement_account_to_the_current_edition(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(delete(LegalDocument))
    stale = _make_user(terms_version=None)
    other = _make_user(terms_version=None)
    db_session.add_all([stale, other])
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    now = documents.utcnow()
    assert await reconsent_required_units(db_session, stale, now=now) == ["terms"]

    updated = await ensure_current_consent(db_session, [stale.id])

    assert updated == {str(stale.id): ["terms"]}
    assert await reconsent_required_units(db_session, stale, now=now) == []
    # 고르지 않은 회원은 건드리지 않는다.
    assert await reconsent_required_units(db_session, other, now=now) == ["terms"]
    assert await ensure_current_consent(db_session, [stale.id]) == {}
