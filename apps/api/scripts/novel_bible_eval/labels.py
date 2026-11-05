"""사람 라벨 — 어댑터들의 추출 제안을 같은 주장끼리 합치고(중복 제거 합집합), 어댑터 이름을 숨긴 로컬 라벨 시트로 내보낸 뒤,
사람이 시트에서 내려받은 결과 JSON 을 읽는다.

주장 키(이름은 코어의 정규화):
- 사실: (화, 주어, 종류, 술어, 값, 유지 여부)
- 지식: (화, 앎 주체, 앎 종류, 명제의 주어·종류·술어·값·유지 여부)
- 사건: (화, 걸친 문단 집합, 현실성, 등장 인물 집합)
별칭이 달라 갈라지는 주장은 합치지 않는다 — 라벨 수가 조금 늘 뿐이고, 잘못 합치면 서로 다른 주장이 한 라벨을 나눠 갖는다.

시트에는 주장의 서로 다른 근거 인용(블록 글에서 위치로 잘라 낸 원문, 어댑터마다 최대 셋)이 실린다. 그래서 시트와 결과는 측정 실행 폴더
(저장소가 추적하지 않는 곳)에만 두고 커밋·게시하지 않는다. 어느 어댑터가 어느 인용을 붙였는지는 시트가 아니라 옆의 열쇠 파일에
있다 — 라벨하는 사람이 어댑터를 알면 판정이 기운다. 열쇠에는 어댑터마다 추출이 멈췄거나 끊긴 까닭도 실린다 — 점수가 앞 화
일부만 담긴 추출로 합격을 내지 않게. 추출 요약(시도 기록·인용 실재율의 화별 수·원가·막힌 화)도 열쇠로 옮겨 라벨 보고서가
싣는다."""

import hashlib
import html
import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from api.novel_bible.core.keys import normalize_name, predicate_norm
from api.novel_bible.core.types import ItemDraft, Proposal, Proposition

from novel_bible_eval.run import ChapterOutcome

Verdict = Literal["correct", "wrong", "direction", "unknown"]
QuoteMark = Literal["supported", "unsupported"]
# 어댑터 하나가 한 주장에 싣는 인용 수 상한. 주장 전체에 상한을 걸면 앞에 합친 어댑터가 자리를 채워 뒤 어댑터의 인용이 빠지고,
# 그 어댑터의 주장은 받침을 볼 인용이 없어 틀림으로 센다 — 합치는 순서가 정밀도를 바꾼다.
_MAX_QUOTES = 3
# 차단 규칙이 읽는 사실 종류 — 핵심 사실 정밀도가 이것으로 좁힌다. 속성은 그 어댑터가 불변이라고 표시한 것만 든다.
_CORE_KINDS = frozenset({"life", "presence", "possession", "ability"})
_SLOT_OF_TABLE = {"fact": "facts", "knowledge": "knowledge", "event": "events"}


class Claim(BaseModel):
    """`adapters` 는 어댑터마다 그 어댑터가 붙인 서로 다른 인용(앞의 셋까지)의 차례(`quotes` 안). 인용을 붙이지 않은 어댑터는 빈
    목록이다. `core` 는 어댑터마다 그 어댑터의 주장이 핵심 사실인가 — 불변 표시는 주장 키에 없어서(사람이 같은 명제를 두 번
    라벨하지 않게) 같은 속성을 한 어댑터는 불변으로, 다른 어댑터는 불변 아님으로 낼 수 있고, 차단 규칙이 읽는 것은 그 어댑터
    자신의 표시다."""

    id: str
    chapter: int
    slot: str
    core: dict[str, bool]
    line: str
    quotes: list[str]
    adapters: dict[str, list[int]]


class Label(BaseModel):
    verdict: Verdict
    quotes: list[QuoteMark | None]
    memo: str = ""


