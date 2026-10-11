"""오프라인 회상 — 체크포인트·문항마다 검색 함수를 돌려 recall@3·@10·순위·점수를 낸다. LLM 없음.

질의는 운영과 같은 모양으로 만든다: 사용자 메시지 = 문항(또는 맥락 턴 문장), 직전 AI 응답 = 그 문항 앞의 진행자 줄. 사용자
쪽·AI 쪽을 어떻게 나눠 명사를 뽑을지는 검색 함수(운영 회상 모듈, 또는 시제품)가 정한다 — 하네스가 둘을 합쳐 따로 질의를 만들면
운영보다 넓은 질의가 되어 수치가 부푼다.

- 한 턴 문항: 앞 줄 = 그 체크포인트 대본의 마지막 진행자 줄.
- 대명사 문항: 맥락 턴(사용자 = 맥락 턴 문장, 앞 줄 = 체크포인트 마지막 진행자 줄)과 질문 턴(사용자 = 질문, 앞 줄 = 맥락 턴
  응답) 두 값. 맥락 턴 응답을 아직 재지 않았으면 맥락 턴 문장을 대리 앞 줄로 쓰고 `context_proxy` 로 표시한다. 일부러 막은
  문항의 반사실 질문(`counterfactualQuestion`)도 같은 앞 줄로 함께 돌린다.
- 기권 문항: 주입이 없어야 하는 질의다.

정답 에피소드 = 심은 턴을 `[start_turn, end_turn]` 에 담고 detail 이 정답 키를 채우는 에피소드. 없으면 그 문항은 추출 실패로
세고 recall 분모에서 뺀다(추출 실패와 검색 실패를 가른다)."""

import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from memory_eval.metrics import answer_matches, recall_at_k, wilson_interval
from memory_eval.plants import PlantSet, offline_entries
from memory_eval.transcript import ScriptTurn


@dataclass(frozen=True)
class Episode:
    id: str
    start_turn: int
    end_turn: int
    title: str
    detail: str
    asserted_by: str
    nouns: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    importance: int = 3
    # 이 에피소드가 검색 대상이 되는 첫 턴(그 스냅샷이 접힌 턴 + 1). 모르면 None — 체크포인트 집계에만 쓴다.
    available_from_turn: int | None = None


@dataclass(frozen=True)
class Ranked:
    """검색 결과 한 줄(순위 순). `injected` 는 임계·상위 3 을 통과해 실제로 실렸는가."""

    episode_id: str
    score: float
    injected: bool


@dataclass(frozen=True)
class RecallQuery:
    item_id: str
    checkpoint: int
    kind: str  # question · context · counterfactual · abstain
    form: str
    split: str
    user_text: str
    previous_assistant: str
    previous_source: str  # checkpoint_line · context_proxy · context_response


class Retriever(Protocol):
    def __call__(
        self, episodes: Sequence[Episode], *, user_text: str, previous_assistant: str, current_turn: int
    ) -> list[Ranked]: ...


def build_queries(
    plant_set: PlantSet,
    script: Sequence[ScriptTurn],
    checkpoint: int,
    *,
    splits: set[str],
    context_responses: Mapping[tuple[str, int], str] | None = None,
) -> list[RecallQuery]:
    by_turn = {t.turn: t for t in script}
    last_line = by_turn[checkpoint].assistant if checkpoint in by_turn else ""
    queries: list[RecallQuery] = []
    for entry in offline_entries(plant_set, checkpoint):
        split = str(entry.get("split", ""))
        if split not in splits:
            continue
        item_id = str(entry["id"])
        form = str(entry.get("questionForm", ""))
        if entry.get("category") == "기권":
            queries.append(
                RecallQuery(
                    item_id, checkpoint, "abstain", form, split, str(entry["question"]), last_line, "checkpoint_line"
                )
            )
            continue
        context = entry.get("contextTurn")
        if form == "anaphora" and context:
            context_line = str(context["userLine"])
            queries.append(
                RecallQuery(item_id, checkpoint, "context", form, split, context_line, last_line, "checkpoint_line")
            )
            measured = (context_responses or {}).get((item_id, checkpoint))
            previous, source = (
                (measured, "context_response") if measured is not None else (context_line, "context_proxy")
            )
            queries.append(
                RecallQuery(item_id, checkpoint, "question", form, split, str(entry["question"]), previous, source)
            )
            if entry.get("counterfactualQuestion"):
                queries.append(
                    RecallQuery(
                        item_id,
                        checkpoint,
                        "counterfactual",
                        form,
                        split,
                        str(entry["counterfactualQuestion"]),
                        previous,
                        source,
                    )
                )
            continue
        queries.append(
            RecallQuery(
                item_id, checkpoint, "question", form, split, str(entry["question"]), last_line, "checkpoint_line"
            )
        )
    return queries


