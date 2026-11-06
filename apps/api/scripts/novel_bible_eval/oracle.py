"""오라클 실행의 세트 결함 요약 — 가짜 해석기가 명세 정답을 그대로 낸 실행(`FakeLLM(oracle=True)`)의 결과에서 세트 쪽 결함을
한 표로 모은다. 추출이 정답과 같으므로 아래 갈래는 모두 0 이어야 정상이다 — 하나라도 있으면 그 화·탐침의 명세(또는 규칙과
명세의 어긋남)를 고칠 곳이다.

- (a) 막힌 기본 화 — 규칙과 항목.
- (b) 기대 규칙으로 안 막힌 충돌 탐침 — 닫힌 값 탐침은 기대 갈래·두 값의 모순으로 막혀야 맞다(지표의 판정과 같다).
- (c) 기대 경고를 안 낸 경고 기대 탐침.
- (d) 막힌 비충돌 탐침 — 갈래·세부 종류와 막은 규칙.
- (e) 놓친 정답 — 기본 화(재현율 분모)와 탐침 화에서, 슬롯이 버려 확정 제안에 없는 정답. 슬롯마다 기본 화 재현율을 함께 싣는다.
- (f) 판정에 쓰지 못한 확정 — 실패·끝나지 않은 확정과, 기대는 기본 화가 정본에 없어 지표에서 빠진 탐침. 이것이 있으면 그
  탐침들의 (b)~(d) 는 판정되지 않은 것이다.

행마다 "정답 칸 미기입"을 단다 — 규칙이 읽는데 명세가 적지 않아 오라클이 기본값을 낸 칸이다: 불변 속성이 아닌 사실의 시작
서술(`onset`)·범위(`scope`), 주선 사건의 사용(`uses`). 기본 화 행은 그 화, 탐침 행은 탐침 화와 기대는 기본 화를 본다. 기본값이
맞는 값일 수도 있지만, 그 행이 결함으로 잡혔다면 먼저 확인할 곳이다."""

from collections.abc import Sequence
from dataclasses import dataclass

from novel_bible_eval import metrics
from novel_bible_eval.match import extracted, matched_facts, matched_knowledge, paired_events
from novel_bible_eval.metrics import Ratio
from novel_bible_eval.run import ChapterOutcome
from novel_bible_eval.spec import ChapterSpec, EvalSet, NovelSpec, ProbeSpec

HEADER = "오라클 실행 — 추출 정확도가 아니라 세트·규칙 정합 확인"
CATEGORIES = {
    "blocked_base": "(a) 막힌 기본 화",
    "conflict_missed": "(b) 기대 규칙으로 안 막힌 충돌 탐침",
    "warning_missed": "(c) 기대 경고를 안 낸 경고 기대 탐침",
    "non_conflict_blocked": "(d) 막힌 비충돌 탐침",
    "answer_missed": "(e) 놓친 정답",
    "unjudged": "(f) 판정에 쓰지 못한 확정",
}
UNFILLED_FIELDS = ("onset", "scope", "uses")
_JUDGED = ("committed", "blocked")


@dataclass(frozen=True)
class DefectRow:
    category: str  # `CATEGORIES` 의 열쇠
    where: str  # `소설 3화 반복 1` 또는 `소설 탐침 키`
    detail: str
    items: tuple[str, ...] = ()
    unfilled: tuple[str, ...] = ()


@dataclass(frozen=True)
class SetDefects:
    rows: list[DefectRow]
    recall: dict[str, list[Ratio]]  # 슬롯마다 반복별 기본 화 재현율
    unfilled_total: dict[str, int]  # 세트 전체에서 명세가 적지 않은 칸 수(칸마다)


