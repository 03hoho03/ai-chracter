"""인상(Reflective) 문안 시제품·판정 도구 — 방의 접기 묶음마다 운영과 같은 입력(비밀 행을 포함한 장면·사실 행 전부)을 뽑고,
후보 문안으로 인상을 다시 만들고, 인상 문장마다 근거·작가 설정 어긋남을 판정한다. 모델은 전부 가짜다(유료 호출 0). 장면·사실
행과 문안·설정은 합성이다 — 실제 측정 데이터를 싣지 않는다.

지키는 것: 입력은 운영 인상 생성과 같은 행·같은 순서이고 비밀 행도 제자리에 들어가 그 수를 센다, 추출이 덜 끝난 묶음은 만들지 않는다,
후보 문안은 운영 채널에 심을 수 있는 꼴만 받는다, 글은 운영과 같게 다듬고 자른다, 호출 전에 원장 상한을 보고 끊긴 실행은 이어서
돈다, 판정은 문장마다 다수결이고 대조군 관문은 결과를 보기 전에 정한 문턱 하나로 판정한다."""

import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import MemoryImpressionResult, build_memory_impression_prompt
from api.core.config import settings
from api.db.models import ChatRoomMemorySnapshot
from api.db.models.chat import IMPRESSION_TEXT_MAX
from api.llm.client import CallUsage, LLMCallContext
from factories import (
    _make_memory_episode,
    _make_memory_extraction,
    _make_memory_fact,
    _make_memory_fact_extraction,
    _open_room,
)
from memory_eval import impression_proto as ip
from memory_eval.ledger import BudgetExceededError, Ledger

HAIKU = "claude-haiku-5-5"

CANDIDATE = {
    "sections": [
        {
            "scope": "both",
            "slot": "instruction",
            "body": "[합성 지시] 인물 사이 감정의 흐름을 적는다.",
            "conditional": False,
            "order": 0,
        },
        {"scope": "both", "slot": "episodes", "body": "[장면]\n{episode_lines}", "conditional": True, "order": 1},
        {"scope": "both", "slot": "facts", "body": "[사실]\n{fact_lines}", "conditional": True, "order": 2},
    ]
}