def gold_keys(plant: Mapping[str, Any]) -> list[list[str]]:
    """정답 에피소드·추출 보존의 일치 키. 화자 항목의 정답 키는 귀속("말한 적 없"·인물 이름)이라 에피소드 본문에 있을 이유가
    없으므로 주장 내용 낱말(`keywords`)로 센다."""
    if plant.get("category") == "화자":
        return [[str(k)] for k in plant.get("keywords", [])]
    return [[str(s) for s in bundle] for bundle in plant.get("answerKeys") or []]


def gold_episode_ids(plant: Mapping[str, Any], episodes: Sequence[Episode]) -> list[str]:
    turn = int(plant["plantTurn"])
    keys = gold_keys(plant)
    return [e.id for e in episodes if e.start_turn <= turn <= e.end_turn and answer_matches(e.detail, keys)]


def evaluate_query(ranked: Sequence[Ranked], *, gold: Sequence[str]) -> dict[str, Any]:
    injected = [r.episode_id for r in ranked if r.injected]
    order = [r.episode_id for r in ranked]
    gold_set = set(gold)
    rank = next((i + 1 for i, eid in enumerate(order) if eid in gold_set), None)
    return {
        "injected": injected,
        "top10": order[:10],
        "scores": {r.episode_id: r.score for r in ranked[:10]},
        "gold": list(gold),
        "goldRank": rank,
        "recall3": recall_at_k(injected, gold_set, 3) if gold_set else None,
        "recall10": recall_at_k(order, gold_set, 10) if gold_set else None,
    }


def load_retriever(spec: str) -> Retriever:
    """`모듈:함수` — 운영 회상 모듈을 감싼 어댑터나 시제품 검색 함수."""
    module_name, _, attr = spec.partition(":")
    if not attr:
        raise SystemExit(f"--retriever 는 '모듈:함수' 꼴이어야 한다: {spec!r}")
    retriever: Retriever = getattr(importlib.import_module(module_name), attr)
    return retriever


