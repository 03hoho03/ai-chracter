"""소설 리플레이 — 측정 서버의 소설 덤프를 읽어 같은 세트·같은 슬롯 값으로 다시 렌더하고, 그 바이트가 덤프의 sha 와 같을 때만
현행·변형 갈래를 부르는 도구와, 부른 출력에서 기계 지표를 세는 리포트.

LLM 은 가짜 클라이언트만 쓴다. 가짜는 공급자 모듈의 사용량 기록 함수를 모듈 속성으로 불러, 도구가 감싼 기록이 실제로 보낸 모델 id 와
토큰을 받는 경로를 그대로 탄다. 문안은 이 파일의 합성 문장뿐이다."""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import novel_replay
import novel_replay_metrics as metrics
from api.core.config import settings
from api.db.models.prompt import PromptSection, PromptSet, PromptSetSemver
from api.llm import gemini
from api.llm.client import LLMCallContext, LLMClient, T, structured_model
from api.llm.routing import resolve_backend
from api.novelize.prompts import (
    NovelizePrompt,
    build_novelize_chapter_prompt,
    build_novelize_episode_outline_prompt,
    build_novelize_outline_prompt,
)
from factories import _batch_output, _episode_text

# 원문 대화와 작품 설정에 심는 표지 — 출력에 나오면 누출로 센다.
_MARKER = "리플레이표지은하수종이배"
_TURN_LINES = (
    "[턴 1] 사용자: 비가 오네.\n[턴 1] 진행자: 우산을 펼쳤다.\n[턴 2] 사용자: 같이 가자.\n[턴 2] 진행자: 둘이 걸었다."
)
_BODY = "비가 내리는 저녁이었다. 서진은 우산을 펼치고 골목으로 나섰다.\n\n" + "도윤이 말없이 옆에 섰다. " * 20


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _section(channel: str, slot: str, body: str, order: int, *, conditional: bool = False) -> PromptSection:
    return PromptSection(
        channel=channel, scope="both", slot=slot, variant="", body=body, conditional=conditional, order=order
    )


def _sections(tag: str) -> list[PromptSection]:
    """세 채널과 등급 규칙의 합성 섹션. `tag` 가 지시문에 들어가 세트마다 바이트가 다르다."""
    common = [
        ("work_setting", "[설정]\n{work_setting}", 1, False),
        ("user_name", "[주인공] {user_name}", 2, False),
        ("notes", "[노트]\n{setting_notes}", 3, True),
        ("turn_context", "[원문]\n{turn_lines}", 9, False),
    ]
    out = [_section("novelize_rating", "rule_rating", f"[수위] 합성 등급 규칙 {tag}", 0)]
    plans = {
        "novelize_chapter": ("episode_plan", "{episode_count}화, 화마다 {episode_chars}자. {novel_title_rule}"),
        "novelize_outline": ("outline_plan", "화 수 상한 {max_episodes}, 안내 {episode_hint}"),
        "novelize_episode_outline": ("episode_outline", "[이 화]\n{episode_outline}"),
    }
    for channel, (plan_slot, plan_body) in plans.items():
        out.append(_section(channel, "instruction", f"합성 지시문 {channel} {tag}", 0))
        out.extend(_section(channel, slot, body, order, conditional=cond) for slot, body, order, cond in common)
        out.append(_section(channel, plan_slot, plan_body, 5))
    return out


async def _add_set(db: AsyncSession, tag: str, *, model: str = "gemini", status: str = "published") -> PromptSet:
    prompt_set = PromptSet(
        version=None if status == "draft" else f"replay-{uuid.uuid4()}",
        status=status,
        lane="novel",
        model=model,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
    )
    db.add(prompt_set)
    await db.flush()
    sections = _sections(tag)
    for section in sections:
        section.prompt_set_id = prompt_set.id
    db.add_all(sections)
    await db.flush()
    return prompt_set


async def _set_sections(db: AsyncSession, prompt_set: PromptSet) -> list[PromptSection]:
    rows = await db.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id))
    return list(rows.all())


def _sent_model(channel: str) -> str:
    """작업 모델이 gemini 인 소설 호출이 실제로 보내는 모델 id — 덤프가 적는 것과 같은 해석."""
    backend, sent = resolve_backend(novel_replay._CALL_SITES[channel], "gemini")
    return structured_model(novel_replay._CALL_SITES[channel], sent) if backend == "gemini" else sent


