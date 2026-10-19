"""임베딩 후보 격자 비교 — 대본 셋의 개발 절반 문항과 체크포인트 템플릿에서 내보낸 장면으로, 후보(모델@차원)마다 견적을 내고
벡터가 다 있는 후보는 명사 단독 / 벡터 단독 / RRF 의 recall@3·@10 을 낸다.

작품 목록 파일(JSON 배열) 한 줄: `{"work", "plants", "splitDir", "transcript", "episodes": {"<체크포인트>": "<장면 JSON>"}}`.
장면 JSON 은 `export-episodes` 출력이다(체크포인트 템플릿마다 하나). 지시어 문항이 있으면 줄에 `"contextResponses"`(잰 맥락 턴
응답 `[{item, checkpoint, reply}]` 파일)를 둔다 — 임베딩 회상은 대리 앞 줄을 받지 않는다. 심기 표는 언제나 개발 보기로만
읽는다 — 시험 정답 파일은 열지 않는다. 질의·장면 글은 `embed-plan` 과 같은 함수로 만들고, 표는 질문 턴(`kind == "question"`)만
센다(맥락 턴·반사실·기권 줄은 빠진다). 명사 쪽은 후보와 상관없어 한 번만 돌리고, 벡터 단독·RRF 는 후보 × 하이브리드 설정 격자
점마다 한 줄이다. RRF 의 명사 쪽은 운영 회상(`server_recall`)이다.

RRF 격자에서 하나를 고르는 일(`select_rrf`)은 커밋된 목적함수 파일의 `rrfGrid` 를 그대로 따른다: `order` 의 기준을 앞에서부터
견주고(`-` 는 작은 쪽, 없으면 큰 쪽), `requirements` 의 조건을 하나라도 지키지 않은(또는 재지 않은) 격자 점은 순위에 넣지
않는다. 조건 `nounOnlyMatchesReference` 는 그 격자 점에서 임베딩이 꺼진 경로(`embed_offline.embedding_off_retriever`)의 결과가
명사 단독 줄과 행마다 같은가다 — 임베딩을 끄면 회상이 명사 단독으로 돌아가야 기존 회상의 기준 벡터와 리플레이가 유지된다."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_eval import embed_offline as eo
from memory_eval import holdout
from memory_eval import recall_offline as ro
from memory_eval.embed_api import Candidate
from memory_eval.plants import PlantSet
from memory_eval.transcript import ScriptTurn, load_transcript

DEV = {"dev"}


@dataclass(frozen=True)
class Work:
    name: str
    plant_set: PlantSet
    script: list[ScriptTurn]
    episodes: dict[int, list[ro.Episode]]
    context_responses: dict[tuple[str, int], str] = field(default_factory=dict)


def load_context_responses(path: Path) -> dict[tuple[str, int], str]:
    return {
        (str(row["item"]), int(row["checkpoint"])): str(row["reply"])
        for row in json.loads(path.read_text(encoding="utf-8"))
    }


def load_works(path: Path) -> list[Work]:
    works = []
    for row in json.loads(path.read_text(encoding="utf-8")):
        split_dir = Path(row["splitDir"])
        plant_set = holdout.load_view(
            Path(row["plants"]), split_dir, DEV, preregistration=split_dir / "not-read", seal_sha=None
        )
        off = [e["id"] for e in plant_set.all_items() if e.get("split") != "dev"]
        if off:
            raise SystemExit(f"{row['work']}: 개발 보기만 쓴다 — 개발이 아닌 문항 {len(off)}개")
        episodes = {int(cp): ro.load_episodes_json(Path(p)) for cp, p in row["episodes"].items()}
        context = load_context_responses(Path(row["contextResponses"])) if row.get("contextResponses") else {}
        works.append(
            Work(str(row["work"]), plant_set, list(load_transcript(Path(row["transcript"]))), episodes, context)
        )
    return works


def missing_rows(works: Sequence[Work], table: eo.EmbeddingTable) -> list[dict[str, str]]:
    """모든 작품·체크포인트에서 이 후보의 벡터가 없는 글(같은 글은 한 번)."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    for work in works:
        for cp, episodes in sorted(work.episodes.items()):
            queries = ro.fusion_query_texts(
                ro.build_queries(work.plant_set, work.script, cp, splits=DEV, context_responses=work.context_responses)
            )
            for row in eo.missing_texts(table, episodes, queries):
                out.setdefault((row["inputType"], row["sha256"]), row)
    return list(out.values())


