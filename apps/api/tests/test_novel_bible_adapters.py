"""정본 기억 모델 어댑터 — 코드 표, env 덮어쓰기, 켜진 스위치의 기동 검증, 호출 위치 정책, 호출 기록, 실제 어댑터의 호출.

어댑터는 (부를 모델, 읽을 소설 레인 문안 체인) 한 쌍이다. 연산(슬롯 추출·충돌 판정)마다 어댑터를 코드 표가 정하고 env 가
덮어쓴다. 처음 등록부는 Gemini 어댑터 하나라 Claude 쪽 검증은 표를 가짜 스펙으로 바꿔 함수 단계에서 본다. 모델 호출은 가짜
클라이언트로만 한다."""

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _require_lane_model
from api.core.config import Settings, settings
from api.db.models.novel_bible import NovelBibleJob
from api.db.models.novel_bible_events import NovelBibleEvent
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.db.models.prompt import PromptSet, PromptSection
from api.llm import backends
from api.llm.backends import PromptSetModelId
from api.llm.call_policy import CALL_POLICIES
from api.llm.client import (
    LLMCallContext,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    LLMRateLimitError,
    LLMTruncatedError,
    collect_usage,
)
from api.llm.routing import RoutingLLMClient
from api.novel_bible.adapters import table
from api.novel_bible.adapters.records import recorded_bible_call
from api.novel_bible.adapters.resolver import ModelAdapter, build_resolver
from api.novel_bible.adapters.table import AdapterId, AdapterSpec
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import AdapterCallError, BibleModelAdapter
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import JobFailure, OperationKey
from api.novelize.call_records import recorded_call
from factories import load_production_env
from novel_bible_fakes import FakeAdapter, add_chapter, full_registry, make_novel, savepoint_factory

_BODY = "사건: 둘이 정원에서 만난다\n\n사실: 하나|life|-|alive|참\n\n앎: 둘|knows|하나|life|-|alive"


class _Answer(BaseModel):
    verdict: str