def _write(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def _item(
    key: str = "room-1:1", *, lane: ip.Lane = "character", episodes: Sequence[str] = ("- 우산: 빌려주었다",)
) -> ip.ImpressionInput:
    return ip.ImpressionInput(
        room_id=key.split(":")[0],
        lane=lane,
        group_index=int(key.split(":")[1]),
        snapshot_ids=("s1", "s2", "s3"),
        episode_lines=tuple(episodes),
        fact_lines=("- 민수 → 지아: 소꿉친구 (confirmed)",),
        episode_ids=("e1",),
        fact_ids=("f1",),
        secret_episodes=0,
        secret_facts=0,
    )


class FakeImpressionClient:
    """인상 호출만 받는 가짜. 응답 글을 차례로 내고(다 쓰면 고정 글), 호출마다 사용량 한 건을 실어 보낸다. 부른 순간의 인상 모델
    설정을 적어 둔다 — 운영과 같은 모델 고르기(설정)로 불렸는지 본다."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.prompts: list[str] = []
        self.usages: list[LLMCallContext] = []
        self.models_at_call: list[str] = []

    async def generate_structured(self, prompt: str, response_schema: Any, *, usage: LLMCallContext) -> Any:
        assert response_schema is MemoryImpressionResult
        self.prompts.append(prompt)
        self.usages.append(usage)
        self.models_at_call.append(str(settings.memory_impression_model))
        if usage.usage_sink is not None:
            usage.usage_sink.append(
                CallUsage(
                    call_site=usage.call_site,
                    model=HAIKU,
                    prompt_tokens=1000,
                    cached_tokens=0,
                    cache_write_tokens=0,
                    output_tokens=200,
                    thoughts_tokens=0,
                )
            )
        return MemoryImpressionResult(impression=self.texts.pop(0) if self.texts else "  서로를 믿기 시작했다.  ")


# ---------------------------------------------------------------- 묶음과 입력


def test_full_groups_takes_consecutive_full_chunks_like_production_multiples() -> None:
    # 운영은 스냅샷 수가 N 의 배수가 될 때마다 가장 새 N 개를 묶는다 — 순서대로 꽉 찬 묶음만, 남는 꼬리는 버린다.
    assert ip.full_groups(list("abcdefg"), 3) == [["a", "b", "c"], ["d", "e", "f"]]
    assert ip.full_groups(list("ab"), 3) == []
    with pytest.raises(ValueError):
        ip.full_groups(list("abc"), 0)


async def _room_with_snapshots(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, count: int
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    room = await _open_room(db_client, db_session, turns=count, lane="character")
    ids: list[uuid.UUID] = []
    for turn in range(1, count + 1):
        assistant = room.turns[turn][1]
        snapshot = ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text=f"[합성 요약 {turn}]",
            source="auto",
        )
        db_session.add(snapshot)
        await db_session.flush()
        ids.append(snapshot.id)
    return room.room_id, ids


async def test_load_room_inputs_keeps_secret_rows_counts_them_and_keeps_production_order(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id, snaps = await _room_with_snapshots(db_client, db_session, count=4)
    # 스냅샷 하나에 공개 장면 둘(순번 뒤집어 넣음)·비밀 장면 하나, 공개 사실 하나·비밀 사실 하나.
    rows: list[Any] = []
    for index, snap in enumerate(snaps):
        rows += [
            _make_memory_episode(room_id, snap, ordinal=1, title=f"공개B{index}", detail="둘째"),
            _make_memory_episode(room_id, snap, ordinal=0, title=f"공개A{index}", detail="첫째"),
            _make_memory_episode(room_id, snap, ordinal=2, title=f"비밀{index}", detail="숨김", known_by=["지아"]),
            _make_memory_fact(room_id, snap, ordinal=0, value=f"공개값{index}"),
            _make_memory_fact(
                room_id,
                snap,
                ordinal=1,
                kind="fact",
                object=None,
                attribute="비밀",
                fact_key=f"fact|민수|비밀{index}",
                value=f"비밀값{index}",
                known_by=["민수"],
            ),
            _make_memory_extraction(room_id, snap),
            _make_memory_fact_extraction(room_id, snap),
        ]
    db_session.add_all(rows)
    await db_session.flush()

    inputs, skipped = await ip.load_room_inputs(db_session, room_id, every=3)

    assert skipped == []
    assert len(inputs) == 1  # 스냅샷 넷 → N=3 꽉 찬 묶음 하나, 꼬리 하나는 버린다
    item = inputs[0]
    assert item.lane == "character"
    assert item.group_index == 1
    assert item.snapshot_ids == tuple(str(s) for s in snaps[:3])
    # 스냅샷 커서 순, 그 안은 순번 순 — 운영 인상 생성이 프롬프트에 싣는 순서다.
    # 비밀 행도 제자리(순번 2·1)에 든다.
    assert list(item.episode_lines) == [
        line for i in range(3) for line in (f"- 공개A{i}: 첫째", f"- 공개B{i}: 둘째", f"- 비밀{i}: 숨김")
    ]
    assert list(item.fact_lines) == [
        line
        for i in range(3)
        for line in (f"- 민수 → 지아: 공개값{i} (confirmed)", f"- 민수 / 비밀: 비밀값{i} (confirmed)")
    ]
    assert item.secret_episodes == 3 and item.secret_facts == 3
    assert len(item.episode_ids) == 9 and len(item.fact_ids) == 6


async def test_load_room_inputs_skips_groups_whose_extractions_are_not_all_done(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room_id, snaps = await _room_with_snapshots(db_client, db_session, count=6)
    rows: list[Any] = []
    for index, snap in enumerate(snaps):
        rows.append(_make_memory_fact(room_id, snap, value=f"값{index}"))
        rows.append(_make_memory_extraction(room_id, snap))
        # 둘째 묶음의 한 스냅샷은 사실 추출이 실패로 남았다.
        rows.append(
            _make_memory_fact_extraction(
                room_id, snap, **({"status": "failed", "fact_count": None} if index == 4 else {})
            )
        )
    db_session.add_all(rows)
    await db_session.flush()

    inputs, skipped = await ip.load_room_inputs(db_session, room_id, every=3)

    assert [i.group_index for i in inputs] == [1]
    assert [s["groupIndex"] for s in skipped] == [2]
    assert skipped[0]["reason"] == "extraction_not_done"


def test_input_round_trips_through_json() -> None:
    item = _item()
    assert ip.ImpressionInput.from_json(json.loads(json.dumps(item.to_json()))) == item
    assert item.key == "room-1:1"


# ---------------------------------------------------------------- 후보 문안


def test_candidate_renders_exactly_like_production_builder(tmp_path: Path) -> None:
    sections, sha = ip.load_candidate(_write(tmp_path / "c.json", CANDIDATE))
    item = _item(lane="story")
    expected = build_memory_impression_prompt(
        sections=sections, is_story_chat=True, episode_lines=item.episode_lines, fact_lines=item.fact_lines
    )
    assert ip.render_prompt(item, sections) == expected
    assert all(s.channel == "memory_impression" for s in sections)
    assert len(sha) == 64


@pytest.mark.parametrize(
    "bad",
    [
        {"scope": "both", "slot": "summary", "body": "x", "conditional": False, "order": 0},
        {"scope": "both", "slot": "facts", "body": "{fact_lines} {summary_text}", "conditional": False, "order": 0},
        {"scope": "everyone", "slot": "instruction", "body": "x", "conditional": False, "order": 0},
    ],
)
def test_candidate_rejects_what_the_production_channel_could_not_seed(tmp_path: Path, bad: dict[str, Any]) -> None:
    with pytest.raises(SystemExit):
        ip.load_candidate(_write(tmp_path / "c.json", {"sections": [bad]}))


def test_render_prompt_refuses_empty_channel(tmp_path: Path) -> None:
    spec = {"sections": [{"scope": "story", "slot": "instruction", "body": "x", "conditional": False, "order": 0}]}
    sections, _ = ip.load_candidate(_write(tmp_path / "c.json", spec))
    with pytest.raises(SystemExit):
        ip.render_prompt(_item(lane="character"), sections)


def test_finalize_matches_production_trim_and_cut() -> None:
    assert ip.finalize("  안녕.  ") == ("안녕.", 3, False)
    long_text = "가" * (IMPRESSION_TEXT_MAX + 5)
    text, raw_chars, truncated = ip.finalize(long_text)
    assert len(text) == IMPRESSION_TEXT_MAX and raw_chars == IMPRESSION_TEXT_MAX + 5 and truncated
    assert ip.finalize("   ") == ("", 0, False)
    # 상한에서 자른 끝이 공백이면 운영처럼 한 번 더 걷는다.
    cut_at_space = "가" * (IMPRESSION_TEXT_MAX - 1) + " 나다"
    assert ip.finalize(cut_at_space)[0] == "가" * (IMPRESSION_TEXT_MAX - 1)


# ---------------------------------------------------------------- 생성


async def test_run_generation_records_rows_ledger_and_resumes(tmp_path: Path) -> None:
    sections, sha = ip.load_candidate(_write(tmp_path / "c.json", CANDIDATE))
    items = [_item("room-1:1"), _item("room-1:2"), _item("room-2:1", lane="story")]
    ledger = Ledger(tmp_path / "ledger.jsonl", bundle="b")
    out = tmp_path / "out.jsonl"
    client = FakeImpressionClient("  첫 인상.  ", "가" * (IMPRESSION_TEXT_MAX + 1))

    made = await ip.run_generation(
        items[:2],
        sections,
        candidate_sha=sha,
        client=client,
        ledger=ledger,
        out_path=out,
        stage="proto",
        call_estimate_usd=0.001,
    )
    assert made == 2
    assert client.models_at_call == ["haiku", "haiku"]  # 운영 인상 호출과 같은 모델 고르기
    assert {u.call_site for u in client.usages} == {"chat_memory_impression"}
    rows = ip.read_rows(out)
    assert [r["key"] for r in rows] == ["room-1:1", "room-1:2"]
    assert rows[0]["text"] == "첫 인상." and rows[0]["truncated"] is False
    assert rows[1]["truncated"] is True and len(rows[1]["text"]) == IMPRESSION_TEXT_MAX
    assert rows[0]["promptSha"] == ip.sha256_text(ip.render_prompt(items[0], sections))
    assert len(ledger.rows()) == 2 and ledger.rows()[0]["callSite"] == "chat_memory_impression"

    # 이어 돌리기: 끝난 두 줄은 다시 부르지 않는다.
    again = await ip.run_generation(
        items,
        sections,
        candidate_sha=sha,
        client=client,
        ledger=ledger,
        out_path=out,
        stage="proto",
        call_estimate_usd=0.001,
    )
    assert again == 1 and len(client.prompts) == 3


async def test_run_generation_stops_before_a_call_that_would_pass_the_cap(tmp_path: Path) -> None:
    sections, sha = ip.load_candidate(_write(tmp_path / "c.json", CANDIDATE))
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=0.0005, bundle="b")
    client = FakeImpressionClient()
    with pytest.raises(BudgetExceededError):
        await ip.run_generation(
            [_item()],
            sections,
            candidate_sha=sha,
            client=client,
            ledger=ledger,
            out_path=tmp_path / "o.jsonl",
            stage="p",
            call_estimate_usd=0.001,
        )
    assert client.prompts == []


def test_estimate_counts_only_calls_not_yet_done(tmp_path: Path) -> None:
    sections, _ = ip.load_candidate(_write(tmp_path / "c.json", CANDIDATE))
    items = [_item("r:1"), _item("r:2")]
    full = ip.estimate(items, sections, model=HAIKU, tokens_per_char=1.0, output_tokens=300, done=set())
    half = ip.estimate(items, sections, model=HAIKU, tokens_per_char=1.0, output_tokens=300, done={"r:1"})
    assert full["calls"] == 2 and half["calls"] == 1
    assert half["totalUsd"] == pytest.approx(full["totalUsd"] / 2)


def test_length_report() -> None:
    rows: list[dict[str, Any]] = [
        {"status": "ok", "text": "가" * 100, "rawChars": 100, "truncated": False},
        {"status": "ok", "text": "가" * 600, "rawChars": 700, "truncated": True},
        {"status": "ok", "text": "", "rawChars": 0, "truncated": False},
        {"status": "call_error", "text": None, "rawChars": None, "truncated": None},
    ]
    report = ip.length_report(rows)
    assert report == {
        "rows": 4,
        "ok": 3,
        "failed": 1,
        "empty": 1,
        "truncated": 1,
        "rawOverCap": 1,
        "chars": {"min": 100, "median": 350.0, "mean": 350.0, "max": 600},
        "sentences": {"min": 1, "median": 1.0, "mean": 1.0, "max": 1},
    }


# ---------------------------------------------------------------- 판정


def test_split_sentences() -> None:
    assert ip.split_sentences("하나다. 둘이다!  셋인가?\n넷") == ["하나다.", "둘이다!", "셋인가?", "넷"]
    assert ip.split_sentences("  ") == []


OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
TEMPLATE = "설정:\n{author_setting}\n장면:\n{episode_lines}\n사실:\n{fact_lines}\n문장:\n{sentences}"


def _judge_item(gold: Sequence[ip.Label] | None = ("supported", "unsupported", "conflict")) -> ip.JudgeItem:
    return ip.JudgeItem(
        item_id="x1",
        author_setting="[합성 설정] 민수는 열일곱 살이다.",
        episode_lines=("- 우산: 빌려주었다",),
        fact_lines=("- 민수 → 지아: 소꿉친구 (confirmed)",),
        sentences=("민수는 지아를 아낀다.", "둘은 어제 싸웠다.", "민수는 서른 살이다."),
        gold=tuple(gold) if gold is not None else None,
    )


def test_render_judge_prompt_numbers_sentences_and_requires_every_placeholder() -> None:
    prompt = ip.render_judge_prompt(TEMPLATE, _judge_item())
    assert "[1] 민수는 지아를 아낀다.\n[2] 둘은 어제 싸웠다.\n[3] 민수는 서른 살이다." in prompt
    assert "[합성 설정]" in prompt and "- 우산: 빌려주었다" in prompt
    with pytest.raises(SystemExit):
        ip.check_template("설정 {author_setting} 문장 {sentences}")


def _verdict(*labels: str) -> ip.ImpressionVerdict:
    return ip.ImpressionVerdict.model_validate(
        {"sentences": [{"index": i + 1, "label": label, "reason": "r"} for i, label in enumerate(labels)]}
    )


class ScriptedJudge:
    def __init__(self, *answers: ip.ImpressionVerdict | Exception) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, prompt: str) -> ip.ImpressionVerdict:
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


async def test_judge_item_stops_after_two_agreeing_votes() -> None:
    judge = ScriptedJudge(
        _verdict("supported", "unsupported", "conflict"), _verdict("supported", "unsupported", "conflict")
    )
    decided, votes = await ip.judge_item(judge, "p", 3)
    assert decided == ["supported", "unsupported", "conflict"] and judge.calls == 2 and len(votes) == 2


async def test_judge_item_takes_a_third_vote_when_any_sentence_splits() -> None:
    judge = ScriptedJudge(
        _verdict("supported", "unsupported", "conflict"),
        _verdict("supported", "supported", "conflict"),
        _verdict("unsupported", "unsupported", "supported"),
    )
    decided, votes = await ip.judge_item(judge, "p", 3)
    # 첫 문장 2:1 supported, 둘째 2:1 unsupported, 셋째 2:1 conflict
    assert decided == ["supported", "unsupported", "conflict"] and judge.calls == 3 and len(votes) == 3


async def test_judge_item_retries_malformed_votes_then_counts_inability() -> None:
    # 문장 수와 다른 답·예외는 같은 입력으로 다시 묻는다. 세 번 다 실패한 표는 불능 표다.
    bad = _verdict("supported")
    judge = ScriptedJudge(
        bad,
        RuntimeError("x"),
        bad,  # 첫 표: 불능
        _verdict("supported", "supported", "supported"),  # 둘째 표
        _verdict("unsupported", "supported", "supported"),  # 셋째 표(첫 표가 불능이라 부른다)
    )
    decided, votes = await ip.judge_item(judge, "p", 3, concurrent=False)
    assert votes[0] is None
    assert decided == [None, "supported", "supported"]


def _row(gold: Sequence[str], decided: Sequence[str | None]) -> dict[str, Any]:
    return {"itemId": "x", "sentences": ["s"] * len(gold), "gold": list(gold), "decided": list(decided)}


def test_judge_report_gate_passes_only_at_threshold_and_without_inability() -> None:
    gold = ["supported"] * 4 + ["unsupported"] * 3 + ["conflict"] * 3
    perfect = ip.judge_report([_row(gold, gold)])
    assert perfect["gate"]["pass"] is True and perfect["gate"]["accuracy"] == 1.0

    one_wrong = list(gold)
    one_wrong[0] = "unsupported"  # 10 문장 중 1 틀림 → 0.9 는 통과(문턱 이상)
    assert ip.judge_report([_row(gold, one_wrong)])["gate"]["pass"] is True

    two_wrong = list(one_wrong)
    two_wrong[9] = "unsupported"
    report = ip.judge_report([_row(gold, two_wrong)])
    assert report["gate"]["pass"] is False and report["gate"]["accuracy"] == pytest.approx(0.8)

    unable: list[str | None] = list(gold)
    unable[5] = None
    report = ip.judge_report([_row(gold * 10, gold * 9 + unable)])
    assert report["gate"]["accuracy"] >= 0.9 and report["gate"]["inability"] == 1 and report["gate"]["pass"] is False


def test_judge_report_rates_without_gold() -> None:
    report = ip.judge_report(
        [
            {"itemId": "a", "sentences": ["1", "2"], "gold": None, "decided": ["supported", "unsupported"]},
            {"itemId": "b", "sentences": ["1", "2"], "gold": None, "decided": ["conflict", None]},
        ]
    )
    assert report["sentences"] == 4 and report["inability"] == 1
    assert report["rates"] == {
        "unsupported": pytest.approx(1 / 3),
        "conflict": pytest.approx(1 / 3),
        "flagged": pytest.approx(2 / 3),
    }
    assert report["itemsWithFlag"] == 2
    assert "gate" not in report


def test_items_from_results_joins_inputs_and_settings() -> None:
    item = _item("room-1:1")
    rows: list[dict[str, Any]] = [
        {"key": "room-1:1", "status": "ok", "text": "하나다. 둘이다."},
        {"key": "room-1:2", "status": "call_error", "text": None},
    ]
    built = ip.items_from_results(rows, [item], {"room-1": "[합성 설정]"})
    assert len(built) == 1
    assert built[0].item_id == "room-1:1" and built[0].sentences == ("하나다.", "둘이다.")
    assert built[0].fact_lines == item.fact_lines and built[0].author_setting == "[합성 설정]"
    with pytest.raises(SystemExit):
        ip.items_from_results(rows, [item], {})


def test_load_items_reads_controls(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "controls.json",
        [
            {
                "id": "c1",
                "authorSetting": "[합성]",
                "episodeLines": ["- a: b"],
                "factLines": [],
                "sentences": ["하나.", "둘."],
                "gold": ["supported", "conflict"],
            }
        ],
    )
    items = ip.load_items(path)
    assert items[0].gold == ("supported", "conflict") and items[0].sentences == ("하나.", "둘.")
    _write(
        path,
        [{"id": "c1", "authorSetting": "", "episodeLines": [], "factLines": [], "sentences": ["하나."], "gold": ["x"]}],
    )
    with pytest.raises(SystemExit):
        ip.load_items(path)


async def test_judge_items_writes_rows_and_resumes(tmp_path: Path) -> None:
    out = tmp_path / "judged.jsonl"
    items = [_judge_item(), ip.JudgeItem(**{**_judge_item().__dict__, "item_id": "x2"})]
    judge = ScriptedJudge(*([_verdict("supported", "unsupported", "conflict")] * 4))
    made = await ip.judge_items(items[:1], judge, template=TEMPLATE, out_path=out, judge_model=OPUS)
    assert made == 1
    made = await ip.judge_items(items, judge, template=TEMPLATE, out_path=out, judge_model=OPUS)
    assert made == 1 and judge.calls == 4
    rows = ip.read_rows(out)
    assert [r["itemId"] for r in rows] == ["x1", "x2"]
    assert rows[0]["decided"] == ["supported", "unsupported", "conflict"]
    assert rows[0]["promptSha"] == ip.sha256_text(ip.render_judge_prompt(TEMPLATE, items[0]))
    assert {r["judgeModel"] for r in rows} == {OPUS}


async def test_judge_items_resume_does_not_ask_again_for_votes_received_before_a_mid_item_stop(tmp_path: Path) -> None:
    # 첫 표를 받은 뒤 둘째 표에서 원장 상한으로 멈춘 문항. 첫 표는 이미 돈을 냈으므로 이어 돌릴 때 다시 부르지 않는다.
    out = tmp_path / "judged.jsonl"
    agree = _verdict("supported", "unsupported", "conflict")
    stopped = ScriptedJudge(agree, BudgetExceededError("cap"))
    with pytest.raises(BudgetExceededError):
        await ip.judge_items([_judge_item()], stopped, template=TEMPLATE, out_path=out, judge_model=OPUS)
    assert stopped.calls == 2 and ip.read_rows(out) == []

    resumed = ScriptedJudge(agree)
    made = await ip.judge_items([_judge_item()], resumed, template=TEMPLATE, out_path=out, judge_model=OPUS)
    assert made == 1 and resumed.calls == 1
    [row] = ip.read_rows(out)
    assert row["decided"] == ["supported", "unsupported", "conflict"] and len(row["votes"]) == 2

    again = ScriptedJudge()
    made = await ip.judge_items([_judge_item()], again, template=TEMPLATE, out_path=out, judge_model=OPUS)
    assert made == 0 and again.calls == 0


async def test_judge_items_resume_keeps_an_inability_vote_received_before_a_stop(tmp_path: Path) -> None:
    # 재시도를 다 쓴 불능 표도 이미 낸 호출이다. 이어 돌릴 때 그 표를 다시 묻지 않고, 불능 표가 있으니 셋째 표까지만 받는다.
    out = tmp_path / "judged.jsonl"
    bad = _verdict("supported")
    stopped = ScriptedJudge(bad, bad, bad, BudgetExceededError("cap"))
    with pytest.raises(BudgetExceededError):
        await ip.judge_items([_judge_item()], stopped, template=TEMPLATE, out_path=out, judge_model=OPUS)

    resumed = ScriptedJudge(
        _verdict("supported", "supported", "supported"), _verdict("supported", "conflict", "supported")
    )
    await ip.judge_items([_judge_item()], resumed, template=TEMPLATE, out_path=out, judge_model=OPUS)
    assert resumed.calls == 2
    [row] = ip.read_rows(out)
    assert row["votes"][0] is None and len(row["votes"]) == 3
    assert row["decided"] == ["supported", None, "supported"]


async def test_judge_items_refuses_to_mix_judge_models_in_one_output(tmp_path: Path) -> None:
    out = tmp_path / "judged.jsonl"
    agree = _verdict("supported", "unsupported", "conflict")
    await ip.judge_items(
        [_judge_item()], ScriptedJudge(agree, agree), template=TEMPLATE, out_path=out, judge_model=OPUS
    )
    other = ScriptedJudge(agree, agree)
    with pytest.raises(SystemExit):
        await ip.judge_items([_judge_item()], other, template=TEMPLATE, out_path=out, judge_model=SONNET)
    assert other.calls == 0

    # 문항 중간에 남은 표만 있어도 다른 모델로는 잇지 않는다.
    partial = tmp_path / "partial.jsonl"
    with pytest.raises(BudgetExceededError):
        await ip.judge_items(
            [_judge_item()],
            ScriptedJudge(agree, BudgetExceededError("cap")),
            template=TEMPLATE,
            out_path=partial,
            judge_model=OPUS,
        )
    with pytest.raises(SystemExit):
        await ip.judge_items([_judge_item()], other, template=TEMPLATE, out_path=partial, judge_model=SONNET)
    assert other.calls == 0


def test_check_judge_model_refuses_rows_without_a_recorded_model(tmp_path: Path) -> None:
    out = tmp_path / "judged.jsonl"
    ip.check_judge_model(out, OPUS)  # 아직 파일이 없으면 통과
    out.write_text(json.dumps({"itemId": "x1", "promptSha": "s", "decided": [], "votes": []}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ip.check_judge_model(out, OPUS)


def test_cli_registers_impression_commands(tmp_path: Path) -> None:
    import memory_eval_cli

    parser = memory_eval_cli.build_parser()
    args = parser.parse_args(
        ["--run", str(tmp_path), "impression-proto", "--inputs", "a.jsonl", "--candidate", "c.json", "--out", "o.jsonl"]
    )
    assert args.dry_run is False and args.allow_paid is False and args.label == "impression-proto"
    args = parser.parse_args(["--run", str(tmp_path), "impression-judge", "--wording", "w.json", "--out", "j.jsonl"])
    assert args.judge_model == "claude-opus-5-5"