class ExtractionSummary(BaseModel):
    """어댑터 하나의 라벨용 추출 요약 — 추출 결과 파일에 싣고 열쇠로 옮긴다. `attempts` 는 어댑터 호출마다 (연산, 실패 사유 —
    성공은 None)로 스키마 실패율의 재료, `quote` 는 화마다 (검증을 통과해 남은 항목, 남은 + 인용 때문에 버린 항목), `cost` 는
    작업 호출 기록의 원가·지연, `blocked` 는 막힌 화 → 막은 규칙. 사람 라벨 세트는 실제 소설이라 차단이 진짜 모순일 수 있어
    차단 오탐에 넣지 않고 따로 적는다."""

    attempts: list[tuple[str, str | None]]
    quote: list[tuple[int, int]]
    cost: dict[str, Any]
    blocked: dict[int, list[str]]


@dataclass(frozen=True)
class LabeledClaim:
    claim: Claim
    label: Label


def _fact_line(proposition: Proposition) -> str:
    attribute = f" · {proposition.attribute}" if proposition.attribute else ""
    negated = "" if proposition.holds else " (아님)"
    return f"{proposition.subject} · {proposition.kind}{attribute} · {proposition.value}{negated}"


def _proposition_key(proposition: Proposition) -> tuple[Any, ...]:
    return (
        normalize_name(proposition.subject), proposition.kind,
        predicate_norm(proposition.kind, proposition.attribute), normalize_name(proposition.value), proposition.holds,
    )


def _describe(item: ItemDraft, order: Mapping[str, int]) -> tuple[tuple[Any, ...], str, bool] | None:
    """(주장 키, 한 줄 서술, 핵심 사실인가). 라벨하지 않는 항목(회상 관계)은 None."""
    proposition = item.proposition
    if item.table == "fact" and proposition is not None:
        core = proposition.kind in _CORE_KINDS or (
            proposition.kind == "attribute" and item.fields.get("immutable") is True
        )
        return _proposition_key(proposition), _fact_line(proposition), core
    if item.table == "knowledge" and proposition is not None and item.names.get("knower"):
        knower = item.names["knower"][0].name
        kind = str(item.fields.get("kind"))
        verb = "안다" if kind == "knows" else "믿는다"
        line = f"{knower} 가 {verb} — {_fact_line(proposition)}"
        return (normalize_name(knower), kind, *_proposition_key(proposition)), line, False
    if item.table == "event":
        paragraphs = tuple(sorted(order[str(block)] for block in item.covers_blocks if str(block) in order))
        present = tuple(sorted({normalize_name(name.name) for name in item.names.get("present", ())}))
        actuality = str(item.fields.get("actuality"))
        line = f"{item.fields.get('summary', '')} · 등장 {', '.join(present) or '없음'} · {actuality}"
        return (paragraphs, actuality, present), line, False
    return None


def merge_claims(runs: Mapping[str, Sequence[ChapterOutcome]], block_texts: Mapping[str, str]) -> list[Claim]:
    """`runs` 는 어댑터마다 그 어댑터 사본의 확정 결과, `block_texts` 는 블록 id → 블록 글. 한 어댑터 안의 중복 주장은 하나로
    센다(먼저 나온 것의 인용)."""
    merged: dict[tuple[Any, ...], Claim] = {}
    for adapter, outcomes in runs.items():
        for outcome in outcomes:
            order = {block: number for number, block in enumerate(outcome.block_ids, start=1)}
            for job in outcome.jobs:
                if job.proposal is None:
                    continue
                for item in Proposal.model_validate(job.proposal).items:
                    described = _describe(item, order)
                    if described is None:
                        continue
                    key_tail, line, core = described
                    key = (outcome.ordinal, _SLOT_OF_TABLE[item.table], *key_tail)
                    claim = merged.setdefault(
                        key,
                        Claim(
                            id=hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:16],
                            chapter=outcome.ordinal, slot=_SLOT_OF_TABLE[item.table], core={}, line=line,
                            quotes=[], adapters={},
                        ),
                    )
                    if adapter in claim.adapters:
                        continue
                    indices: list[int] = []
                    for quote in item.quotes:
                        if len(indices) == _MAX_QUOTES:
                            break
                        text = block_texts[str(quote.block_id)][quote.char_start:quote.char_end]
                        if text not in claim.quotes:
                            claim.quotes.append(text)
                        if (index := claim.quotes.index(text)) not in indices:
                            indices.append(index)
                    claim.adapters[adapter] = indices
                    claim.core[adapter] = core
    return list(merged.values())