def _dump_line(
    prompt: NovelizePrompt, *, branch: str, schema: str | None, episode_number: int | None = None
) -> dict[str, Any]:
    """측정 덤프 한 줄 — `novelize/prompt_dump.py` 가 쓰는 14칸."""
    return {
        "jobId": str(uuid.uuid4()),
        "branch": branch,
        "callSite": prompt.channel,
        "jobModel": "gemini",
        "callModel": _sent_model(prompt.channel),
        "episodeNumber": episode_number,
        "novelSetId": str(prompt.prompt_set_id),
        "channel": prompt.channel,
        "scope": prompt.scope,
        "withRating": prompt.with_rating,
        "values": prompt.values,
        "systemSha256": _sha(prompt.system_instruction),
        "promptSha256": _sha(prompt.prompt),
        "schema": schema,
    }


async def _dump(db: AsyncSession, prompt_set: PromptSet, path: Path) -> list[dict[str, Any]]:
    """운영 빌더로 세 채널의 프롬프트를 만들어 덤프 줄을 쓴다. 대상 밖 채널의 줄 하나를 사이에 끼운다."""
    sections = await _set_sections(db, prompt_set)
    shared: dict[str, Any] = {
        "label_set": prompt_set,
        "sections": sections,
        "is_story_chat": True,
        "work_setting": f"안개 낀 항구 도시. {_MARKER}",
        "user_name": "서진",
        "setting_notes": "",
        "turn_lines": _TURN_LINES,
    }
    outline = build_novelize_outline_prompt(**shared, max_episodes=30, episode_hint=1)
    scenes = build_novelize_episode_outline_prompt(**shared, episode_outline="제목: 첫 만남\n줄거리: 둘이 만났다.")
    chapter = build_novelize_chapter_prompt(**shared, previous_excerpt="", episode_count=1)
    lines = [
        _dump_line(outline, branch="outline", schema="NovelizeOutlineResult"),
        {"jobId": str(uuid.uuid4()), "channel": "novelize_revise", "callSite": "novelize_revise", "values": {}},
        _dump_line(scenes, branch="episode_outline", schema="NovelizeEpisodeOutlineResult"),
        _dump_line(chapter, branch="manuscript", schema=None, episode_number=1),
    ]
    _write(path, lines)
    return lines


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _FakeNovelLLM(LLMClient):
    """소설 세 호출을 받는 가짜. 받은 (호출 위치, 글쓰기 모델, 스키마 이름, 지시문 sha, 본문 sha)를 적고, 공급자처럼 사용량 기록
    함수를 모듈 속성으로 부른다."""

    def __init__(self, *, chapter: str = _batch_output(_BODY)) -> None:
        self.calls: list[tuple[str, str, str | None, str, str]] = []
        self.chapter = chapter

    async def _record(self, usage: LLMCallContext) -> None:
        tokens = SimpleNamespace(
            prompt_token_count=1_000,
            cached_content_token_count=0,
            cache_write_token_count=None,
            candidates_token_count=500,
            thoughts_token_count=0,
            total_token_count=1_500,
        )
        # 공급자처럼 모듈 속성으로 부른다 — 도구가 감싼 기록 함수를 그때 찾아야 한다.
        await vars(gemini)["record_usage"](usage.call_site, settings.gemini_model_name, tokens)

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((usage.call_site, usage.model, None, _sha(system_instruction or ""), _sha(prompt)))
        await self._record(usage)
        yield self.chapter

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설 리플레이는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        name = response_schema.__name__
        self.calls.append((usage.call_site, usage.model, name, _sha(system_instruction), _sha(prompt)))
        await self._record(usage)
        item = {"title": "첫 만남", "summary": "둘이 만났다.", "start_turn": 1, "end_turn": 2}
        if name == "NovelizeOutlineResult":
            return response_schema.model_validate({"episodes": [{**item, "goal": "서로를 알게 된다."}]})
        scene = {**item, "purpose": "시작을 연다.", "characters": ["서진"], "flashback": False}
        return response_schema.model_validate({"scenes": [scene]})