def _load(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """테스트 프로세스가 물려받은 설정 env 를 지우고 `env` 만 둔 설정."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _reader(loaded: Settings) -> Any:
    return lambda name: str(getattr(loaded, name))


def _claude_spec(**changes: Any) -> AdapterSpec:
    fields: dict[str, Any] = {
        "call_model": "haiku", "prompt_chain": "sonnet", "structured": True, "with_instruction": True,
        "max_input_chars": 100_000,
    }
    return AdapterSpec(**(fields | changes))


# --- 코드 표 ---


def test_every_operation_has_an_adapter_and_its_own_call_site_with_a_policy_row() -> None:
    operations = set(get_args(OperationKey))

    assert set(table.SLOT_OPERATION_ADAPTERS) == operations == set(table.OPERATION_CALL_SITES)
    assert set(table.ADAPTERS) == set(get_args(AdapterId))
    assert set(table.SLOT_OPERATION_ADAPTERS.values()) <= set(table.ADAPTERS)
    call_sites = list(table.OPERATION_CALL_SITES.values())
    assert len(set(call_sites)) == len(call_sites)
    assert set(call_sites) <= set(CALL_POLICIES)


def test_the_first_registry_holds_only_the_gemini_adapter() -> None:
    assert get_args(AdapterId) == ("gemini",)
    spec = table.ADAPTERS["gemini"]
    assert (spec.call_model, spec.prompt_chain, spec.structured, spec.with_instruction) == ("gemini", "gemini", True, True)
    assert set(table.SLOT_OPERATION_ADAPTERS.values()) == {"gemini"}


def test_novel_lane_chains_are_the_chains_the_admin_prompt_screen_allows_in_the_novel_lane() -> None:
    allowed: set[PromptSetModelId] = set()
    for model in get_args(PromptSetModelId):
        try:
            _require_lane_model("novel", model)
        except HTTPException:
            continue
        allowed.add(model)

    assert table.NOVEL_LANE_CHAINS == allowed


def test_an_override_replaces_only_its_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    other = cast(AdapterId, "other")
    monkeypatch.setitem(table.ADAPTERS, other, _claude_spec(call_model="sonnet"))

    effective = table.effective_adapters({"facts.extract": other})

    assert effective == {**table.SLOT_OPERATION_ADAPTERS, "facts.extract": other}
    assert table.effective_adapters({}) == table.SLOT_OPERATION_ADAPTERS


# --- 호출 위치 정책 ---


def test_bible_call_sites_are_instruction_structured_calls_on_an_anthropic_row() -> None:
    for call_site in table.OPERATION_CALL_SITES.values():
        policy = CALL_POLICIES[call_site]
        assert policy.call_kind == "structured_with_instruction"
        assert policy.backend == "anthropic" and policy.backend_from is None
        assert policy.gemini_timeout == 120_000
        assert not policy.model_selectable and policy.model_setting is None
        assert policy.novelize is None and policy.judgment_kind is None and not policy.publish_filter
        assert policy.claude_limits == "chat"


class _RecordingClient(LLMClient):
    """구조화 호출 하나를 받아 둔다. `error` 가 있으면 사용량을 남기지 않고 그 예외를 낸다."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate(
        self, prompt: str, system_instruction: str | None = None, stop_sequences: list[str] | None = None, *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("정본 기억은 스트림을 부르지 않는다")

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("정본 기억은 지시문을 따로 싣는 구조화만 부른다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: Any, *, system_instruction: str, usage: LLMCallContext
    ) -> Any:
        self.calls.append({"prompt": prompt, "system": system_instruction, "usage": usage})
        if self.error is not None:
            raise self.error
        collect_usage(usage, "합성-모델", SimpleNamespace(prompt_token_count=10, candidates_token_count=3))
        return response_schema.model_validate({"verdict": "합성 판정"})


def _prompt() -> RenderedPrompt:
    return RenderedPrompt(system_instruction="합성 지시문", prompt="합성 원고", prompt_set_id=uuid.uuid4())


def _refuse_to_build() -> LLMClient:
    raise AssertionError("Gemini 어댑터의 호출이 다른 구현으로 갔다")


async def test_bible_calls_with_the_gemini_adapter_go_to_gemini_despite_the_anthropic_policy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_call_site_backends", {})
    gemini = _RecordingClient()
    router = RoutingLLMClient(gemini, factories={"anthropic": _refuse_to_build, "bedrock": _refuse_to_build})
    adapter = ModelAdapter("gemini", router)
    records: list[dict[str, Any]] = []

    for operation, call_site in table.OPERATION_CALL_SITES.items():
        answer = await adapter.structured(_prompt(), _Answer, records=records, stage=operation)
        assert answer == _Answer(verdict="합성 판정")
        assert gemini.calls[-1]["usage"].call_site == call_site

    assert {record["backend"] for record in records} == {"gemini"}
    assert [record["stage"] for record in records] == list(table.OPERATION_CALL_SITES)


def test_an_env_backend_line_for_a_bible_call_site_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="서비스하지 않는다"):
        _load(
            monkeypatch,
            ANTHROPIC_DIRECT_API_KEY="sk-test",
            LLM_CALL_SITE_BACKENDS="novel_bible_extract_facts:anthropic",
        )


# --- 덮어쓰기 파서(스위치와 무관) ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", {}),
        (" , ,", {}),
        ("facts.extract:gemini", {"facts.extract": "gemini"}),
        (" facts.extract : gemini , knowledge.extract:gemini ,", {"facts.extract": "gemini", "knowledge.extract": "gemini"}),
    ],
)
def test_the_adapter_override_parses_operation_adapter_pairs(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: dict[str, str]
) -> None:
    assert _load(monkeypatch, NOVEL_BIBLE_ADAPTERS=raw).novel_bible_adapters == expected