def _unfilled_fields(chapter: ChapterSpec) -> list[tuple[str, int, str]]:
    """(정답 종류, 차례 1부터, 칸) — 규칙이 읽는데 명세가 적지 않은 칸."""
    fields = [
        ("사실", number, name)
        for number, fact in enumerate(chapter.facts, start=1) if not fact.immutable
        for name in ("onset", "scope") if name not in fact.model_fields_set
    ]
    fields += [
        ("사건", number, "uses")
        for number, event in enumerate(chapter.events, start=1)
        if event.actuality == "present" and "uses" not in event.model_fields_set
    ]
    return fields


def _unfilled(chapter: ChapterSpec, where: str) -> list[str]:
    return [f"{where} {item} {number} {name}" for item, number, name in _unfilled_fields(chapter)]


def _probe_unfilled(novel: NovelSpec, probe: ProbeSpec) -> tuple[str, ...]:
    marks = _unfilled(probe.chapter, "탐침")
    for ordinal in probe.depends_on:
        marks += _unfilled(novel.chapters[ordinal - 1], f"{ordinal}화")
    return tuple(marks)


def _missed(chapter: ChapterSpec, outcome: ChapterOutcome, novel: NovelSpec, slots: Sequence[str]) -> list[str]:
    """확정 제안이 짝짓지 못한 정답. 사실·지식은 매처가 정답 차례대로 제안을 하나씩 가져가므로, 앞 정답까지의 맞춘 수가 그
    정답에서 늘지 않으면 그 정답을 놓친 것이다."""
    found = extracted(outcome)
    missed: list[str] = []
    if "events" in slots:
        paired = paired_events(chapter.events, found.events)
        missed += [
            f"events 사건 {number + 1}「{event.summary}」"
            for number, event in enumerate(chapter.events) if number not in paired
        ]
    if "facts" in slots:
        for number, fact in enumerate(chapter.facts):
            before = matched_facts(chapter.facts[:number], found.facts, novel.aliases)
            if matched_facts(chapter.facts[: number + 1], found.facts, novel.aliases) == before:
                attribute = f" {fact.attribute}" if fact.attribute else ""
                missed.append(f"facts 사실 {number + 1}({fact.subject} {fact.kind}{attribute}: {fact.values[0]})")
    if "knowledge" in slots:
        for number, known in enumerate(chapter.knowledge):
            before = matched_knowledge(chapter.knowledge[:number], found.knowledge, novel.aliases)
            if matched_knowledge(chapter.knowledge[: number + 1], found.knowledge, novel.aliases) == before:
                missed.append(f"knowledge 지식 {number + 1}({known.knower} {known.kind} {known.subject} {known.fact_kind})")
    return missed


def _got(outcome: ChapterOutcome) -> str:
    blocks = ", ".join(outcome.block_rules) or "없음"
    warnings = ", ".join(outcome.warning_rules) or "없음"
    return f"상태 {outcome.status} · 차단 {blocks} · 경고 {warnings}"