_SHEET = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>정본 기억 라벨 시트</title>
<style>
:root{color-scheme:light dark;--bg:#fafafa;--fg:#1d1d1f;--line:#d0d0d4;--muted:#66666c}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--fg:#e6e6e8;--line:#3a3a3e;--muted:#a0a0a6}}
body{margin:0 auto;max-width:760px;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,sans-serif}
.claim{border-top:1px solid var(--line);padding:12px 0}.meta{color:var(--muted);font-size:12px}
blockquote{margin:6px 0;padding-left:10px;border-left:3px solid var(--line)}textarea{width:100%;box-sizing:border-box}
label{margin-right:12px}button{font:inherit;padding:6px 12px}
</style></head><body>
<h1>정본 기억 라벨 시트</h1>
<p class="meta">주장마다 판정 하나와 인용마다 받침 여부를 고른다. 작업 중 값은 이 브라우저에만 남는다. 끝나면 결과를 내려받는다.</p>
<div id="sheet"></div>
<button id="download" type="button">결과 JSON 내려받기</button>
<script type="application/json" id="claims">__CLAIMS__</script>
<script>
const claims = JSON.parse(document.getElementById("claims").textContent);
const storeKey = "novel-bible-labels-__SHEET_ID__";
let state = {labels: {}, missing: {}};
try { state = JSON.parse(localStorage.getItem(storeKey)) || state; } catch (e) {}
function save() { try { localStorage.setItem(storeKey, JSON.stringify(state)); } catch (e) {} }
function entry(claim) {
  return state.labels[claim.id] ||= {verdict: null, quotes: claim.quotes.map(() => null), memo: ""};
}
const verdicts = [["correct", "맞음"], ["wrong", "틀림"], ["direction", "방향 틀림"], ["unknown", "판단 불가"]];
function radios(name, options, current, onPick) {
  const box = document.createElement("div");
  for (const [value, text] of options) {
    const label = document.createElement("label");
    const input = Object.assign(document.createElement("input"), {type: "radio", name, value, checked: current === value});
    input.addEventListener("change", () => { onPick(value); save(); });
    label.append(input, " " + text);
    box.append(label);
  }
  return box;
}
const sheet = document.getElementById("sheet");
let chapter = null;
for (const claim of claims) {
  if (claim.chapter !== chapter) {
    chapter = claim.chapter;
    const head = document.createElement("h2");
    head.textContent = chapter + "화";
    const missing = Object.assign(document.createElement("textarea"), {placeholder: "이 화에서 빠진 핵심(자유 기록)"});
    missing.value = state.missing[chapter] || "";
    missing.addEventListener("input", () => { state.missing[chapter] = missing.value; save(); });
    sheet.append(head, missing);
  }
  const row = entry(claim);
  const box = document.createElement("section");
  box.className = "claim";
  const meta = Object.assign(document.createElement("div"), {className: "meta", textContent: claim.slot});
  const line = Object.assign(document.createElement("p"), {textContent: claim.line});
  const options = claim.slot === "knowledge" ? verdicts : verdicts.filter(([value]) => value !== "direction");
  box.append(meta, line, radios(claim.id, options, row.verdict, (value) => { row.verdict = value; }));
  claim.quotes.forEach((quote, index) => {
    const text = Object.assign(document.createElement("blockquote"), {textContent: quote});
    const marks = [["supported", "받침"], ["unsupported", "안 받침"]];
    box.append(text, radios(claim.id + "-q" + index, marks, row.quotes[index], (value) => { row.quotes[index] = value; }));
  });
  const memo = Object.assign(document.createElement("textarea"), {placeholder: "메모", value: row.memo});
  memo.addEventListener("input", () => { row.memo = memo.value; save(); });
  box.append(memo);
  sheet.append(box);
}
document.getElementById("download").addEventListener("click", () => {
  const labels = Object.fromEntries(Object.entries(state.labels).filter(([, row]) => row.verdict));
  const blob = new Blob([JSON.stringify({labels, missing: state.missing}, null, 2)], {type: "application/json"});
  const link = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob), download: "labels-" + new Date().toISOString().slice(0, 10) + ".json",
  });
  link.click();
});
</script></body></html>
"""
_EMBEDDED = re.compile(r'<script type="application/json" id="claims">(.*?)</script>', re.DOTALL)


def write_sheet(
    claims: Sequence[Claim], out_dir: Path, *, halted: Mapping[str, str | None],
    extraction: Mapping[str, ExtractionSummary] | None = None, seed: int = 0,
) -> tuple[Path, Path]:
    """시트(`sheet.html`, 화 순서로 묶되 화 안에서 시드로 섞음 — 어댑터 순서가 드러나지 않게)와 열쇠(`claims-key.json`)를
    쓴다. `halted` 는 합친 어댑터마다 그 추출의 멈춤·끊김 까닭(끝까지 돌았으면 None), `extraction` 은 어댑터마다 추출 요약이고
    둘 다 열쇠에만 싣는다."""
    shuffled = list(claims)
    random.Random(seed).shuffle(shuffled)
    shuffled.sort(key=lambda claim: claim.chapter)
    rows = [claim.model_dump(include={"id", "chapter", "slot", "line", "quotes"}) for claim in shuffled]
    embedded = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    sheet_id = hashlib.sha256("".join(claim.id for claim in shuffled).encode()).hexdigest()[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "sheet.html"
    sheet.write_text(_SHEET.replace("__CLAIMS__", embedded).replace("__SHEET_ID__", html.escape(sheet_id)),
                     encoding="utf-8")
    key = out_dir / "claims-key.json"
    written = {
        "halted": dict(halted),
        "extraction": {name: summary.model_dump(mode="json") for name, summary in (extraction or {}).items()},
        "claims": [claim.model_dump() for claim in claims],
    }
    key.write_text(json.dumps(written, ensure_ascii=False, indent=2), encoding="utf-8")
    return sheet, key


def sheet_claims(sheet_html: str) -> list[dict[str, Any]]:
    found = _EMBEDDED.search(sheet_html)
    assert found is not None, "라벨 시트에 주장 목록이 없다"
    rows: list[dict[str, Any]] = json.loads(found.group(1))
    return rows


def read_labels(result: Path, key: Path) -> list[LabeledClaim]:
    """시트 결과와 열쇠를 맞춘다. 라벨이 빠진 주장이 있거나 인용 칸 수가 다르면 거절한다 — 덜 채운 시트를 조용히 세면 분모가
    줄어 정밀도가 그 주장 없이 나온다."""
    claims = [Claim.model_validate(row) for row in json.loads(key.read_text(encoding="utf-8"))["claims"]]
    raw = json.loads(result.read_text(encoding="utf-8"))["labels"]
    missing = [claim.id for claim in claims if claim.id not in raw]
    if missing:
        raise ValueError(f"라벨이 없는 주장이 {len(missing)}건 있다")
    labeled = [LabeledClaim(claim, Label.model_validate(raw[claim.id])) for claim in claims]
    if any(len(row.label.quotes) != len(row.claim.quotes) for row in labeled):
        raise ValueError("인용 칸 수가 열쇠와 다른 라벨이 있다")
    return labeled


def read_halted(key: Path) -> dict[str, str | None]:
    """열쇠에 실린 어댑터마다의 추출 멈춤·끊김 까닭(끝까지 돌았으면 None)."""
    halted: dict[str, str | None] = json.loads(key.read_text(encoding="utf-8"))["halted"]
    return halted


def read_extraction(key: Path) -> dict[str, ExtractionSummary]:
    """열쇠에 실린 어댑터마다의 추출 요약."""
    rows = json.loads(key.read_text(encoding="utf-8"))["extraction"]
    return {name: ExtractionSummary.model_validate(row) for name, row in rows.items()}