@pytest.mark.parametrize(
    "raw",
    [
        "facts.extract",
        "facts.extract:gemini:gemini",
        ":gemini",
        "facts.extract:",
        "facts.extract:gemini,facts.extract:gemini",
        "facts.judge:gemini",
        "facts.extract:haiku",
        "facts.extract:Gemini",
    ],
)
def test_a_malformed_or_unknown_override_is_refused_even_while_the_switch_is_off(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    with pytest.raises(ValidationError):
        _load(monkeypatch, NOVEL_BIBLE_ADAPTERS=raw)


# --- 켜진 스위치의 기동 검증(설정 단계) ---


def test_with_the_switch_off_nothing_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load(monkeypatch, NOVEL_BIBLE_ADAPTERS="facts.extract:gemini")

    assert not loaded.novel_bible_enabled
    assert not loaded.gemini_api_key and not loaded.anthropic_direct_api_key


def test_the_switch_on_with_the_gemini_table_needs_no_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _load(monkeypatch, NOVEL_BIBLE_ENABLED="true", GEMINI_API_KEY="gemini-test")

    assert loaded.novel_bible_enabled and not loaded.anthropic_direct_api_key


def test_the_switch_on_without_a_gemini_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        _load(monkeypatch, NOVEL_BIBLE_ENABLED="true")


def test_the_switch_on_needs_the_gemini_key_even_when_every_operation_goes_to_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 어댑터가 쓰는 앱의 모델 클라이언트는 어느 구현으로 보내든 Gemini 클라이언트를 먼저 만든다.
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec())
    claude_only = {"ANTHROPIC_DIRECT_API_KEY": "sk-test"}

    assert not _load(monkeypatch, **claude_only).novel_bible_enabled
    assert _load(
        monkeypatch, NOVEL_BIBLE_ENABLED="true", GEMINI_API_KEY="gemini-test", **claude_only
    ).novel_bible_enabled
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        _load(monkeypatch, NOVEL_BIBLE_ENABLED="true", **claude_only)


@pytest.mark.parametrize("extra", [{}, {"NOVEL_BIBLE_ENABLED": "true"}])
def test_the_production_env_starts_with_the_switch_off_or_on(
    monkeypatch: pytest.MonkeyPatch, extra: dict[str, str]
) -> None:
    loaded = load_production_env(monkeypatch, **extra)

    assert loaded.novel_bible_adapters == {}
    assert loaded.novel_bible_enabled == bool(extra)


# --- 기동 검증 규칙(함수 단계, 가짜 Claude 스펙) ---


def test_a_claude_spec_goes_to_anthropic_direct_and_needs_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec())

    without_key = table.adapter_errors({}, {}, _reader(_load(monkeypatch, GEMINI_API_KEY="gemini-test")))
    with_key = table.adapter_errors(
        {}, {}, _reader(_load(monkeypatch, GEMINI_API_KEY="gemini-test", ANTHROPIC_DIRECT_API_KEY="sk-test"))
    )

    assert len(without_key) == len(table.OPERATION_CALL_SITES)
    assert all("anthropic" in error and "ANTHROPIC_DIRECT_API_KEY" in error for error in without_key)
    assert not any("BEDROCK" in error for error in without_key)
    assert with_key == []


def test_a_claude_spec_whose_model_turns_thinking_off_refuses_a_deep_structured_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec())
    loaded = _load(
        monkeypatch,
        GEMINI_API_KEY="gemini-test",
        ANTHROPIC_DIRECT_API_KEY="sk-test",
        ANTHROPIC_HAIKU_MODEL_ID="claude-haiku-5-5",
        ANTHROPIC_STRUCTURED_EFFORT="max",
    )

    errors = table.adapter_errors({}, {}, _reader(loaded))

    assert errors and all("ANTHROPIC_STRUCTURED_EFFORT=max" in error for error in errors)


@pytest.mark.parametrize("changes", [{"structured": False}, {"with_instruction": False}])
def test_a_spec_without_instruction_structured_output_is_refused(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, bool]
) -> None:
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec(**changes))

    errors = table.adapter_errors(
        {}, {}, _reader(_load(monkeypatch, GEMINI_API_KEY="gemini-test", ANTHROPIC_DIRECT_API_KEY="sk-test"))
    )

    assert errors and all("구조화 출력을 하지 못한다" in error for error in errors)


def test_a_spec_reading_a_chain_outside_the_novel_lane_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec(prompt_chain="haiku"))

    errors = table.adapter_errors(
        {}, {}, _reader(_load(monkeypatch, GEMINI_API_KEY="gemini-test", ANTHROPIC_DIRECT_API_KEY="sk-test"))
    )

    assert errors and all("소설 레인에 없다" in error for error in errors)


def test_an_implementation_without_instruction_structured_calls_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec())
    anthropic = backends.BACKENDS["anthropic"]
    capabilities = backends.BackendCapabilities(
        structured="json_schema", structured_images=False, structured_with_instruction=False
    )
    monkeypatch.setitem(
        backends.BACKENDS, "anthropic",
        backends.BackendSpec(capabilities=capabilities, model_id_settings=anthropic.model_id_settings,
                             credential_env=anthropic.credential_env),
    )

    errors = table.adapter_errors(
        {}, {}, _reader(_load(monkeypatch, GEMINI_API_KEY="gemini-test", ANTHROPIC_DIRECT_API_KEY="sk-test"))
    )

    assert errors and all("구조화 호출을 받지 못한다" in error for error in errors)


