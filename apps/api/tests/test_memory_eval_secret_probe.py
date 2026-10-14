"""비밀 누출 두 턴 프로브 — 장면 설정 턴 다음에 질문 턴을 보내고, 둘째 턴 전 요약 커서·사실 행 수가 체크포인트 지문과 다르면
그 프로브를 불능으로 둔다."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from memory_eval import probe as probe_mod
from memory_eval.ledger import Ledger
from memory_eval.plants import PlantSet, opus_probes
from memory_eval.probe import BurstPacer, ProbeRun, memory_drift


def _entry(item: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": item,
        "category": "secret",
        "split": "dev",
        "question": "세빈아, 요즘 유나 무슨 일 있대?",
        "setup_turn_text": "동아리방에 세빈이 들어와 가방을 내려놓았다.",
        "probeCheckpoints": {"opus": [300], "offline": [300]},
    }
    base.update(overrides)
    return base


def test_secret_probe_sends_the_scene_setup_first_and_guards_the_memory_before_the_question() -> None:
    plants = PlantSet(
        raw={},
        plants=[_entry("secret-a"), _entry("relation-a", category="relation", setup_turn_text=None)],
        abstains=[],
    )
    secret, relation = opus_probes(plants, 300)
    assert secret.turns == ["동아리방에 세빈이 들어와 가방을 내려놓았다.", "세빈아, 요즘 유나 무슨 일 있대?"]
    assert secret.two_turn and secret.guard_memory
    assert relation.turns == ["세빈아, 요즘 유나 무슨 일 있대?"] and not relation.guard_memory


_CP = {"cursor": ["2026-10-14T00:00:00", "m1"], "factCount": 12, "turnCount": 300, "stats": {"a": "1"}}


@pytest.mark.parametrize(
    ("now", "fields"),
    [
        pytest.param({**_CP, "turnCount": 301, "stats": {"a": "2"}}, [], id="turn-and-stats-may-move"),
        pytest.param({**_CP, "cursor": ["2026-10-14T00:01:00", "m9"]}, ["cursor"], id="new-fold"),
        pytest.param({**_CP, "factCount": 15}, ["factCount"], id="new-facts"),
    ],
)
def test_memory_drift_looks_only_at_the_summary_cursor_and_fact_rows(now: dict[str, Any], fields: list[str]) -> None:
    assert [d.split(":")[0] for d in memory_drift(_CP, now)] == fields


def test_code_without_a_fact_table_has_no_fact_field_on_either_side() -> None:
    cp = {k: v for k, v in _CP.items() if k != "factCount"}
    assert memory_drift(cp, dict(cp)) == []


def _run(tmp_path: Path) -> ProbeRun:
    return ProbeRun(
        stage="s8", arm="B2", room_id=uuid.uuid4(), run_dir=tmp_path, database_url="postgresql+asyncpg://x/lm_eval_w",
        cred_file=tmp_path / "c", cookie_file=tmp_path / "k", port=8130, server_overrides={}, allow_paid=False,
        opus_turn_usd=0.1, judgment_turn_usd=0.0, ledger=Ledger(tmp_path / "ledger.jsonl"),
        pacer=BurstPacer(limit=9, window_seconds=60.0),
    )  # fmt: skip


def test_guard_reads_the_memory_state_a_few_times_and_reports_the_first_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from memory_eval import checkpoint

    reads = iter([dict(_CP), {**_CP, "factCount": 13}, dict(_CP)])
    calls: list[int] = []

    async def read(url: str, room: uuid.UUID) -> dict[str, Any]:
        calls.append(1)
        return next(reads)

    monkeypatch.setattr(checkpoint, "read_fingerprint", read)
    monkeypatch.setattr(probe_mod, "MEMORY_GUARD_INTERVAL_SECONDS", 0.0)
    drift = probe_mod._guard_memory(_run(tmp_path), _CP)
    assert drift == ["factCount: 체크포인트 12 → 지금 13"]
    assert len(calls) == 2


def test_guard_passes_when_every_read_matches_the_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_eval import checkpoint

    async def read(url: str, room: uuid.UUID) -> dict[str, Any]:
        return dict(_CP)

    monkeypatch.setattr(checkpoint, "read_fingerprint", read)
    monkeypatch.setattr(probe_mod, "MEMORY_GUARD_INTERVAL_SECONDS", 0.0)
    assert probe_mod._guard_memory(_run(tmp_path), _CP) == []


def _turns(n: int, *, chars: int = 200) -> list[Any]:
    from api.db.models import ChatMessage, ChatMessageRole

    out: list[Any] = []
    for _ in range(n):
        out.append(ChatMessage(role=ChatMessageRole.USER, content="가" * 30))
        out.append(ChatMessage(role=ChatMessageRole.ASSISTANT, content="나" * chars))
    return out


def test_precheck_finds_the_turn_at_which_a_fold_would_start() -> None:
    from api.chat.memory_fold import FOLD_AT_TURNS

    texts = ["설정", "질문"]
    assert probe_mod.fold_due_offsets(_turns(FOLD_AT_TURNS - 3), texts, reply_chars=200) == []
    assert probe_mod.fold_due_offsets(_turns(FOLD_AT_TURNS - 2), texts, reply_chars=200) == [2]
    assert probe_mod.fold_due_offsets(_turns(FOLD_AT_TURNS - 1), texts, reply_chars=200) == [1, 2]


def test_precheck_assumes_a_generous_reply_length_for_the_character_fold() -> None:
    assert probe_mod.assumed_reply_chars(_turns(3, chars=200)) == probe_mod.ASSUMED_REPLY_CHARS
    assert probe_mod.assumed_reply_chars(_turns(3, chars=4_000)) == 4_000


def _folder(tmp_path: Path, summary: str, prompts: list[str]) -> Path:
    (tmp_path / "memory-snapshots.jsonl").write_text(
        "\n".join(
            json.dumps(r, ensure_ascii=False)
            for r in [{"kind": "roomStatic"}, {"kind": "memorySnapshot", "summary": summary}]
        ),
        encoding="utf-8",
    )
    rows = [{"kind": "generation", "prompt": p} for p in prompts] + [{"kind": "judgment", "prompt": "판정"}]
    (tmp_path / "prompt-dump.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )
    return tmp_path


def test_question_prompt_must_still_carry_the_checkpoint_summary(tmp_path: Path) -> None:
    same = _folder(tmp_path, "[지금] 금요일", ["앞 [지금] 금요일 뒤", "앞 [지금] 금요일 질문"])
    assert probe_mod.summary_drift(same) == []
    changed = _folder(tmp_path, "[지금] 금요일", ["앞 [지금] 금요일 뒤", "앞 [지금] 토요일 질문"])
    assert probe_mod.summary_drift(changed) == ["질문 턴 프롬프트의 요약이 체크포인트 요약과 다르다"]
    missing = _folder(tmp_path, "[지금] 금요일", [])
    assert probe_mod.summary_drift(missing) == ["질문 턴 생성 프롬프트 덤프가 없다"]