class _Factory:
    """`--execute` 때만 클라이언트를 만든다는 것을 세는 팩토리."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.built = 0

    def __call__(self) -> LLMClient:
        self.built += 1
        return self.client


@pytest.fixture(autouse=True)
def _quiet_usage_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """사용량 기록 원래 함수는 DB 에 쓴다 — 리플레이 도구가 감싸는 자리만 남기고 기록은 하지 않는다."""

    async def record_usage(call_site: str, model: str, usage_metadata: object | None, **_: Any) -> None:
        return None

    monkeypatch.setattr(gemini, "record_usage", record_usage)


async def _run(db: AsyncSession, argv: list[str], factory: Callable[[], LLMClient]) -> int:
    args = novel_replay.parse_args(argv)
    return await novel_replay.run(args, db, client_factory=factory)


def _argv(dump: Path, ledger: Path, *extra: str, calls: str = "10", usd: str = "5") -> list[str]:
    return ["run", "--dump", str(dump), "--ledger", str(ledger), "--limit-calls", calls, "--limit-usd", usd, *extra]


# ---- 시험 실행 ---------------------------------------------------------------------------------


async def test_dry_run_rerenders_every_target_line_byte_identical_and_makes_no_calls(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    measured = await _add_set(db_session, "A")
    db_session.add(
        PromptSetSemver(prompt_set_id=measured.id, lane="novel", model="gemini", major=900, minor=2, patch=3)
    )
    await db_session.flush()
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    lines = await _dump(db_session, measured, dump)
    factory = _Factory(_FakeNovelLLM())

    assert await _run(db_session, _argv(dump, ledger), factory) == 0

    assert factory.built == 0
    plans = [r for r in _records(ledger) if r["kind"] == "plan"]
    assert not [r for r in _records(ledger) if r["kind"] == "call"]
    # 대상 밖 채널(문단 수정) 줄은 거른다 — 덤프 줄 번호는 파일 그대로다.
    assert [(p["line"], p["channel"], p["arm"]) for p in plans] == [
        (1, "novelize_outline", "window"),
        (3, "novelize_episode_outline", "window"),
        (4, "novelize_chapter", "window"),
    ]
    for plan, line in zip(plans, [lines[0], lines[2], lines[3]], strict=True):
        assert plan["matchesDump"] is True
        assert (plan["promptSha256"], plan["systemSha256"]) == (line["promptSha256"], line["systemSha256"])
        assert (plan["jobId"], plan["callSite"], plan["chainModel"]) == (line["jobId"], line["channel"], "gemini")
        assert (plan["novelSetId"], plan["setSemver"], plan["setStatus"]) == (str(measured.id), "900.2.3", "published")
        assert plan["execute"] is False and plan["costCeilingUsd"] > 0


# ---- 재렌더 단언 -------------------------------------------------------------------------------


async def test_a_line_whose_rerender_differs_from_its_dump_fails_and_is_not_called(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    measured = await _add_set(db_session, "A")
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    lines = await _dump(db_session, measured, dump)
    lines[3]["promptSha256"] = _sha("측정 뒤 바뀐 본문")
    _write(dump, lines)

    # 전체 중단: 한 줄이라도 다르면 아무것도 부르지 않는다.
    stopped = _Factory(_FakeNovelLLM())
    assert await _run(db_session, _argv(dump, ledger, "--stop-on-mismatch", "--execute"), stopped) == 2
    assert stopped.built == 0
    assert not [r for r in _records(ledger) if r["kind"] == "call"]
    failed = [r for r in _records(ledger) if r["kind"] == "plan" and not r["matchesDump"]]
    assert [(r["line"], r["jobId"]) for r in failed] == [(4, lines[3]["jobId"])]

    # 기본: 다른 줄만 실패로 빼고 나머지는 부른다. 종료 코드는 실패가 있었음을 알린다.
    ledger2 = tmp_path / "ledger2.jsonl"
    fake = _FakeNovelLLM()
    assert await _run(db_session, _argv(dump, ledger2, "--execute"), _Factory(fake)) == 2
    called = [r["jobId"] for r in _records(ledger2) if r["kind"] == "call"]
    assert called == [lines[0]["jobId"], lines[2]["jobId"]]
    assert [c[0] for c in fake.calls] == ["novelize_outline", "novelize_episode_outline"]


async def test_the_window_arm_must_send_the_model_the_dump_recorded(db_session: AsyncSession, tmp_path: Path) -> None:
    measured = await _add_set(db_session, "A")
    dump = tmp_path / "dump.jsonl"
    lines = await _dump(db_session, measured, dump)
    lines[3]["callModel"] = "측정 때 다른 모델"
    _write(dump, lines)

    stopped = tmp_path / "stopped.jsonl"
    factory = _Factory(_FakeNovelLLM())
    assert await _run(db_session, _argv(dump, stopped, "--stop-on-mismatch", "--execute"), factory) == 2
    assert factory.built == 0
    failed = [r for r in _records(stopped) if r["kind"] == "plan" and r["callModelMatchesDump"] is False]
    assert [(r["line"], r["matchesDump"]) for r in failed] == [(4, True)]

    # 기본: 그 줄만 빼고 나머지는 부른다.
    ledger = tmp_path / "ledger.jsonl"
    fake = _FakeNovelLLM()
    assert await _run(db_session, _argv(dump, ledger, "--execute"), _Factory(fake)) == 2
    assert [r["line"] for r in _records(ledger) if r["kind"] == "call"] == [1, 3]


async def test_a_line_whose_set_is_missing_is_refused(db_session: AsyncSession, tmp_path: Path) -> None:
    measured = await _add_set(db_session, "A")
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    lines = await _dump(db_session, measured, dump)
    lines[0]["novelSetId"] = str(uuid.uuid4())
    _write(dump, lines)
    assert await _run(db_session, _argv(dump, ledger), _Factory(_FakeNovelLLM())) == 2
    refused = [r for r in _records(ledger) if r["kind"] == "plan" and r.get("refused")]
    assert [r["line"] for r in refused] == [1]


# ---- 상한·원장 ---------------------------------------------------------------------------------


async def test_call_and_cost_limits_stop_the_calls_and_stay_in_the_ledger(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    measured = await _add_set(db_session, "A")
    dump = tmp_path / "dump.jsonl"
    await _dump(db_session, measured, dump)

    by_calls = tmp_path / "calls.jsonl"
    assert await _run(db_session, _argv(dump, by_calls, "--execute", calls="2"), _Factory(_FakeNovelLLM())) == 0
    records = _records(by_calls)
    calls = [r for r in records if r["kind"] == "call"]
    assert len(calls) == 2
    assert records[-1]["kind"] == "budgetExhausted" and records[-1]["used"] == 2
    # 원장의 모델 칸은 공급자 사용량이 돌려준 실제 모델 id 이고, 원가는 그 id 의 단가로 센 값이다.
    assert {c["sentModel"] for c in calls} == {settings.gemini_model_name}
    assert all(c["costUsd"] is not None and c["costUsd"] > 0 for c in calls)
    assert all(c["callSite"] in novel_replay.TARGET_CHANNELS for c in calls)

    # 원가 상한은 호출 전에 그 호출의 최악 견적으로 건다 — 한 호출의 실제 원가 절반이면 첫 호출부터 부르지 않는다.
    by_usd = tmp_path / "usd.jsonl"
    first_cost = calls[0]["costUsd"]
    argv = _argv(dump, by_usd, "--execute", usd=str(first_cost / 2))
    assert await _run(db_session, argv, _Factory(_FakeNovelLLM())) == 0
    assert [r["kind"] for r in _records(by_usd) if r["kind"] != "plan"] == ["budgetExhausted"]

    # 원장에 앞 묶음 원가가 이미 상한 이상이면 클라이언트를 만들지도 않는다.
    spent = tmp_path / "spent.jsonl"
    _write(spent, [{"kind": "call", "jobId": "앞 묶음", "arm": "window", "rep": 0, "costUsd": 0.5}])
    factory = _Factory(_FakeNovelLLM())
    assert await _run(db_session, _argv(dump, spent, "--execute", usd="0.5"), factory) == 3
    assert factory.built == 0


async def test_a_call_whose_worst_case_estimate_would_cross_the_cost_limit_is_not_made(
    db_session: AsyncSession, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    measured = await _add_set(db_session, "A")
    dump = tmp_path / "dump.jsonl"
    await _dump(db_session, measured, dump)
    dry = tmp_path / "dry.jsonl"
    assert await _run(db_session, _argv(dump, dry), _Factory(_FakeNovelLLM())) == 0
    ceiling = next(r["costCeilingUsd"] for r in _records(dry) if r["kind"] == "plan" and r["line"] == 1)
    capsys.readouterr()

    # 상한이 첫 호출의 견적보다 조금 작다: 원장 누적이 0 이어도 부르지 않고 멈춘 자리를 원장에 남긴다.
    below = tmp_path / "below.jsonl"
    fake = _FakeNovelLLM()
    argv = _argv(dump, below, "--execute", usd=str(ceiling * 0.99))
    assert await _run(db_session, argv, _Factory(fake)) == 0
    assert fake.calls == []
    stops = [r for r in _records(below) if r["kind"] != "plan"]
    assert [(r["kind"], r["line"], r["used"]) for r in stops] == [("budgetExhausted", 1, 0)]
    # 시험 실행에서도 전체 최악 견적이 상한을 넘으면 경고 줄을 낸다.
    assert "경고" in capsys.readouterr().out

    # 상한이 첫 호출의 견적 이상이면 그 호출은 부른다.
    at = tmp_path / "at.jsonl"
    fake = _FakeNovelLLM()
    argv = _argv(dump, at, "--execute", usd=str(ceiling + 1e-6))
    assert await _run(db_session, argv, _Factory(fake)) == 0
    first = next(r for r in _records(at) if r["kind"] != "plan")
    assert (first["kind"], first["line"]) == ("call", 1)

    # 상한이 넉넉하면 경고하지 않는다.
    capsys.readouterr()
    assert await _run(db_session, _argv(dump, tmp_path / "roomy.jsonl", usd="1000"), _Factory(_FakeNovelLLM())) == 0
    assert "경고" not in capsys.readouterr().out


async def test_running_the_same_jobs_and_arm_into_the_same_ledger_again_is_refused(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    measured = await _add_set(db_session, "A")
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    await _dump(db_session, measured, dump)
    assert await _run(db_session, _argv(dump, ledger, "--execute"), _Factory(_FakeNovelLLM())) == 0
    factory = _Factory(_FakeNovelLLM())
    assert await _run(db_session, _argv(dump, ledger, "--execute"), factory) == 2
    assert factory.built == 0


# ---- 갈래 -------------------------------------------------------------------------------------


async def test_model_axis_changes_only_the_call_model_and_set_axis_changes_the_prompt(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    measured = await _add_set(db_session, "A")
    other = await _add_set(db_session, "B")
    dump = tmp_path / "dump.jsonl"
    await _dump(db_session, measured, dump)

    by_model = tmp_path / "model.jsonl"
    fake = _FakeNovelLLM()
    argv = _argv(dump, by_model, "--model", "sonnet", "--arm", "sonnet", "--execute")
    assert await _run(db_session, argv, _Factory(fake)) == 0
    plans = [r for r in _records(by_model) if r["kind"] == "plan"]
    window = {p["line"]: p for p in plans if p["arm"] == "window"}
    arm = {p["line"]: p for p in plans if p["arm"] == "sonnet"}
    assert set(arm) == set(window) == {1, 3, 4}
    for line, plan in arm.items():
        assert (plan["variant"], plan["chainModel"], plan["novelSetId"]) == ("model", "sonnet", str(measured.id))
        assert (plan["promptSha256"], plan["systemSha256"]) == (
            window[line]["promptSha256"],
            window[line]["systemSha256"],
        )
    # 같은 바이트를 모델만 바꿔 보낸다 — 호출 위치는 운영 소설 호출 위치 그대로다.
    sent = {(site, model, prompt_sha) for site, model, _, _, prompt_sha in fake.calls}
    assert {(s, m) for s, m, _ in sent} == {(c, m) for c in novel_replay.TARGET_CHANNELS for m in ("gemini", "sonnet")}

    by_set = tmp_path / "set.jsonl"
    argv = _argv(dump, by_set, "--set", str(other.id), "--arm", "b")
    assert await _run(db_session, argv, _Factory(_FakeNovelLLM())) == 0
    plans = [r for r in _records(by_set) if r["kind"] == "plan"]
    window = {p["line"]: p for p in plans if p["arm"] == "window"}
    arm = {p["line"]: p for p in plans if p["arm"] == "b"}
    for line, plan in arm.items():
        assert (plan["variant"], plan["novelSetId"], plan["chainModel"]) == ("set", str(other.id), "gemini")
        assert plan["matchesDump"] is False
        assert plan["promptSha256"] == window[line]["promptSha256"]  # 본문 섹션 글은 두 세트가 같다
        assert plan["systemSha256"] != window[line]["systemSha256"]  # 지시문·등급 규칙이 세트마다 다르다


async def test_set_axis_on_a_draft_records_the_draft_sections_fingerprint(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    measured = await _add_set(db_session, "A")
    # 이 트랜잭션 안에서만 (소설, sonnet) 초안 자리를 비운다 — 초안은 (레인, 모델)마다 하나다.
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.lane == "novel", PromptSet.model == "sonnet", PromptSet.status == "draft")
        .values(status="replaced-in-test")
    )
    draft = await _add_set(db_session, "D", model="sonnet", status="draft")
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    await _dump(db_session, measured, dump)

    assert (
        await _run(
            db_session,
            _argv(dump, ledger, "--set", "draft", "--model", "sonnet", "--arm", "d"),
            _Factory(_FakeNovelLLM()),
        )
        == 0
    )
    plans = [r for r in _records(ledger) if r["kind"] == "plan" and r["arm"] == "d"]
    assert len(plans) == 3
    assert {(p["novelSetId"], p["setStatus"], p["chainModel"]) for p in plans} == {(str(draft.id), "draft", "sonnet")}
    fingerprints = {p["sectionsSha256"] for p in plans}
    assert len(fingerprints) == 1 and None not in fingerprints
    # 초안을 고치면 지문이 바뀐다 — 그 시점의 섹션을 가리킨다는 증거.
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.prompt_set_id == draft.id, PromptSection.slot == "instruction")
        .values(body="고친 합성 지시문")
    )
    ledger2 = tmp_path / "ledger2.jsonl"
    argv = _argv(dump, ledger2, "--set", "draft", "--model", "sonnet", "--arm", "d")
    assert await _run(db_session, argv, _Factory(_FakeNovelLLM())) == 0
    again = {r["sectionsSha256"] for r in _records(ledger2) if r["kind"] == "plan" and r["arm"] == "d"}
    assert again.isdisjoint(fingerprints)


def test_axis_arguments_follow_the_one_axis_rule() -> None:
    base = ["run", "--dump", "d", "--ledger", "l", "--limit-calls", "1", "--limit-usd", "1"]
    for extra in (
        ["--model", "sonnet"],
        ["--arm", "x"],
        ["--set", "draft", "--arm", "x"],
        ["--set", "nope", "--arm", "x"],
    ):
        with pytest.raises(SystemExit):
            novel_replay.parse_args(base + extra)
    for required in ("--limit-calls", "--limit-usd", "--ledger"):
        index = base.index(required)
        with pytest.raises(SystemExit):
            novel_replay.parse_args(base[:index] + base[index + 2 :])


# ---- 기계 지표 --------------------------------------------------------------------------------


def test_chapter_checks_count_format_failure_refusal_and_short_body() -> None:
    values = {"episode_count": "1", "episode_chars": "3000"}
    good = metrics.chapter_checks(_batch_output(_BODY), values)
    assert (good.parsed, good.legacy, good.refused, good.episodes, good.below_min) == (True, False, False, 1, 0)
    assert good.chars == [len("\n\n".join(p.strip() for p in _BODY.split("\n\n")))]

    # 구분자 형식이 없는 한 화 출력은 운영처럼 옛 형식으로 받되 형식 성공으로는 세지 않는다.
    legacy = metrics.chapter_checks(_BODY, values)
    assert (legacy.parsed, legacy.legacy, legacy.refused) == (False, True, False)
    # 화가 둘 이상이면 옛 형식으로도 받지 않는다.
    broken = metrics.chapter_checks(_BODY, {**values, "episode_count": "2"})
    assert (broken.parsed, broken.legacy, broken.episodes) == (False, False, 0)

    refusal = "죄송하지만 그 장면은 쓸 수 없습니다. 다른 요청을 해 주세요."
    refused = metrics.chapter_checks(refusal, values)
    assert refused.refused is True and refused.parsed is False
    short = metrics.chapter_checks(_batch_output("짧은 본문이었다."), values)
    assert (short.parsed, short.below_min) == (True, 1)


def test_structured_checks_use_the_schema_and_the_saving_validators() -> None:
    values = {"turn_lines": _TURN_LINES}
    episode = {"title": "첫 만남", "summary": "둘이 만났다.", "goal": "알게 된다.", "start_turn": 1, "end_turn": 2}
    ok = metrics.structured_checks("novelize_outline", json.dumps({"episodes": [episode]}), values)
    assert (ok.schema_ok, ok.valid, ok.refused, ok.items) == (True, True, False, 1)
    # 원문에 턴이 둘뿐인데 셋째 턴을 가리키면 저장 쪽 검증이 거부한다.
    out_of_range = metrics.structured_checks(
        "novelize_outline", json.dumps({"episodes": [{**episode, "end_turn": 3}]}), values
    )
    assert (out_of_range.schema_ok, out_of_range.valid) == (True, False)
    not_json = metrics.structured_checks("novelize_outline", "구성안이 아니다", values)
    assert (not_json.schema_ok, not_json.valid) == (False, False)

    scene = {
        "title": "시작",
        "summary": "죄송하지만 이 장면은 정리할 수 없습니다.",
        "purpose": "연다.",
        "characters": ["서진"],
        "flashback": False,
        "start_turn": 1,
        "end_turn": 1,
    }
    refused = metrics.structured_checks("novelize_episode_outline", json.dumps({"scenes": [scene]}), values)
    assert (refused.schema_ok, refused.valid, refused.refused) == (True, False, True)


def test_turn_count_reads_only_the_turn_heads_that_run_on_from_one() -> None:
    assert metrics.turn_count({"turn_lines": _TURN_LINES}) == 2
    # 메시지 안에서 줄을 바꾼 본문이 `[턴 n]` 으로 시작해도 이어지는 번호가 아니면 세지 않는다.
    assert metrics.turn_count({"turn_lines": _TURN_LINES + "\n[턴 99] 본문 속 줄"}) == 2
    assert metrics.turn_count({"turn_lines": "[턴 2] 사용자: 앞이 빠졌다."}) == 0
    episode = {"title": "첫 만남", "summary": "둘이 만났다.", "goal": "알게 된다.", "start_turn": 1, "end_turn": 99}
    values = {"turn_lines": _TURN_LINES + "\n[턴 99] 본문 속 줄"}
    beyond = metrics.structured_checks("novelize_outline", json.dumps({"episodes": [episode]}), values)
    assert beyond.valid is False


def test_a_manuscript_head_with_its_own_episode_number_counts_as_formatted() -> None:
    values = {"episode_count": "1", "episode_chars": "3000"}
    third = _episode_text(_BODY, number=3)
    assert metrics.chapter_checks(third, values).parsed is False
    assert metrics.chapter_checks(third, values, episode_number=3).parsed is True
    assert metrics.chapter_checks(_episode_text(_BODY, number=4), values, episode_number=3).parsed is False


def test_the_episode_number_comes_from_the_dump_field_or_is_approximated_only_for_the_outline_flow(
    tmp_path: Path,
) -> None:
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    base = {"episode_count": "1", "episode_chars": "3000"}
    summaries = {**base, "previous_summaries": "1화: 앞 일이 있었다.\n2화: 다음 일이 있었다."}
    cases: list[tuple[str, dict[str, Any], int]] = [
        # (작업, 덤프 줄, 형식 성공으로 세는가)
        ("field", {"branch": "manuscript", "episodeNumber": 3, "values": {**base, "previous_summaries": ""}}, 1),
        ("approx-manuscript", {"branch": "manuscript", "values": summaries}, 1),
        ("approx-regenerate", {"branch": "outline_regenerate", "values": summaries}, 1),
        ("legacy-flow", {"branch": "legacy_regenerate", "values": summaries}, 0),
        ("no-head", {"branch": "manuscript", "values": {**base, "previous_summaries": "있었다.\n다음 일."}}, 0),
    ]
    _write(dump, [{"jobId": job, "channel": "novelize_chapter", **line} for job, line, _ in cases])
    output = _episode_text(_BODY, number=3)
    _write(
        ledger,
        [
            {
                "kind": "call",
                "line": number,
                "jobId": job,
                "channel": "novelize_chapter",
                "arm": job,
                "rep": 0,
                "output": output,
                "error": None,
                "costUsd": 0.01,
                "sentModel": "m",
            }
            for number, (job, _, _) in enumerate(cases, start=1)
        ],
    )
    rows = {row["arm"]: row for row in metrics.summarize(metrics.load_calls([ledger], dump), [])}
    assert {job: rows[job]["formatOk"] for job, _, _ in cases} == {job: ok for job, _, ok in cases}


def test_leaked_markers_are_those_planted_in_the_inputs_and_found_in_the_output() -> None:
    values = {"work_setting": f"항구 {_MARKER}", "turn_lines": "평범한 원문"}
    markers = [_MARKER, "입력에없는표지"]
    assert metrics.leaked_markers(f"본문 속 {_MARKER} 한 줄", values, markers) == [_MARKER]
    assert metrics.leaked_markers("입력에없는표지 가 본문에 있다", values, markers) == []
    assert metrics.leaked_markers("깨끗한 본문", values, markers) == []


def test_report_counts_per_arm_and_channel_without_any_output_text(tmp_path: Path) -> None:
    dump, ledger = tmp_path / "dump.jsonl", tmp_path / "ledger.jsonl"
    values = {"episode_count": "1", "episode_chars": "3000", "work_setting": _MARKER, "turn_lines": _TURN_LINES}
    _write(dump, [{"jobId": "j1", "channel": "novelize_chapter", "values": values}])
    leaked = _batch_output(_BODY + _MARKER)
    plan = {"kind": "plan", "line": 1, "jobId": "j1", "channel": "novelize_chapter", "setSemver": "1.0.0"}
    _write(
        ledger,
        [
            {**plan, "arm": "window"},
            {**plan, "arm": "b", "setSemver": "1.1.0"},
            {
                "kind": "call",
                "line": 1,
                "jobId": "j1",
                "channel": "novelize_chapter",
                "arm": "window",
                "rep": 0,
                "output": _batch_output(_BODY),
                "error": None,
                "costUsd": 0.01,
                "sentModel": "m",
            },
            {
                "kind": "call",
                "line": 1,
                "jobId": "j1",
                "channel": "novelize_chapter",
                "arm": "b",
                "rep": 0,
                "output": leaked,
                "error": None,
                "costUsd": 0.02,
                "sentModel": "m",
            },
            {
                "kind": "call",
                "line": 1,
                "jobId": "j1",
                "channel": "novelize_chapter",
                "arm": "b",
                "rep": 1,
                "output": "",
                "error": "LLMClientError: 실패",
                "costUsd": None,
                "sentModel": None,
            },
        ],
    )
    rows = metrics.summarize(metrics.load_calls([ledger], dump), [_MARKER])
    by_arm = {row["arm"]: row for row in rows}
    assert by_arm["window"]["calls"] == 1 and by_arm["window"]["formatOk"] == 1 and by_arm["window"]["leakCalls"] == 0
    assert by_arm["b"]["calls"] == 2 and by_arm["b"]["errors"] == 1 and by_arm["b"]["leakCalls"] == 1
    assert (by_arm["window"]["setSemvers"], by_arm["b"]["setSemvers"]) == (["1.0.0"], ["1.1.0"])

    out = tmp_path / "report.out"
    argv = ["report", "--ledger", str(ledger), "--dump", str(dump), "--marker", _MARKER, "--out", str(out)]
    assert novel_replay.report(novel_replay.parse_args(argv)) == 0
    text = out.read_text(encoding="utf-8")
    assert "novelize_chapter" in text
    assert "비가 내리는 저녁" not in text and _MARKER not in text


# ---- 운영 DB 거부 ------------------------------------------------------------------------------


def test_a_database_outside_this_machine_is_refused_before_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://app:pw@postgres:5432/app")
    with pytest.raises(SystemExit, match="운영 DB"):
        novel_replay.main(["run", "--dump", "d"])