def recall_rows(works: Sequence[Work], retriever: ro.Retriever, *, fusion: bool = False) -> list[dict[str, Any]]:
    rows = []
    for work in works:
        for cp, episodes in sorted(work.episodes.items()):
            for r in ro.run_checkpoint(
                work.plant_set,
                work.script,
                cp,
                episodes,
                retriever,
                splits=DEV,
                context_responses=work.context_responses,
                fusion=fusion,
            ):
                if r["kind"] == "question":
                    rows.append({**r, "work": work.name})
    return rows


def table_row(
    candidate: str, method: str, rows: Sequence[dict[str, Any]], params: eo.HybridParams | None = None
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "method": method,
        "params": params.config() if params is not None else None,
        "plainInjection": ro.plain_injection(rows),
        "all": ro.summarize(rows, key=lambda r: "all").get("all"),
        "byForm": ro.summarize(rows, key=lambda r: str(r["form"])),
        "byWorkCheckpoint": ro.summarize(rows, key=lambda r: f"{r['work']}:cp{r['checkpoint']}"),
    }


def compare(
    works: Sequence[Work],
    candidates: Sequence[Candidate],
    tables: Mapping[str, eo.EmbeddingTable],
    *,
    nouns: Callable[..., list[ro.Ranked]],
    grid: Sequence[eo.HybridParams] = (eo.DEFAULT_PARAMS,),
) -> list[dict[str, Any]]:
    noun_rows = recall_rows(works, nouns)
    out = [table_row("-", "nouns", noun_rows)]
    # 임베딩이 꺼진 경로는 후보와 상관없어 격자 점마다 한 번만 잰다.
    matches = {
        params: _rows_match(noun_rows, recall_rows(works, eo.embedding_off_retriever(params), fusion=True))
        for params in grid
    }
    for candidate in candidates:
        table = tables[candidate.label]
        for params in grid:
            vector = recall_rows(works, eo.vector_retriever(table, params), fusion=True)
            out.append(table_row(candidate.label, "vector", vector, params))
            hybrid = recall_rows(works, eo.rrf_retriever(table, params), fusion=True)
            row = table_row(candidate.label, "rrf", hybrid, params)
            row["requirements"] = {"nounOnlyMatchesReference": int(matches[params])}
            out.append(row)
    return out


def _rows_match(reference: Sequence[Mapping[str, Any]], other: Sequence[Mapping[str, Any]]) -> bool:
    """작품마다 두 결과가 행 단위(주입 id·상위 10 순서·점수)로 모두 같은가. 행 키에 작품이 없어 작품별로 견준다."""
    for work in sorted({str(r["work"]) for r in [*reference, *other]}):
        a = [r for r in reference if r["work"] == work]
        b = [r for r in other if r["work"] == work]
        if ro.compare_rows(a, b)["mismatches"]:
            return False
    return True


# 목적함수 `rrfGrid` 가 쓸 수 있는 기준과 필수 조건.
RRF_RECALL_FORMS = ("direct", "paraphrase", "anaphora")
RRF_CRITERIA = frozenset({"recallAt3DevSum", "normalTurnMeanInjected"})
RRF_REQUIREMENTS = frozenset({"nounOnlyMatchesReference"})


def rrf_grid_order(objective: Mapping[str, Any]) -> tuple[list[tuple[str, int]], list[str]]:
    """목적함수의 RRF 격자 고르는 순서 — ([(기준, 큰 쪽이 나으면 1 · 작은 쪽이면 -1)], [필수 조건])."""
    grid = objective.get("rrfGrid") or {}
    raw: Sequence[str] = grid.get("order") or []
    order = [(k[1:], -1) if k.startswith("-") else (k, 1) for k in raw]
    requirements = list(grid.get("requirements") or {})
    keys = [k for k, _ in order]
    if not order or set(keys) - RRF_CRITERIA or len(set(keys)) != len(keys):
        raise SystemExit(f"목적함수의 RRF 격자 기준은 {sorted(RRF_CRITERIA)} 중에서 겹치지 않게 적는다: {list(raw)}")
    if set(requirements) - RRF_REQUIREMENTS:
        raise SystemExit(f"목적함수의 RRF 격자 필수 조건은 {sorted(RRF_REQUIREMENTS)} 중에서 적는다: {requirements}")
    return order, requirements