def load_episodes_json(path: Path) -> list[Episode]:
    """시제품 추출 결과 또는 DB 에서 내보낸 에피소드 목록(JSON 배열, 칸 이름은 이 데이터클래스와 같다)."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        Episode(
            id=str(r["id"]),
            start_turn=int(r["start_turn"]),
            end_turn=int(r["end_turn"]),
            title=str(r.get("title", "")),
            detail=str(r.get("detail", "")),
            asserted_by=str(r.get("asserted_by", "")),
            nouns=tuple(r.get("nouns", [])),
            keywords=tuple(r.get("keywords", [])),
            importance=int(r.get("importance", 3)),
            available_from_turn=r.get("available_from_turn"),
        )
        for r in rows
    ]


def visible_at(episodes: Sequence[Episode], checkpoint: int) -> list[Episode]:
    return [e for e in episodes if e.available_from_turn is None or e.available_from_turn <= checkpoint + 1]


def run_checkpoint(
    plant_set: PlantSet,
    script: Sequence[ScriptTurn],
    checkpoint: int,
    episodes: Sequence[Episode],
    retriever: Retriever,
    *,
    splits: set[str],
    context_responses: Mapping[tuple[str, int], str] | None = None,
) -> list[dict[str, Any]]:
    pool = visible_at(episodes, checkpoint)
    rows = []
    for query in build_queries(plant_set, script, checkpoint, splits=splits, context_responses=context_responses):
        ranked = retriever(
            pool, user_text=query.user_text, previous_assistant=query.previous_assistant, current_turn=checkpoint + 1
        )
        entry = plant_set.item(query.item_id)
        gold = [] if query.kind == "abstain" else gold_episode_ids(entry, pool)
        rows.append({**asdict(query), **evaluate_query(ranked, gold=gold)})
    return rows


def extraction_report(plant_set: PlantSet, episodes: Sequence[Episode], *, splits: set[str]) -> list[dict[str, Any]]:
    """심은 항목마다 추출 보존(정답 에피소드가 있는가)과 화자 귀속(그 에피소드의 `asserted_by`)."""
    rows = []
    for plant in plant_set.plants:
        if str(plant.get("split", "")) not in splits:
            continue
        gold = gold_episode_ids(plant, episodes)
        covering = [e for e in episodes if e.start_turn <= int(plant["plantTurn"]) <= e.end_turn]
        judged = [e for e in episodes if e.id in gold] or covering
        expected = str(plant.get("speaker", {}).get("assertedBy", ""))
        rows.append(
            {
                "item": plant["id"],
                "split": plant.get("split"),
                "preserved": bool(gold),
                "assertedBy": judged[0].asserted_by if judged else None,
                "assertedByExpected": expected,
                "assertedByCorrect": (judged[0].asserted_by == expected) if judged else None,
            }
        )
    return rows


def summarize(rows: Sequence[dict[str, Any]], *, key: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    """recall 비율을 묶음마다 n·윌슨 구간과 함께. 정답 에피소드 없는 문항은 분모에서 빠진다(따로 센다)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    out: dict[str, Any] = {}
    for name, members in sorted(groups.items()):
        scored = [m for m in members if m.get("recall3") is not None]
        k3 = sum(1 for m in scored if m["recall3"])
        k10 = sum(1 for m in scored if m["recall10"])
        n = len(scored)
        out[name] = {
            "n": n,
            "noGold": len(members) - n,
            "recall3": k3 / n if n else None,
            "recall3Wilson": wilson_interval(k3, n),
            "recall10": k10 / n if n else None,
            "recall10Wilson": wilson_interval(k10, n),
        }
    return out


# 직접 형식 합격선의 분모 하한 — 정답 에피소드가 없어 빠진 문항을 뺀 수가 이보다 작으면 판정하지 않는다.
PASSLINE_MIN_N = 5


def direct_passline(rows: Sequence[dict[str, Any]], plant_set: PlantSet, *, threshold: float) -> dict[str, Any]:
    """직접 형식 합격선: 300턴 체크포인트의 직접 형식 질문 턴만, 일부러 실패하게 만든 측정 문항은 분모에서 빼고 따로 보고한다.
    분모가 하한보다 작으면 `halt`(멈추고 묻는다)."""
    designed = sorted(str(e["id"]) for e in plant_set.plants if (e.get("limitProbe") or {}).get("designedToFail"))
    candidates = [r for r in rows if r["kind"] == "question" and r["form"] == "direct" and int(r["checkpoint"]) == 300]
    counted = [r for r in candidates if r["item_id"] not in designed and r.get("recall3") is not None]
    k = sum(1 for r in counted if r["recall3"])
    n = len(counted)
    status = "halt" if n < PASSLINE_MIN_N else ("pass" if k / n >= threshold else "fail")
    return {
        "status": status,
        "n": n,
        "k": k,
        "rate": k / n if n else None,
        "wilson": wilson_interval(k, n),
        "noGold": sorted(r["item_id"] for r in candidates if r.get("recall3") is None and r["item_id"] not in designed),
        "designedToFail": sorted({r["item_id"] for r in candidates if r["item_id"] in designed}),
    }


@dataclass(frozen=True)
class TuningResult:
    tau: float
    common_ratio: float
    direct: float
    anaphora: float
    injection_rate: float


def best_tuning(results: Sequence[TuningResult]) -> TuningResult:
    """튜닝 목적함수(개발 절반, 300턴 체크포인트): 직접 형식 recall@3 최대 → 대명사 질문 턴 recall@3 최대 → 보통 턴 주입률
    최소 → 임계가 큰 쪽."""
    return max(results, key=lambda r: (r.direct, r.anaphora, -r.injection_rate, r.tau))