def set_defects(eval_set: EvalSet, outcomes: Sequence[ChapterOutcome]) -> SetDefects:
    novels = {novel.key: novel for novel in eval_set.novels}
    probes = {probe.key: (novel, probe) for novel in eval_set.novels for probe in novel.probes}
    canon = {(o.novel, o.ordinal) for o in outcomes if o.probe is None and o.repeat == 1 and o.status == "committed"}
    slots = sorted({job.slot for outcome in outcomes for job in outcome.jobs})
    rows: list[DefectRow] = []
    for outcome in outcomes:
        novel = novels[outcome.novel]
        if outcome.probe is None:
            chapter = novel.chapters[outcome.ordinal - 1]
            where = f"{novel.key} {outcome.ordinal}화 반복 {outcome.repeat}"
            unfilled = tuple(_unfilled(chapter, f"{outcome.ordinal}화"))
        else:
            _, probe = probes[outcome.probe]
            chapter = probe.chapter
            where = f"{novel.key} 탐침 {probe.key}"
            unfilled = _probe_unfilled(novel, probe)
        if outcome.status not in _JUDGED:
            rows.append(DefectRow("unjudged", where, f"검사에 닿지 못함 — {_got(outcome)}", unfilled=unfilled))
            continue
        rows += [
            DefectRow("answer_missed", where, missed, unfilled=unfilled)
            for missed in _missed(chapter, outcome, novel, slots)
        ]
        if outcome.probe is None:
            rows += [
                DefectRow("blocked_base", where, f"차단 {block.rule}", tuple(block.items), unfilled)
                for block in outcome.blocks
            ]
            continue
        if not all((novel.key, ordinal) in canon for ordinal in probe.depends_on):
            rows.append(DefectRow("unjudged", where, f"기대는 기본 화 {probe.depends_on} 중 정본에 없는 화가 있다", unfilled=unfilled))
            continue
        if probe.kind == "conflict":
            hit = outcome.status == "blocked" and probe.expected_rule in outcome.block_rules
            if probe.closed is not None:
                hit = hit and metrics._closed_hit(probe, outcome)
            if not hit:
                rows.append(DefectRow("conflict_missed", where, f"기대 {probe.expected_rule} — {_got(outcome)}",
                                      unfilled=unfilled))
        elif probe.kind == "warning":
            if probe.expected_rule not in outcome.warning_rules:
                rows.append(DefectRow("warning_missed", where, f"기대 {probe.expected_rule} — {_got(outcome)}",
                                      unfilled=unfilled))
        elif outcome.status == "blocked":
            kind = probe.group + (f" · {probe.subkind}" if probe.subkind else "")
            rows.append(DefectRow(
                "non_conflict_blocked", where, f"갈래 {kind} — 차단 {', '.join(outcome.block_rules)}",
                tuple(item for block in outcome.blocks for item in block.items), unfilled,
            ))
    totals = dict.fromkeys(UNFILLED_FIELDS, 0)
    for novel in eval_set.novels:
        chapters = [*novel.chapters, *(probe.chapter for probe in novel.probes)]
        for _, _, name in (field for chapter in chapters for field in _unfilled_fields(chapter)):
            totals[name] += 1
    order = list(CATEGORIES)
    rows.sort(key=lambda row: order.index(row.category))
    return SetDefects(rows=rows, recall=metrics.recall(eval_set, outcomes), unfilled_total=totals)


def _cell(text: str) -> str:
    return text.replace("|", "\\|") or "-"


def defects_markdown(defects: SetDefects) -> str:
    counts = " · ".join(
        f"{label} {sum(row.category == key for row in defects.rows)}" for key, label in CATEGORIES.items()
    )
    recall = " · ".join(
        f"{slot} " + ", ".join(f"{ratio.k}/{ratio.n}" for ratio in ratios) for slot, ratios in defects.recall.items()
    )
    unfilled = " · ".join(f"{name} {count}" for name, count in defects.unfilled_total.items())
    lines = [
        "# 세트 결함 — 오라클 실행", "", HEADER + ". 가짜 해석기가 명세 정답을 그대로 냈으므로 아래 행은 모두 세트(또는 규칙과 "
        "명세의 어긋남) 쪽 결함 후보다. 정상이면 모든 갈래가 0 이다.", "",
        f"갈래별: {counts}", "", f"기본 화 재현율(반복별 맞춤/심음): {recall or '-'}", "",
        f"명세가 채우지 않아 판정에서 기본값을 쓴 칸(세트 전체): {unfilled}", "",
    ]
    if not defects.rows:
        return "\n".join([*lines, "세트 결함 0건.", ""])
    lines += ["| 갈래 | 어디 | 무엇 | 항목 | 정답 칸 미기입 |", "|---|---|---|---|---|"]
    lines += [
        f"| {CATEGORIES[row.category]} | {_cell(row.where)} | {_cell(row.detail)} | {_cell(', '.join(row.items))} | "
        f"{_cell(', '.join(row.unfilled))} |"
        for row in defects.rows
    ]
    return "\n".join([*lines, ""])