def test_the_settings_validator_refuses_what_the_rule_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec())

    with pytest.raises(ValidationError, match="ANTHROPIC_DIRECT_API_KEY"):
        _load(monkeypatch, NOVEL_BIBLE_ENABLED="true", GEMINI_API_KEY="gemini-test")


# --- 호출 기록 ---


def _report(usage: LLMCallContext) -> None:
    collect_usage(usage, "합성-모델", SimpleNamespace(prompt_token_count=10, candidates_token_count=3))


def test_bible_call_records_have_the_same_keys_as_novel_job_call_records() -> None:
    prompt_set_id = uuid.uuid4()
    context = LLMCallContext(call_site="novel_bible_extract_facts", user_id=None, room_id=None, call_model="gemini")
    novel: list[dict[str, Any]] = []
    bible: list[dict[str, Any]] = []

    with recorded_call(novel, context, stage="boundary", prompt_set_id=prompt_set_id, route_source=None) as usage:
        _report(usage)
    with recorded_bible_call(bible, context, stage="facts.extract", prompt_set_id=prompt_set_id) as usage:
        _report(usage)
    with pytest.raises(LLMClientError), recorded_call(
        novel, context, stage="boundary", prompt_set_id=prompt_set_id, route_source=None
    ):
        raise LLMClientError("합성 실패")
    with pytest.raises(LLMClientError), recorded_bible_call(
        bible, context, stage="facts.extract", prompt_set_id=prompt_set_id
    ):
        raise LLMClientError("합성 실패")

    assert [set(record) for record in bible] == [set(record) for record in novel]
    reported, failed = bible
    assert reported["stage"] == failed["stage"] == "facts.extract"
    assert reported["routeSource"] is None and reported["promptSetId"] == str(prompt_set_id)
    assert (reported["backend"], reported["promptTokens"], reported["failure"]) == ("gemini", 10, None)
    assert (failed["failure"], "promptTokens" in failed) == ("llm_error", False)


# --- 실제 어댑터 ---


async def test_the_adapter_reads_the_active_novel_lane_set_of_its_chain(db_session: AsyncSession) -> None:
    source = await ModelAdapter("gemini").prompt_source(db_session)

    prompt_set = await db_session.get(PromptSet, source.prompt_set_id)
    assert prompt_set is not None
    assert (prompt_set.lane, prompt_set.model, prompt_set.status) == ("novel", "gemini", "published")
    latest = await db_session.scalar(
        select(func.max(PromptSet.published_at)).where(
            PromptSet.lane == "novel", PromptSet.model == "gemini", PromptSet.status == "published"
        )
    )
    assert prompt_set.published_at == latest
    stored = await db_session.scalar(
        select(func.count()).select_from(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id)
    )
    assert len(source.sections) == stored
    assert {section.prompt_set_id for section in source.sections} == {prompt_set.id}


async def test_a_chain_without_an_active_set_is_a_prompt_missing_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 소설 레인에는 판정 전용 체인 세트가 없다.
    monkeypatch.setitem(table.ADAPTERS, "gemini", _claude_spec(prompt_chain="haiku"))

    with pytest.raises(AdapterCallError) as raised:
        await ModelAdapter("gemini").prompt_source(db_session)

    assert (raised.value.code, raised.value.retryable) == ("prompt_missing", False)


