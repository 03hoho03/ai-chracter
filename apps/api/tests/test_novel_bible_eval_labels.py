"""정본 기억 측정 하네스의 사람 라벨 — 세 어댑터 제안을 같은 주장끼리 합치고, 어댑터 이름을 숨긴 라벨 시트로 내보낸 뒤 사람이
내려받은 결과를 읽어 어댑터별 정밀도를 같은 라벨로 센다.

제안·원고는 합성이다. 실제 라벨 원문은 저장소에 두지 않는다."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from api.novel_bible.core.types import EntityName, ItemDraft, Proposal, Proposition, VerifiedQuote
from novel_bible_eval import labels, metrics
from novel_bible_eval.run import ChapterOutcome, JobOutcome

ALPHA, BETA = "adapter-alpha", "adapter-beta"
B1, B2 = uuid.uuid4(), uuid.uuid4()
TEXTS = {str(B1): "서하는 낡은 등불을 닦았다.", str(B2): "도윤은 서하의 등불을 보았다."}


def _quote(block: uuid.UUID, start: int, end: int) -> VerifiedQuote:
    return VerifiedQuote(block_id=block, char_start=start, char_end=end, quote_sha256="0" * 64)


def _fact(key: str, quote: VerifiedQuote, *more: VerifiedQuote, subject: str = "서하") -> ItemDraft:
    proposition = Proposition(subject=subject, kind="possession", attribute=None, value="낡은 등불", holds=True)
    return ItemDraft(
        local_key=key, table="fact", fields={}, quotes=(quote, *more), proposition=proposition,
        names={"subject": (EntityName(kind="character", name=subject),)},
    )


def _knowledge(quote: VerifiedQuote) -> ItemDraft:
    proposition = Proposition(subject="서하", kind="possession", attribute=None, value="낡은 등불", holds=True)
    return ItemDraft(
        local_key="k1", table="knowledge", fields={"kind": "knows"}, quotes=(quote,), proposition=proposition,
        names={"knower": (EntityName(kind="character", name="도윤"),),
               "subject": (EntityName(kind="character", name="서하"),)},
    )


def _event(quote: VerifiedQuote) -> ItemDraft:
    return ItemDraft(
        local_key="event1", table="event", fields={"actuality": "present", "summary": "등불을 닦는다"},
        names={"present": (EntityName(kind="character", name="서하"),)}, quotes=(quote,), covers_blocks=(B1,),
    )


def _outcome(*jobs: tuple[str, tuple[ItemDraft, ...]]) -> ChapterOutcome:
    return ChapterOutcome(
        novel="label-copy", repeat=1, ordinal=1, probe=None, status="committed", block_rules=[], warning_rules=[],
        block_ids=[str(B1), str(B2)],
        jobs=[
            JobOutcome(slot=slot, status="succeeded", attempts=1, failure_code=None,
                       proposal=Proposal(items=items).model_dump(mode="json"), calls=[])
            for slot, items in jobs
        ],
    )


def _runs() -> dict[str, list[ChapterOutcome]]:
    alpha = _outcome(
        # 한 어댑터 안의 중복은 먼저 나온 것 하나로 센다 — 뒤의 인용은 싣지 않는다.
        ("facts", (_fact("f1", _quote(B1, 4, 9)), _fact("f2", _quote(B1, 0, 2)))),
        ("knowledge", (_knowledge(_quote(B2, 0, 2)),)),
    )
    beta = _outcome(
        ("facts", (_fact("f1", _quote(B2, 8, 11)),)),  # 같은 주장, 다른 인용
        ("events", (_event(_quote(B1, 0, 2)),)),
    )
    return {ALPHA: [alpha], BETA: [beta]}


def test_claims_merge_across_adapters_and_keep_every_distinct_quote() -> None:
    claims = labels.merge_claims(_runs(), TEXTS)
    by_slot = {claim.slot: claim for claim in claims}
    assert sorted(by_slot) == ["events", "facts", "knowledge"]
    fact = by_slot["facts"]
    assert fact.quotes == ["낡은 등불", "등불을"]
    assert fact.adapters == {ALPHA: [0], BETA: [1]}
    assert by_slot["knowledge"].adapters == {ALPHA: [0]}
    assert by_slot["events"].adapters == {BETA: [0]}


def test_the_order_adapters_are_merged_in_does_not_change_their_precision() -> None:
    # 알파가 서로 다른 인용 셋을 붙여도 베타의 인용은 실린다 — 주장 전체에 셋 상한을 걸면 뒤에 합친 어댑터는 인용이 없어
    # 맞는 주장도 틀림으로 센다.
    alpha = _outcome(("facts", (_fact("f1", _quote(B1, 0, 2), _quote(B1, 4, 9), _quote(B1, 10, 13)),)))
    beta = _outcome(("facts", (_fact("f1", _quote(B2, 8, 11)),)))
    scores = []
    for runs in ({ALPHA: [alpha], BETA: [beta]}, {BETA: [beta], ALPHA: [alpha]}):
        (claim,) = labels.merge_claims(runs, TEXTS)
        labeled = [labels.LabeledClaim(claim, labels.Label(verdict="correct", quotes=["supported"] * len(claim.quotes)))]
        scores.append({name: (r.k, r.n) for name in (ALPHA, BETA) for r in [metrics.label_precision(labeled, name)]})
    assert scores == [{ALPHA: (1, 1), BETA: (1, 1)}] * 2


def _fill(sheet: list[dict[str, Any]], key: list[labels.Claim]) -> dict[str, Any]:
    slot_of = {claim.id: claim.slot for claim in key}
    verdicts: dict[str, Any] = {}
    for row in sheet:
        slot = slot_of[row["id"]]
        if slot == "facts":
            verdicts[row["id"]] = {"verdict": "correct", "quotes": ["supported", "unsupported"], "memo": ""}
        elif slot == "knowledge":
            verdicts[row["id"]] = {"verdict": "direction", "quotes": ["supported"], "memo": ""}
        else:
            verdicts[row["id"]] = {"verdict": "unknown", "quotes": [None], "memo": "합성 메모"}
    return {"labels": verdicts, "missing": {"1": ""}}


def test_the_sheet_hides_adapters_and_its_result_scores_each_adapter_with_the_same_labels(tmp_path: Path) -> None:
    claims = labels.merge_claims(_runs(), TEXTS)
    sheet_path, key_path = labels.write_sheet(claims, tmp_path, seed=3)
    html = sheet_path.read_text(encoding="utf-8")
    assert ALPHA not in html and BETA not in html
    sheet = labels.sheet_claims(html)
    assert sorted(row["id"] for row in sheet) == sorted(claim.id for claim in claims)
    assert "낡은 등불" in html

    result = tmp_path / "labels-result.json"
    result.write_text(json.dumps(_fill(sheet, claims)), encoding="utf-8")
    labeled = labels.read_labels(result, key_path)

    # 알파: 사실(맞음, 자기 인용 받침) + 지식(방향 틀림) → 1/2. 핵심 사실로 좁히면 1/1.
    assert (metrics.label_precision(labeled, ALPHA).k, metrics.label_precision(labeled, ALPHA).n) == (1, 2)
    core = metrics.label_precision(labeled, ALPHA, core_only=True)
    assert (core.k, core.n) == (1, 1)
    # 베타: 같은 사실이지만 베타가 붙인 인용은 안 받침 → 틀림, 사건은 판단 불가라 분모에서 빠진다 → 0/1.
    assert (metrics.label_precision(labeled, BETA).k, metrics.label_precision(labeled, BETA).n) == (0, 1)
    direction = metrics.label_direction_error(labeled, ALPHA)
    assert (direction.k, direction.n) == (1, 1)


def test_a_result_that_leaves_a_claim_unlabeled_is_refused(tmp_path: Path) -> None:
    claims = labels.merge_claims(_runs(), TEXTS)
    sheet_path, key_path = labels.write_sheet(claims, tmp_path)
    filled = _fill(labels.sheet_claims(sheet_path.read_text(encoding="utf-8")), claims)
    filled["labels"].pop(next(iter(filled["labels"])))
    result = tmp_path / "partial.json"
    result.write_text(json.dumps(filled), encoding="utf-8")
    with pytest.raises(ValueError, match="라벨이 없는 주장"):
        labels.read_labels(result, key_path)