def rrf_criteria(row: Mapping[str, Any]) -> dict[str, float]:
    """표 한 줄의 기준 값. recall@3 합은 세 질문 형식의 recall@3 를 더한다 — 정답 에피소드가 없어 recall 이 없는 형식은 0 이다
    (모든 격자 점이 같은 문항이라 순위를 바꾸지 않는다)."""
    by_form = row["byForm"]
    recall = [(by_form.get(f) or {}).get("recall3") for f in RRF_RECALL_FORMS]
    mean = (row.get("plainInjection") or {}).get("meanPerTurn")
    if mean is None:
        raise SystemExit("보통 턴이 없어 보통 턴 평균 주입을 잴 수 없다 — RRF 격자를 고르지 않는다")
    return {"recallAt3DevSum": float(sum(r for r in recall if r is not None)), "normalTurnMeanInjected": float(mean)}


def select_rrf(table: Sequence[Mapping[str, Any]], objective: Mapping[str, Any]) -> dict[str, Any]:
    """RRF 줄 가운데 필수 조건을 모두 지킨 격자 점을 목적함수 순서로 매겨 하나를 고른다(앞의 것이 낫다). 고를 점이 없으면 None."""
    order, requirements = rrf_grid_order(objective)
    rows = [r for r in table if r["method"] == "rrf"]

    def kept(row: Mapping[str, Any]) -> bool:
        return all((row.get("requirements") or {}).get(name) == 1 for name in requirements)

    def brief(row: Mapping[str, Any]) -> dict[str, Any]:
        return {"candidate": row["candidate"], "params": row["params"], "criteria": rrf_criteria(row),
                "requirements": row.get("requirements")}  # fmt: skip

    def rank(row: Mapping[str, Any]) -> tuple[float, ...]:
        values = rrf_criteria(row)
        return tuple(sign * values[key] for key, sign in order)

    ranked = sorted((r for r in rows if kept(r)), key=rank, reverse=True)
    return {
        "order": [list(o) for o in order],
        "requirements": requirements,
        "ranked": [brief(r) for r in ranked],
        "excluded": [brief(r) for r in rows if not kept(r)],
        "chosen": brief(ranked[0]) if ranked else None,
    }


def _cell(summary: Mapping[str, Any] | None) -> str:
    if not summary or summary.get("recall3") is None:
        return "-"
    return f"{summary['recall3']:.3f} / {summary['recall10']:.3f} (n={summary['n']})"


def _params(params: Mapping[str, Any] | None) -> str:
    """운영 기본값과 다른 설정만 짧게(접두 `memory_embed_recall_` 를 뗀 이름)."""
    if params is None:
        return "-"
    default = eo.DEFAULT_PARAMS.config()
    changed = [f"{k.removeprefix(eo.CONFIG_PREFIX)}={v}" for k, v in params.items() if default.get(k) != v]
    return " ".join(changed) or "기본"


def _mean(plain: Mapping[str, Any] | None) -> str:
    if not plain or plain.get("meanPerTurn") is None:
        return "-"
    return f"{plain['meanPerTurn']:.2f} (n={plain['n']})"


def markdown(table: Sequence[Mapping[str, Any]]) -> str:
    forms = sorted({f for row in table for f in row["byForm"]})
    head = ["후보", "방식", "설정", "전체 @3 / @10", *[f"{f} @3 / @10" for f in forms], "보통 턴 평균 주입"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for row in table:
        cells = [row["candidate"], row["method"], _params(row.get("params")), _cell(row["all"]),
                 *[_cell(row["byForm"].get(f)) for f in forms], _mean(row.get("plainInjection"))]  # fmt: skip
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
