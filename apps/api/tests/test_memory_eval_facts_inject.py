"""사실 주입 재측정 — 현 운영 갈래와 그 위에 사실 주입만 켠 갈래를 견주는 정의(갈래·효과·문턱 표), 질의 임베딩 상한이 두 갈래에
같게 실리는지, 관찰 칸 둘(비밀이 아는 사람 없는 사실 행으로 실림 · 사용자 주장 행 실림), 실린 행 정리. 문항·이름·사실은 전부
지어낸 것이다."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from api.db.models.chat import ChatMemoryFact
from memory_eval import facts_inject as fi
from memory_eval import knowledge_recompute as kr
from memory_eval import verdict_v4 as v4
from memory_eval.arm_env import BUNDLE1_SWITCHES, bundle1_env_pairs
from memory_eval.embed_offline import HybridParams

CP = 300


def test_the_two_arms_are_current_production_and_the_same_plus_fact_injection() -> None:
    """기준 갈래는 장면 회상·요약 비밀 표기·지식 범위 필터·임베딩 회상을 켜고 사실 주입만 끈 갈래, 비교 갈래는 거기에 사실 주입만
    더 켠 갈래다. 질의 임베딩 상한을 3000 으로 주면 두 갈래 env 에 같이 실리고, 두 env 는 사실 주입 한 줄만 다르다."""

    def env(arm: str) -> dict[str, str]:
        return dict(
            bundle1_env_pairs(
                arm, lane="story", embed_model="voyage-4", embed_dims=512, recall=HybridParams(), embed_timeout_ms=3000
            )
        )

    current, facts = env(fi.CURRENT_ARM), env(fi.FACTS_ARM)
    assert {name: current[name] for name in BUNDLE1_SWITCHES} == {
        "MEMORY_EPISODES_RECALL": "true",
        "MEMORY_SUMMARY_SECRET_MARKING": "true",
        "MEMORY_KNOWLEDGE_FILTER": "true",
        "MEMORY_FACTS_INJECT": "false",
        "MEMORY_EMBED_RECALL": "true",
    }
    assert current["MEMORY_EMBED_WRITE"] == "true"
    assert current["MEMORY_EMBED_RECALL_TIMEOUT_MS"] == facts["MEMORY_EMBED_RECALL_TIMEOUT_MS"] == "3000"
    assert {k for k in current.keys() | facts.keys() if current.get(k) != facts.get(k)} == {"MEMORY_FACTS_INJECT"}


def test_the_probe_command_takes_the_query_embedding_timeout_per_run() -> None:
    from memory_eval_cli import build_parser

    for arm in (fi.CURRENT_ARM, fi.FACTS_ARM):
        args = build_parser().parse_args(
            ["--run", "r", "probe", "--plants", "p.json", "--stage", "s", "--arm", arm,
             "--memory-embed-recall-timeout-ms", "3000"]
        )  # fmt: skip
        assert args.memory_embed_recall_timeout_ms == 3000


def _items(category: str, n: int) -> list[dict[str, Any]]:
    return [{"id": f"{category}{i:02d}", "category": category, "split": "test", "score_checkpoint": CP} for i in range(n)]


def _effect_case(fails_current: int, fails_facts: int, n: int = 56) -> tuple[list[dict[str, Any]], ...]:
    """관계 문항 `n` 개. 앞 `fails_current` 개는 기준 갈래만, 그다음 `fails_facts` 개는 사실 주입 갈래만 틀린다."""
    items = _items("relation", n)
    scores = [{"arm": arm, "item": e["id"], "checkpoint": CP, "status": "accept"}
              for arm in (fi.CURRENT_ARM, fi.FACTS_ARM) for e in items]  # fmt: skip
    current = ["stale"] * fails_current + ["current"] * (n - fails_current)
    facts = ["current"] * fails_current + ["stale"] * fails_facts + ["current"] * (n - fails_current - fails_facts)
    judged = [{"arm": arm, "item": e["id"], "checkpoint": CP, "judged": v}
              for arm, values in ((fi.CURRENT_ARM, current), (fi.FACTS_ARM, facts))
              for e, v in zip(items, values, strict=True)]  # fmt: skip
    return items, scores, judged


def test_the_effect_contrasts_current_production_against_fact_injection_with_a_family_of_one() -> None:
    """효과는 기준 갈래 → 사실 주입 갈래 하나다. 가족이 하나라 Holm 문턱이 0.05 그대로다 — 묶음 판정의 사실 주입 효과(요약 표기
    갈래 → 사실 주입 갈래)를 그대로 쓰면 기준 갈래 행이 없어 멈춘다."""
    assert fi.EFFECTS == {
        fi.EFFECT: (fi.CURRENT_ARM, fi.FACTS_ARM, ("relation", "correction", "false_premise"), "judged")
    }
    items, scores, judged = _effect_case(10, 0)
    out = fi.effects([items], scores, judged)
    effect = out[fi.EFFECT]
    assert effect["arms"] == [fi.CURRENT_ARM, fi.FACTS_ARM]
    assert (effect["n"], effect["bOnly"], effect["aOnly"]) == (56, 10, 0)
    assert effect["p"] == pytest.approx(2**-10)
    assert out["holm"]["m"] == 1 and effect["holmThreshold"] == 0.05
    assert effect["status"] == "pass"
    # 사실 주입 쪽이 더 틀리면 통과하지 않는다(단측).
    items, scores, judged = _effect_case(0, 10)
    assert fi.effects([items], scores, judged)[fi.EFFECT]["status"] == "fail"
    # 묶음 판정 표는 그대로다.
    assert v4.EFFECTS["E1"][:2] == ("b1-B1", "b1-B2")  # cite-ok: 기존 효과 표의 키 문자열이다
    assert v4.effect_family([items], scores, judged)["E1"]["status"] == "halt"  # cite-ok: 기존 효과 표의 키 문자열이다


def test_the_effect_floor_comes_from_the_seed_total_with_the_same_categories() -> None:
    seeds = {"totals": [{"name": "facts", "categories": ["false_premise", "relation", "correction"], "min": 40},
                        {"name": "embed", "categories": ["rephrase"], "min": 30}]}  # fmt: skip
    assert fi.effect_floors(seeds) == {fi.EFFECT: 40}


def test_the_power_table_uses_the_single_effect_family_threshold() -> None:
    table = fi.power_table({f"effect:{fi.EFFECT}": 56, "secret:story": 64}, max_c=2)
    effect = table[f"effect:{fi.EFFECT}"]
    assert effect["alpha"] == [0.05]
    assert effect["minB"]["0.05"] == [v4.min_discordant(0.05, c, n=56) for c in range(3)]
    assert table["secret:story"]["alpha"] == v4.SAFETY_ALPHA
    # 묶음 판정 표는 여전히 판정 효과 둘의 Holm 문턱을 낸다.
    assert len(v4.power_table({"effect:E1": 56}, max_c=0)["effect:E1"]["alpha"]) == 2  # cite-ok: 기존 효과 키다
    with pytest.raises(SystemExit):
        v4.power_table({f"effect:{fi.EFFECT}": 56}, max_c=0)


SECRET = {
    "id": "s01",
    "category": "secret",
    "keywords": ["빨간우산", "옥상열쇠"],
    "secretOwner": "도윤",
    "expected_fact": {"known_by": ["도윤"]},
}


def _recorded(**fields: Any) -> dict[str, Any]:
    return {"factId": str(uuid.uuid4()), "found": True, "knownBy": None, "assertedBy": "character", "text": ""} | fields


def _recompute(arm: str, item: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"arm": arm, "item": item, "checkpoint": CP, "userNames": ["사용자"], "recordedRows": rows}


def test_observations_count_a_secret_loaded_as_a_fact_row_nobody_was_said_to_know() -> None:
    public = _recorded(text="도윤 옥상열쇠 빨간우산 아래 숨김")
    known = _recorded(text="도윤 옥상열쇠 빨간우산 아래 숨김", knownBy=["도윤"])
    unrelated = _recorded(text="하늘 맑음")
    rows = [
        _recompute(fi.FACTS_ARM, "s01", [public, unrelated]),
        _recompute(fi.FACTS_ARM, "s01", [known]),
        _recompute(fi.FACTS_ARM, "s01", [unrelated]),
        _recompute(fi.CURRENT_ARM, "s01", [public]),
    ]
    out = fi.observations([SECRET, *_items("relation", 1)], rows)
    assert (out["probes"], out["secretProbes"], out["secretLoadedAsPublicFact"]) == (3, 3, 1)


def test_observations_count_user_claim_rows_loaded_and_rows_missing_from_the_template() -> None:
    rows = [
        _recompute(fi.FACTS_ARM, "relation00", [_recorded(assertedBy="user"), _recorded(assertedBy="user"),
                                                _recorded(assertedBy="narration")]),
        _recompute(fi.FACTS_ARM, "relation01", [_recorded(assertedBy="user"), {"factId": "x", "found": False}]),
        _recompute(fi.CURRENT_ARM, "relation00", [_recorded(assertedBy="user")]),
    ]  # fmt: skip
    out = fi.observations(_items("relation", 2), rows)
    assert out == {"probes": 2, "secretProbes": 0, "secretLoadedAsPublicFact": 0, "userClaimRowsLoaded": 3,
                   "recordedRowsNotInTemplate": 1}  # fmt: skip


def _fact(**fields: Any) -> ChatMemoryFact:
    base: dict[str, Any] = {"id": uuid.uuid4(), "subject": "도윤", "object": None, "attribute": "숨긴 곳",
                            "value": "옥상", "known_by": None, "asserted_by": "character"}  # fmt: skip
    return ChatMemoryFact(**(base | fields))


def test_recorded_rows_carry_known_by_speaker_and_text_in_recorded_order() -> None:
    public = _fact()
    secret = _fact(known_by=["도윤"], asserted_by="user", object="서아", attribute=None, value="비밀")
    stray = str(uuid.uuid4())
    out = kr.recorded_rows([public, secret], [{"factId": str(secret.id)}, {"factId": stray}, {"factId": str(public.id)}])
    assert out == [
        {"factId": str(secret.id), "found": True, "knownBy": ["도윤"], "assertedBy": "user", "text": "도윤 서아 비밀"},
        {"factId": stray, "found": False},
        {"factId": str(public.id), "found": True, "knownBy": None, "assertedBy": "character", "text": "도윤 숨긴 곳 옥상"},
    ]
    assert kr.recorded_rows([public], None) == []


def test_the_summary_command_refuses_the_fact_arm_without_a_facts_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    def write(name: str, rows: list[dict[str, Any]], *, lines: bool = False) -> str:
        path = tmp_path / name
        text = "".join(json.dumps(r) + "\n" for r in rows) if lines else json.dumps(rows)
        path.write_text(text, encoding="utf-8")
        return str(path)

    arms = (fi.CURRENT_ARM, fi.FACTS_ARM)
    judged = write("judged.json", [{"arm": a, "item": "q1", "checkpoint": CP, "judged": "current"} for a in arms])
    probes = write(
        "probes.jsonl",
        [{"arm": a, "item": "q1", "checkpoint": CP, "status": "accept", "turns": [{"user": "u", "reply": "r"}],
          "queryEmbeddings": [{"callSite": "chat_memory_query_embedding", "outcome": "ok"}],
          "memoryFacts": [[{"factId": "f", "chars": 1}]]} for a in arms],
        lines=True,
    )  # fmt: skip
    recompute = write(
        "recompute.json", [{"arm": a, "item": "q1", "checkpoint": CP, "hiddenEpisodes": 1, "reclassified": 1} for a in arms]
    )
    base = ["--run", str(tmp_path), "facts-inject-summary", "--split", "dev", "--story", "p.json", "s",
            "--scores", judged, "--judged", judged, "--ran-probes", probes, "--ran-recompute", recompute,
            "--out", str(tmp_path / "out.json")]  # fmt: skip
    assert main(base) == 2
    assert "--ran-facts-min" in capsys.readouterr().err
    assert main([*base, "--ran-facts-min", "2"]) == 2
    assert "factsLoadedTurns=1 (문턱 2)" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()