async def test_the_adapter_sends_the_instruction_apart_with_its_call_model_and_records_the_call() -> None:
    client = _RecordingClient()
    prompt = _prompt()
    records: list[dict[str, Any]] = []

    answer = await ModelAdapter("gemini", client).structured(prompt, _Answer, records=records, stage="facts.extract")

    assert answer == _Answer(verdict="합성 판정")
    (call,) = client.calls
    assert (call["prompt"], call["system"]) == ("합성 원고", "합성 지시문")
    usage = call["usage"]
    assert (usage.call_site, usage.call_model, usage.user_id, usage.room_id) == (
        "novel_bible_extract_facts", "gemini", None, None
    )
    (record,) = records
    assert (record["stage"], record["promptSetId"], record["outputTokens"]) == (
        "facts.extract", str(prompt.prompt_set_id), 3
    )


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (LLMRateLimitError("합성"), "rate_limited", True),
        (LLMPolicyViolationError("합성"), "blocked", False),
        (LLMTruncatedError("합성"), "truncated", True),
        (LLMClientError("합성"), "llm_error", True),
    ],
)
async def test_provider_failures_become_failure_codes_the_core_knows(
    error: Exception, code: JobFailure, retryable: bool
) -> None:
    records: list[dict[str, Any]] = []

    with pytest.raises(AdapterCallError) as raised:
        await ModelAdapter("gemini", _RecordingClient(error)).structured(
            _prompt(), _Answer, records=records, stage="conflicts.judge"
        )

    assert (raised.value.code, raised.value.retryable) == (code, retryable)
    (record,) = records
    assert record["callSite"] == "novel_bible_judge" and record["failure"] is not None


def test_the_resolver_follows_the_code_table_and_the_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    other = cast(AdapterId, "other")
    monkeypatch.setitem(table.ADAPTERS, other, _claude_spec(call_model="sonnet", max_input_chars=7))
    monkeypatch.setattr(settings, "novel_bible_adapters", {"facts.extract": other})

    resolver = build_resolver()

    assert resolver("facts.extract").id == "other"
    assert resolver("facts.extract").capabilities.max_input_chars == 7
    assert {resolver(operation).id for operation in get_args(OperationKey) if operation != "facts.extract"} == {"gemini"}


# --- 코어는 어댑터를 가르지 않는다 ---


async def _comparable(db: AsyncSession, novel_id: uuid.UUID) -> dict[str, list[tuple[Any, ...]]]:
    events = (await db.scalars(select(NovelBibleEvent).where(NovelBibleEvent.novel_id == novel_id))).all()
    facts = (await db.scalars(select(NovelBibleFact).where(NovelBibleFact.novel_id == novel_id))).all()
    knowledge = (await db.scalars(select(NovelBibleKnowledge).where(NovelBibleKnowledge.novel_id == novel_id))).all()
    return {
        "events": sorted((e.ordinal, e.summary, e.actuality) for e in events),
        "facts": sorted((f.kind, f.predicate_norm, f.value_norm, f.holds, f.scope) for f in facts),
        "knowledge": sorted((k.kind, sorted(k.proposition.items())) for k in knowledge),
    }


async def test_swapping_the_operation_adapter_changes_only_the_adapter_that_runs(db_session: AsyncSession) -> None:
    base = FakeAdapter(id="fake-base")
    outcomes: dict[str, tuple[dict[str, Any], dict[str, list[tuple[Any, ...]]]]] = {}
    swapped = {"a": FakeAdapter(id="fake-a"), "b": FakeAdapter(id="fake-b")}
    for label, adapter in swapped.items():
        novel = await make_novel(db_session)
        chapter, revision = await add_chapter(db_session, novel.id, 1, _BODY)
        registry = full_registry()
        adapters: dict[OperationKey, BibleModelAdapter] = {
            "events.extract": base, "facts.extract": adapter, "knowledge.extract": base, "conflicts.judge": base,
        }
        result = await confirm(
            db_session, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id,
            actor=Actor(kind="system"),
        )
        await run_until_idle(savepoint_factory(db_session), registry, [], adapters.__getitem__)
        jobs = (
            await db_session.execute(
                select(NovelBibleJob.slot, NovelBibleJob.adapter_id, NovelBibleJob.prompt_set_id, NovelBibleJob.status)
                .where(NovelBibleJob.commit_id == result.commit_id)
            )
        ).all()
        outcomes[label] = ({job.slot: (job.adapter_id, job.prompt_set_id, job.status) for job in jobs},
                           await _comparable(db_session, novel.id))

    (jobs_a, items_a), (jobs_b, items_b) = outcomes["a"], outcomes["b"]
    assert jobs_a["facts"] == ("fake-a", swapped["a"].prompt_set_id, "succeeded")
    assert jobs_b["facts"] == ("fake-b", swapped["b"].prompt_set_id, "succeeded")
    for slot in ("events", "knowledge"):
        assert jobs_a[slot] == jobs_b[slot] == ("fake-base", base.prompt_set_id, "succeeded")
    assert set(jobs_a) == set(jobs_b)
    assert items_a == items_b and all(items_a.values())
