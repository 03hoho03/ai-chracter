"""측정 하네스 CLI 의 판정·집계 묶음 — 오프라인 회상·임베딩 비교, 채점·판정·대조군, 라벨링 입력, 최종 비교 판정, 판정기 일치율과
그 표본 준비, 문안 시제품 지표.

진입점(`memory_eval_cli.py`)이 인프라 묶음 다음에 이 모듈의 `register` 를 부른다. 판정 모듈은 명령 함수와 `register` 안에서만
import 한다 — 진입점을 import 하는 것만으로 판정 모듈이 끌려오지 않게. 인프라 묶음의 `probe`·`trajectory-replay` 에는 판정
모듈이 필요한 인자(판정 종류 거르기, 앞 블록·길이 판정 요약)를 여기서 덧붙인다(`_extend_infra`)."""

import argparse
import asyncio
import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from memory_eval import checkpoint, holdout, plants as plants_mod
from memory_eval.cli_common import (
    DEFAULT_SEED_JSON,
    _db_url,
    _embedding_table,
    _hybrid_args,
    _hybrid_params,
    _ints,
    _ledger,
    _paid,
    _plant_view,
    _print,
    _probe_rows,
    _splits,
    _write,
    data_file,
    paid,
    with_plants,
    with_splits,
)
from memory_eval.ledger import Ledger
from memory_eval.seal import PREREGISTRATION_FILE, require_seal
from memory_eval.transcript import load_transcript


def cmd_recall_offline(args: argparse.Namespace) -> int:
    from memory_eval import recall_offline as ro

    splits = _splits(args)
    plant_set = _plant_view(args, splits)
    script = load_transcript(args.transcript)
    context = _context_responses(args)
    cps = _ints(args.checkpoints)
    if args.dry_run:
        _print(
            {
                str(cp): [
                    {
                        "item": q.item_id,
                        "kind": q.kind,
                        "form": q.form,
                        "split": q.split,
                        "previousSource": q.previous_source,
                    }
                    for q in ro.build_queries(plant_set, script, cp, splits=splits, context_responses=context)
                ]
                for cp in cps
            }
        )
        return 0
    episodes = ro.load_episodes_json(args.episodes)
    retriever = _offline_retriever(args)
    rows = [
        r
        for cp in cps
        for r in ro.run_checkpoint(
            plant_set,
            script,
            cp,
            episodes,
            retriever,
            splits=splits,
            context_responses=context,
            fusion=bool(args.fusion),
        )
    ]
    fusion = {
        "method": args.fusion,
        "model": args.embed_model,
        "dims": args.embed_dims,
        "params": _hybrid_params(args).config(),
    }
    report = {
        **({"fusion": fusion} if args.fusion else {}),
        "splits": sorted(splits),
        "rows": rows,
        "plainInjection": ro.plain_injection(rows),
        "byForm": ro.summarize(rows, key=lambda r: f"cp{r['checkpoint']}:{r['kind']}:{r['form']}"),
        "extraction": ro.extraction_report(plant_set, episodes, splits=splits),
    }
    _write(args.out, report)
    print(f"{len(rows)}문항 → {args.out}")
    return 0


def _context_responses(args: argparse.Namespace) -> dict[tuple[str, int], str]:
    from memory_eval.embed_compare import load_context_responses

    return load_context_responses(args.context_responses) if args.context_responses else {}


SERVER_RETRIEVER = "memory_eval.server_recall:retrieve_server"


def _require_server_nouns(retriever: str | None) -> None:
    if retriever and retriever != SERVER_RETRIEVER:
        raise SystemExit(
            f"RRF 의 명사 쪽은 운영 회상({SERVER_RETRIEVER})이다 — 다른 검색 함수와 합치지 않는다: {retriever}"
        )


def _hybrid_grid(args: argparse.Namespace) -> list[Any]:
    """격자 축(쉼표 목록) 각각의 곱. 축 순서는 설정 순서다."""
    import itertools

    from memory_eval import embed_offline as eo

    names = list(eo.HybridParams.__dataclass_fields__)
    axes = [getattr(args, f"{eo.CONFIG_PREFIX}{name}") for name in names]
    return [eo.HybridParams(**dict(zip(names, point, strict=True))) for point in itertools.product(*axes)]


def _offline_retriever(args: argparse.Namespace) -> Any:
    """명사 단독은 `--retriever` 그대로. 벡터 단독·RRF 는 벡터 파일과 하이브리드 설정으로 — RRF 의 명사 쪽은 운영 회상이다."""
    from memory_eval import embed_offline as eo
    from memory_eval import recall_offline as ro

    if not args.fusion:
        return ro.load_retriever(args.retriever)
    if args.embeddings is None:
        raise SystemExit("벡터·RRF 회상은 --embeddings 벡터 파일이 있어야 한다")
    table = _embedding_table(args)
    params = _hybrid_params(args)
    if args.fusion == "vector":
        return eo.vector_retriever(table, params)
    _require_server_nouns(args.retriever)
    return eo.rrf_retriever(table, params)


def cmd_embed_plan(args: argparse.Namespace) -> int:
    """벡터 파일에 없는 장면 글·질의 글을 JSONL 로 쓴다(벡터를 계산할 입력). 질의는 고른 절반의 문항만 — 개발 보기면 시험
    문항의 글은 나가지 않는다. 질의 글은 recall-offline 의 임베딩 회상이 보내는 것과 같다(이번 사용자 메시지 + 직전 응답, 지시어
    문항의 맥락 턴 질의 포함, 질문 턴의 직전 응답은 잰 맥락 턴 응답). 호출 없음."""
    from memory_eval import embed_offline as eo
    from memory_eval import recall_offline as ro

    splits = _splits(args)
    plant_set = _plant_view(args, splits)
    script = load_transcript(args.transcript)
    episodes = ro.load_episodes_json(args.episodes)
    context = _context_responses(args)
    queries = ro.fusion_query_texts(
        [
            q
            for cp in _ints(args.checkpoints)
            for q in ro.build_queries(plant_set, script, cp, splits=splits, context_responses=context)
        ]
    )
    rows = eo.missing_texts(_embedding_table(args), episodes, queries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"벡터가 없는 글 {len(rows)}개 → {args.out}")
    return 0


def cmd_embed_compare(args: argparse.Namespace) -> int:
    """후보 격자를 개발 절반에서 견준다: 후보마다 빠진 글의 견적 → (`--allow-paid` 면 채우고) → 벡터가 다 있는 후보의 명사
    단독·벡터 단독·RRF recall@3·@10 표. `--dry-run` 은 견적만 낸다."""
    from memory_eval import embed_api as ea
    from memory_eval import embed_compare as ec
    from memory_eval import recall_offline as ro
    from memory_eval.embed_offline import EmbeddingTable

    _require_server_nouns(args.retriever)
    objective = None
    if args.objective is not None:
        from memory_eval.objective import load_committed_objective, refuse_result_from_other_objective

        objective = load_committed_objective(args.objective)
        ec.rrf_grid_order(objective["objective"])
        refuse_result_from_other_objective(args.out, objective)
    works = ec.load_works(args.works)
    candidates = ea.parse_candidates(args.candidates or ea.DEFAULT_GRID)

    def load(candidate: ea.Candidate) -> EmbeddingTable:
        if not args.embeddings.exists():
            return EmbeddingTable(model=candidate.model, dims=candidate.dims, vectors={})
        return EmbeddingTable.load(args.embeddings, model=candidate.model, dims=candidate.dims)

    ledger_rows = Ledger(args.run / "ledger.jsonl").rows()
    missing = {c.label: ec.missing_rows(works, load(c)) for c in candidates}
    estimates = [ea.estimate(missing[c.label], c, ledger_rows=ledger_rows) for c in candidates]
    report: dict[str, Any] = {
        "splits": ["dev"],
        "candidates": [c.label for c in candidates],
        "estimate": estimates,
        "estimateTotal": {"tokens": sum(e["tokens"] for e in estimates), "usd": sum(e["usd"] for e in estimates)},
        "filled": [],
        "table": [],
    }
    if not args.dry_run:
        if _paid(args):
            ledger = _ledger(args)
            for c in candidates:
                if missing[c.label]:
                    embedder = ea.make_embedder(c)
                    report["filled"].append(
                        ea.embed_rows(missing[c.label], embedder, ledger=ledger, out=args.embeddings, stage=args.stage)
                    )
        tables = {c.label: load(c) for c in candidates}
        ready = [c for c in candidates if not ec.missing_rows(works, tables[c.label])]
        report["skipped"] = [c.label for c in candidates if c not in ready]
        report["table"] = ec.compare(
            works, ready, tables, nouns=ro.load_retriever(args.retriever), grid=_hybrid_grid(args)
        )
        print(ec.markdown(report["table"]))
        if objective is not None:
            meta = {k: objective[k] for k in ("path", "commit", "sha256")}
            report["selection"] = {**ec.select_rrf(report["table"], objective["objective"]), "objective": meta}
            report["objective"] = meta
    _write(args.out, report)
    total = report["estimateTotal"]
    print(f"빠진 글 견적 {total['tokens']}토큰 ${total['usd']:.4f} · 표 {len(report['table'])}줄 → {args.out}")
    return 0


def cmd_export_facts(args: argparse.Namespace) -> int:
    """방의 사실 행을 사실 오프라인 지표 입력(JSON 배열)으로. 읽기만."""
    from memory_eval.fact_export import export_facts
    from memory_eval.runtime import make_engine

    async def go() -> list[dict[str, Any]]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                return await export_facts(db, args.room)
        finally:
            await engine.dispose()

    rows = asyncio.run(go())
    _write(args.out, rows)
    print(f"사실 {len(rows)}행 → {args.out}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from memory_eval.judge import deterministic

    splits = _splits(args)
    from memory_eval.judge import ensure_unique_probe_rows

    plant_set = _plant_view(args, splits)
    source = _probe_rows(args.probes)
    ensure_unique_probe_rows(source)
    rows = []
    for row in source:
        if row["split"] not in splits or row["status"] not in ("accept", "count_wrong"):
            rows.append(
                {**{k: row[k] for k in ("stage", "arm", "checkpoint", "item", "split", "status")}, "scored": False}
            )
            continue
        replies = [t["reply"] for t in row["turns"]] if row["status"] == "accept" else []
        score = deterministic(plant_set.item(row["item"]), replies) if replies else {"hit": False}
        rows.append(
            {**{k: row[k] for k in ("stage", "arm", "checkpoint", "item", "split", "status")}, "scored": True, **score}
        )
    _write(args.out, rows)
    print(f"{len(rows)}줄 → {args.out}")
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    from memory_eval import judge as judge_mod

    categories: list[str] | None = args.categories
    if not args.controls and (args.controls_tag or args.control_sources):
        raise SystemExit("--controls-tag·--control-sources 는 대조군(--controls)에서만 쓴다")
    if args.controls and args.reuse_judged:
        raise SystemExit("--reuse-judged 는 본 판정에서만 쓴다")
    if args.controls and args.accept_failed_controls:
        raise SystemExit("--accept-failed-controls 는 본 판정에서만 쓴다")
    if args.accept_failed_controls and not (args.accept_reason or "").strip():
        raise SystemExit("--accept-failed-controls 는 --accept-reason 과 함께 준다(누가 왜 받아들였는가)")
    controls_path = args.run / "judge" / judge_mod.controls_filename(args.judge_model, categories)
    sources = args.control_sources or list(judge_mod.CONTROL_INPUTS)
    reused: dict[str, dict[str, Any]] = {}
    other_rule = 0
    boundary_inputs: list[dict[str, str]] = []
    # 판정 문구는 측정 데이터다 — 견적만 내는 드라이런도 같은 판정 입력을 세도록 먼저 읽는다.
    wording = judge_mod.load_wording(data_file(args, judge_mod.JUDGE_WORDING_FILE))
    if args.controls:
        # 대조군은 개발 절반 문항만 — 판정 문안을 대조군 오판으로 다듬으므로 시험 문항이 섞이면 안 된다.
        controls_path = (
            args.run / "judge" / judge_mod.controls_filename(args.judge_model, categories, args.controls_tag)
        )
        plant_set = _plant_view(args, {"dev"})
        items = judge_mod.controls(plant_set, wording) if "plants" in sources else []
        if "extra" in sources:
            for path in args.extra_controls:
                items += judge_mod.load_extra_controls(path, plant_set)
        if "boundary" in sources:
            # 견본 파일을 주지 않으면 측정 데이터 폴더의 기본 견본 파일 하나를 읽는다.
            boundary_paths = args.boundary_controls or [data_file(args, judge_mod.BOUNDARY_CONTROLS_FILE)]
            boundary_rows, boundary_inputs = judge_mod.load_boundary_control_files(plant_set, boundary_paths)
            items += boundary_rows
        if categories is not None:
            items = [i for i in items if i["kind"] in categories]
    else:
        splits = _splits(args)
        plant_set = _plant_view(args, splits)
        rows = [r for r in _probe_rows(args.probes) if r["split"] in splits and r["status"] == "accept"]
        items = [
            {
                "key": judge_mod.probe_key(r),
                "item": r["item"],
                "arm": r["arm"],
                "checkpoint": r["checkpoint"],
                "kind": kind,
                "replies": [t["reply"] for t in r["turns"]],
            }
            for r in rows
            if (kind := judge_mod.judge_kind(plant_set.item(r["item"]))) is not None
        ]
        if args.reuse_judged:
            # 대조군이 같은 판정 입력으로 이미 판정한 응답은 다시 부르지 않고 그 판정을 쓴다. 입력이 달라졌으면(판정 문안·문항
            # 칸·응답) 그 대조군 기록은 지금 판정자에 대한 것이 아니므로 거부한다.
            index = judge_mod.reuse_index(json.loads(args.reuse_judged.read_text(encoding="utf-8")), args.judge_model)
            for item in items:
                control = index.get(item["key"])
                if control is None:
                    continue
                prompt = judge_mod.judge_prompt(item["kind"], plant_set.item(item["item"]), item["replies"], wording)
                if control.get("promptSha256") != judge_mod.prompt_sha256(prompt):
                    raise SystemExit(f"판정 입력이 대조군 때와 다르다: {item['key']}")
                # 다른 표 규칙(규칙 칸이 없던 옛 기록 포함)의 판정을 다시 쓰면 한 결과 파일에 두 규칙의 판정이 섞인다 — 지금
                # 규칙으로 다시 판정한다. 결과를 보고 고르는 것이 아니라 규칙이 다른 줄 전부라 특정 판정에 기회를 더 주지 않는다.
                if control.get("voteRule") != judge_mod.VOTE_RULE:
                    other_rule += 1
                    continue
                reused[item["key"]] = control

    def gate() -> dict[str, Any] | None:
        return judge_mod.require_controls_passed(
            controls_path, accept_sha256=args.accept_failed_controls, accept_reason=args.accept_reason
        )

    if args.dry_run or not args.allow_paid:
        # 드라이런은 대조군 전에도 견적을 내야 하므로 관문을 보지 않는다. 받아들이기를 주었으면 그 sha 만은 미리 맞춰 본다.
        override = gate() if args.accept_failed_controls else None
        _print(
            {
                "calls": len(items) - len(reused),
                **({"reused": len(reused), "notReusedForVoteRule": other_rule} if args.reuse_judged else {}),
                **({"controlsOverride": override} if override else {}),
                "model": args.judge_model,
                # 줄마다 최대 표 수(안전 범주는 다섯)로 센 위쪽 견적 — 첫 두 표가 같으면 덜 쓴다.
                "estimateUsd": judge_mod.judge_estimate_usd_for(
                    [i["kind"] for i in items if i.get("key", "") not in reused], args.judge_model
                ),
                "controls": args.controls,
                **(
                    {"bySource": dict(Counter(i.get("source", "plants") for i in items)), "categories": categories}
                    if args.controls
                    else {}
                ),
            }
        )
        return 0
    override = None if args.controls else gate()
    from api.core.config import settings

    judge = judge_mod.HaikuJudge(
        settings.anthropic_direct_api_key, _ledger(args), stage="judge", model=args.judge_model
    )

    async def go() -> list[dict[str, Any]]:
        prompts = []
        for item in items:
            entry = judge_mod.control_entry(item, plant_set)
            replies = judge_mod.control_replies(item) if args.controls else item["replies"]
            prompts.append(judge_mod.judge_prompt(item["kind"], entry, replies, wording))
        fresh = [n for n, item in enumerate(items) if item.get("key", "") not in reused]
        # 다시 쓰지 않는 줄만 동시 판정에 넣고, 결과는 입력 순서로 제자리에 놓는다.
        judged_rows = await judge_mod.judge_all(
            judge, [(items[n]["kind"], prompts[n]) for n in fresh], concurrency=args.concurrency
        )
        by_index = dict(zip(fresh, judged_rows, strict=True))
        out = []
        for n, item in enumerate(items):
            sha = judge_mod.prompt_sha256(prompts[n])
            if n not in by_index:
                control = reused[item["key"]]
                # 다시 쓰는 줄은 지금 표 규칙의 기록뿐이고, 그 기록은 이유 칸을 함께 남긴다.
                out.append({**item, "judged": control["judged"], "votes": control["votes"],
                            "reasons": control["reasons"], "promptSha256": sha, "voteRule": control["voteRule"],
                            "reused": True})  # fmt: skip
                continue
            judged, votes, reasons = by_index[n]
            # 이유는 표 순서대로 한 문장씩(불능 표는 None) — 표 목록(`votes`)의 모양은 그대로 둔다.
            out.append({**item, "judged": judged, "votes": votes, "reasons": reasons, "promptSha256": sha,
                        "voteRule": judge_mod.VOTE_RULE})  # fmt: skip
        if override is not None:
            out = [{**row, "controlsOverride": override} for row in out]
        return out

    results = asyncio.run(go())
    if args.controls:
        _write(
            controls_path,
            {
                **judge_mod.controls_report(results),
                **({"categories": categories} if categories else {}),
                **({"boundaryInputs": boundary_inputs} if boundary_inputs else {}),
                "judgeModel": args.judge_model,
                "rows": results,
            },
        )
    else:
        _write(args.out, results)
    return 0


def cmd_label_pack(args: argparse.Namespace) -> int:
    """실제 프로브 응답의 독립 라벨링 입력을 파일로만 쓴다. 표준출력은 판정 종류별 줄 수뿐이다 — 응답 글을 화면에 내지 않는다."""
    from memory_eval.judge import (
        JUDGE_WORDING_FILE,
        ensure_unique_probe_rows,
        labeling_pack,
        load_wording,
        sample_label_pack,
    )

    source = _probe_rows(args.probes)
    ensure_unique_probe_rows(source)
    wording = load_wording(data_file(args, JUDGE_WORDING_FILE))
    rows = labeling_pack(_plant_view(args, {"dev"}), source, wording)
    if args.kinds is not None:
        rows = [r for r in rows if r["kind"] in args.kinds]
    pack: dict[str, Any] = {"rows": rows}
    if args.sample:
        if args.seed is None:
            raise SystemExit("--sample 은 --seed 와 함께 준다(표본을 다시 뽑아도 같아야 한다)")
        rows, meta = sample_label_pack(rows, dict(args.sample), seed=args.seed)
        pack = {"rows": rows, "sample": meta}
    _write(args.out, pack)
    _print(
        {
            "rows": len(rows),
            "byKind": dict(sorted(Counter(r["kind"] for r in rows).items())),
            "out": str(args.out),
            "sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(),
        }
    )
    return 0


def cmd_judge_controls_merge(args: argparse.Namespace) -> int:
    """작품마다 꼬리 이름으로 돌린 대조군 결과를 본 판정 관문이 읽는 한 파일로 합치고 관문을 다시 계산한다. 요약만 낸다."""
    from memory_eval import judge as judge_mod

    results = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in args.inputs]
    merged = judge_mod.merge_controls(results, args.judge_model)
    out = args.run / "judge" / judge_mod.controls_filename(args.judge_model)
    _write(out, merged)
    _print({k: merged[k] for k in ("passed", "gate", "observed")} | {"rows": len(merged["rows"]), "out": str(out)})
    return 0


def _require_ran(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    """집계 입구의 "실제로 돌았나" 단언(`memory_eval.ran_gate`). 집계할 행에 문턱이 걸린 갈래가 있으면 프로브 결과와 필터 재계산
    출력을 받아, 그 입력이 집계 행을 모두 덮는지 본 뒤 갈래별 문턱을 본다. 입력이 없거나, 덮지 못하거나, 문턱에 못 미치면 무엇을
    집계하기 전에 거부한다."""
    from memory_eval import ran_gate

    arms = {str(row["arm"]) for row in rows if "arm" in row}
    if not ran_gate.needs_inputs(arms):
        return
    if not args.ran_probes or not args.ran_recompute:
        gated = sorted(arms & set(ran_gate.GATED_ARMS))
        raise SystemExit(
            f"갈래 {gated} 를 집계하려면 --ran-probes(프로브 결과)와 --ran-recompute(filter-recompute 출력)를 준다"
        )
    recompute = [r for path in args.ran_recompute for r in json.loads(path.read_text(encoding="utf-8"))]
    probes = _probe_rows(args.ran_probes)
    ran_gate.require_covered(rows, probe_rows=probes, recompute_rows=recompute)
    ran_gate.require_ran(arms, probe_rows=probes, recompute_rows=recompute, facts_loaded_min=args.ran_facts_min)


def _ran_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--ran-probes", type=Path, nargs="+", help="실제로 돌았나 단언 — 프로브 결과(jsonl, 질의 임베딩 성공 비율)"
    )
    p.add_argument(
        "--ran-recompute", type=Path, nargs="+", help="실제로 돌았나 단언 — filter-recompute 출력(가림·재분류 합계)"
    )
    p.add_argument(
        "--ran-facts-min",
        type=int,
        help="실제로 돌았나 단언 — 사실 주입 갈래의 사실 섹션 실림 턴 수 하한(봉인 문서의 값, 기본값 없음: 그 갈래를 집계하면 필수)",
    )


def cmd_judge_summary(args: argparse.Namespace) -> int:
    """판정 결과의 종류별 합격률을 `unaddressed` 처리 방식 세 가지로 모두 낸다 — 봉인 문서가 하나를 고정하더라도 요약이 셋을
    함께 보여 결과를 본 뒤 유리한 방식을 고르는 일이 드러나게."""
    from memory_eval.judge import UNADDRESSED_POLICIES, summarize_judged

    rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    _require_ran(args, rows)
    _print({policy: summarize_judged(rows, unaddressed=policy) for policy in UNADDRESSED_POLICIES})
    return 0


def cmd_judge_form_summary(args: argparse.Namespace) -> int:
    """거짓 전제 판정 줄의 질문 꼴별 회피(`unaddressed`) 비율. 꼴은 심기 표의 질문 꼴 칸에서만 읽고(칸이 없으면 기본 꼴),
    표준출력에는 꼴별 개수와 비율만 나간다."""
    from memory_eval.b1.plants_tool import DEFAULT_ASK_FORM
    from memory_eval.judge import unaddressed_by_ask_form

    forms: dict[str, str] = {}
    for path in args.plants:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for entry in list(raw.get("plants", [])) + list(raw.get("abstains", [])):
            item = str(entry["id"])
            if item in forms:
                raise SystemExit(f"심기 표 둘에 같은 문항 id 가 있다: {item}")
            forms[item] = str(entry.get("askForm", DEFAULT_ASK_FORM))
    rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    _print({"falsePremiseByAskForm": unaddressed_by_ask_form(rows, forms)})
    return 0


def cmd_countdown(args: argparse.Namespace) -> int:
    """CP300 상영회 카운트다운(스탯 값·노트 본문 존재만 — 두 절반 합계, 문항 이름은 개발 절반만)."""
    from memory_eval import countdown

    bodies = countdown.note_bodies(args.seed_json, [countdown.DAY_NOTE, countdown.EVE_NOTE])
    rows = [r for r in _probe_rows(args.probes) if r["status"] == "accept" and int(r["checkpoint"]) == args.checkpoint]
    result = countdown.screening_countdown([countdown.probe_trace(r, bodies) for r in rows])
    _write(args.out, result)
    _print(result)
    return 0


def cmd_prototype_extract(args: argparse.Namespace) -> int:
    """스냅샷마다 장면 시제품 추출. 기본은 드라이런(창 수·입력 글자·견적). `--fake-llm` 은 렌더·결과 쓰기까지 돌리되 모델 대신
    빈 결과를 받는다(유료 호출 없이 경로 확인). 실제 호출은 `--allow-paid` 일 때만."""
    from memory_eval import prototype_extract as pe
    from memory_eval.runtime import judgment_sets, load_room, make_engine
    from memory_eval.wording_proto import excluded_user_names

    async def go() -> dict[str, Any]:
        # 활성 세트 캐시는 키가 (레인, 모델)뿐이라 지우지 않으면 직전 실행이 본 세트를 몇 분 동안 다시 받는다.
        await checkpoint.clear_room_redis_keys(args.room)
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                ctx = await load_room(db, args.room)
                windows = await pe.build_windows(db, args.room)
                sets = await judgment_sets(db, ctx)
        finally:
            await engine.dispose()
        prompt_set, base_sections = sets.episode
        instruction = args.instruction_file.read_text(encoding="utf-8")
        sections = pe.with_episode_instruction(list(base_sections), instruction)
        is_story = ctx.lane == "story"

        def render(window: pe.Window, titles: list[str]) -> str:
            return pe.build_prompt(
                prompt_set, sections, is_story_chat=is_story, previous_titles=titles, window=window, names=ctx.names
            )

        if args.dry_run or not (args.allow_paid or args.fake_llm):
            return {
                "windows": len(windows),
                "promptSetModel": prompt_set.model,
                "promptChars": [len(render(w, [])) for w in windows],
                "estimateUsd": len(windows) * pe.EXTRACT_CALL_ESTIMATE_USD,
            }
        if args.fake_llm == args.allow_paid:
            raise SystemExit("--fake-llm 과 --allow-paid 중 정확히 하나(또는 --dry-run)")
        if args.out is None:
            raise SystemExit("추출 결과는 --out 이 있어야 한다")
        if args.out.exists():
            raise SystemExit(f"결과 파일이 이미 있다(덮어쓰지 않는다): {args.out}")
        book = _ledger(args)
        if args.allow_paid:
            from api.core.config import settings

            api_key = settings.anthropic_direct_api_key

            async def call(prompt: str) -> pe.PrototypeResult:
                return await pe.call_haiku(api_key, prompt, book, stage=f"prototype-episode-{args.version}")
        else:

            async def call(prompt: str) -> pe.PrototypeResult:
                return pe.PrototypeResult(episodes=[])

        rows: list[dict[str, Any]] = []
        titles: list[str] = []
        for window in windows:
            result = await call(render(window, titles[-2:]))
            episodes = pe.episode_rows(window, result, version=args.version)
            rows.extend(episodes)
            titles = [e["title"] for e in episodes] or titles
        pe.write_json(args.out, rows)
        meta = {
            "version": args.version,
            "instructionSha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
            "renderedInstructionSha256": hashlib.sha256(
                pe.rendered_instruction(sections, is_story_chat=is_story, names=ctx.names).encode("utf-8")
            ).hexdigest(),
            "room": str(args.room),
            "lane": ctx.lane,
            "promptSetModel": prompt_set.model,
            "windows": len(windows),
            "userNames": excluded_user_names(ctx.names),
            "llm": "paid" if args.allow_paid else "fake",
        }
        _write(args.out.with_suffix(".meta.json"), meta)
        return {"windows": len(windows), "episodes": len(rows), "out": str(args.out), "llm": meta["llm"]}

    _print(asyncio.run(go()))
    return 0


def cmd_section_grid(args: argparse.Namespace) -> int:
    """사실 섹션 선택 방식 격자(`constant` 기준선 + `mixed` 상시 비율 × 관련 임계)의 섹션 적중. 개발 보기 전용 — 항목 질문과
    행 일치 여부만 쓰고 행 내용은 내지 않는다."""
    from memory_eval.facts import RENDER_MAX_CHARS, USER_PLACEHOLDER, alias_user, section_grid
    from memory_eval.objective import load_committed_objective, refuse_result_from_other_objective, section_grid_order
    from memory_eval.prototype_facts import load_fact_rows

    # 고르는 순서는 결과보다 먼저 커밋된 목적함수 파일에서만 — 결과를 본 뒤 순서를 고쳐 고르지 못하게.
    objective = load_committed_objective(args.objective)
    refuse_result_from_other_objective(args.out, objective)
    order = section_grid_order(objective["objective"])
    plant_set = _plant_view(args, {"dev"})
    rows = alias_user(load_fact_rows(args.facts), args.user_name)
    names = [n for n in (args.user_name, USER_PLACEHOLDER, *(args.names or [])) if n]
    report = section_grid(
        plant_set.all_items(),
        rows,
        checkpoints=_ints(args.checkpoints),
        ratios=[float(x) for x in args.ratios.split(",")],
        taus=[float(x) for x in args.taus.split(",")],
        names=names,
        max_chars=args.max_chars or RENDER_MAX_CHARS,
        order=order,
    )
    report["objective"] = {k: objective[k] for k in ("path", "commit", "sha256")}
    report["facts"] = str(args.facts)
    _write(args.out, report)
    _print(
        {
            "chosen": report["chosen"],
            "table": [
                {
                    "config": r["config"],
                    "primary": r["primaryHits"],
                    "secret": r["secretHits"],
                    "abstainMis": r["abstainMisinjected"],
                    "hits": {
                        c: f"{t['hit']}/{t['reachable']}/{t['n']}" for c, t in r["totals"].items() if c != "abstain"
                    },
                }
                for r in report["results"]
            ],
        }
    )
    return 0


def cmd_summary_sections(args: argparse.Namespace) -> int:
    """체크포인트 요약 본문의 칸별 글자 수·비율(특히 `[관계]` 칸)."""
    from memory_eval.summary_sections import section_report, summaries_from_file

    rows = [
        {"source": name, **section_report(text)} for path in args.inputs for name, text in summaries_from_file(path)
    ]
    _write(args.out, rows)
    _print([{"source": r["source"], "total": r["total"], "relationRatio": r["relationRatio"]} for r in rows])
    return 0


def cmd_s8(args: argparse.Namespace) -> int:
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.verdict import s8_verdict

    require_seal(
        {"test"}, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha, test_drop=getattr(args, "test_drop", None)
    )
    plant_set = _plant_view(args, {"dev", "test"})
    scores = [r for path in args.scores for r in json.loads(path.read_text(encoding="utf-8"))]
    ensure_unique_probe_rows(scores)
    judge_rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    offline = json.loads(args.offline.read_text(encoding="utf-8"))["rows"]
    points = [
        json.loads(line) for path in args.trajectory for line in path.read_text(encoding="utf-8").splitlines() if line
    ]
    result = s8_verdict(
        plant_set, scores, judge_rows=judge_rows, offline_rows=offline,
        trajectory_points=points or None, recall_section_max=args.recall_section_max,
    )  # fmt: skip
    _write(args.out, result)
    _print({k: result[k].get("pass") for k in ("1", "2", "3", "4", "5", "6", "7")} | {"allPass": result["allPass"]})
    return 0


def cmd_v3_verdict(args: argparse.Namespace) -> int:
    """2차 런 최종 짝 비교, 결과 칸 1~7(칸 1·4 는 시험 절반, 칸 2·3 은 전체 문항 — 봉인 확인 뒤). 결과는 `verdict.json`."""
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.verdict_v3 import v3_verdict

    require_seal(
        {"test"}, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha, test_drop=getattr(args, "test_drop", None)
    )
    plant_set = _plant_view(args, {"dev", "test"})
    scores = [r for path in args.scores for r in json.loads(path.read_text(encoding="utf-8"))]
    ensure_unique_probe_rows(scores)
    judge_rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    controls_path = args.controls or args.run / "judge" / "controls.json"
    control_rows = json.loads(controls_path.read_text(encoding="utf-8"))["rows"] if controls_path.exists() else None
    points = [
        json.loads(line) for path in args.trajectory for line in path.read_text(encoding="utf-8").splitlines() if line
    ]
    result = v3_verdict(
        plant_set, scores, judge_rows=judge_rows, control_rows=control_rows, trajectory_points=points or None,
        section_max=args.section_max, unaddressed=args.unaddressed,
    )  # fmt: skip
    _write(args.out or args.run / "verdict.json", result)
    keys = ("1", "2", "3", "4", "5", "6", "7")
    _print(
        {k: result[k].get("status") for k in keys}
        | {"primaryByPolicy": {p: v["status"] for p, v in result["primaryByPolicy"].items()}}
        | {"allPass": result["allPass"], "status": result["status"]}
    )
    return 0


def v4_controls_input(
    path: Path, *, accept_sha256: str | None, accept_reason: str | None
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """판정자 대조군 기록 줄과, 미달 기록을 사용자가 받아들인 결정(그 파일의 sha256 이 준 값과 같고 실제로 미달일 때만 — 본 판정
    `judge` 와 같은 확인). 기록이 없으면 (None, None) — 판정은 대조군 칸을 `halt` 로 낸다."""
    from memory_eval import judge as judge_mod

    if accept_sha256 is not None and not (accept_reason or "").strip():
        raise SystemExit("--accept-failed-controls 는 --accept-reason 과 함께 준다(누가 왜 받아들였는가)")
    if not path.exists():
        if accept_sha256 is not None:
            raise SystemExit(f"받아들이기로 한 대조군 기록이 없다: {path}")
        return None, None
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    if accept_sha256 is None:
        return rows, None
    return rows, judge_mod.require_controls_passed(path, accept_sha256=accept_sha256, accept_reason=accept_reason)


def v4_effect_floors_input(path: Path) -> dict[str, Any]:
    """분할 시드 파일에서 효과마다의 합계 하한을 읽고, 그 파일의 sha256 을 함께 돌려준다 — 결과에 남겨 보류 기준이 결과 전에
    커밋한 시드 파일의 값이었는지 맞춰 볼 수 있게 한다."""
    from memory_eval.verdict_v4 import effect_floors

    floors = effect_floors(json.loads(path.read_text(encoding="utf-8")))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "floors": floors}


def cmd_v4_verdict(args: argparse.Namespace) -> int:
    """묶음 1 판정 — 안전 쌍·효과 Holm·비열등·캐릭터 표·켜기 권고(시험 절반 — 봉인 확인 뒤). 대본마다 심기 표와 분할 폴더를 짝으로
    주고, 궤적은 대본마다 `trajectory-replay` 출력 폴더를 준다. 결과는 `<원자료>/b1/measure/verdict.json`."""
    return _v4_judge(args, split="test")


def cmd_v4_preview(args: argparse.Namespace) -> int:
    """개발 절반 미리보기 — 시험 판정과 같은 함수·같은 규칙을 개발 문항에 돌린다(봉인 없이). 개발 미리보기가 돌리지 않는 갈래가 든
    쌍·효과는 개발 범위 밖으로 표시한다. 결과는 `<원자료>/b1/preview/verdict-dev.json`, 결과 머리에 `split: dev`."""
    return _v4_judge(args, split="dev")


def cmd_v4_power_table(args: argparse.Namespace) -> int:
    """봉인 전에 실제 시험 n 으로 "통과 최소 불일치" 표를 낸다 — 판정 규칙과 같은 상수(문턱)를 읽는다. 유료 호출·파일 읽기 없음.
    `--facts-inject` 면 효과 문턱을 사실 주입 재측정의 효과 표(갈래 쌍 하나)로 낸다."""
    from memory_eval import facts_inject
    from memory_eval.verdict_v4 import power_table

    sizes: dict[str, int] = {}
    for item in args.n:
        key, _, value = item.partition("=")
        if not value.isdigit():
            raise SystemExit(f"표본은 '키=정수' 꼴이다: {item!r}")
        sizes[key] = int(value)
    table = facts_inject.power_table if args.facts_inject else power_table
    _print(table(sizes, max_c=args.max_c))
    return 0


def cmd_facts_inject_summary(args: argparse.Namespace) -> int:
    """사실 주입 재측정 집계 — 현 운영 갈래 → 사실 주입 갈래의 효과(판정 불능 상한·판정자 대조군까지 묶음 판정과 같은 유효성
    장치), 사실 섹션 실림 턴 수, 관찰 칸 둘(값만). 시험 절반은 봉인 확인 뒤에만 열고 결과에 봉인 판·sha 를 남긴다. 집계 전에
    "실제로 돌았나" 단언(사실 섹션 실림 턴 수 문턱 포함)과 두 갈래 질의 임베딩 상한이 같았는지를 본다. 결과는 `--out`."""
    from memory_eval import facts_inject, ran_gate
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.seal import SEALED_EDITION

    split = args.split
    scores = [r for path in args.scores for r in json.loads(path.read_text(encoding="utf-8"))]
    judge_rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    _require_ran(args, scores + judge_rows)
    probes = _probe_rows(args.ran_probes or [])
    timeouts = facts_inject.require_same_embed_timeout(probes)
    if split == "test":
        require_seal({"test"}, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha, test_drop=args.test_drop)

    def view(pair: list[str]) -> plants_mod.PlantSet:
        return holdout.load_view(
            Path(pair[0]), Path(pair[1]), {split}, preregistration=args.run / PREREGISTRATION_FILE,
            seal_sha=args.seal_sha, test_drop=args.test_drop,
        )  # fmt: skip

    story = [view(pair) for pair in args.story]
    character = [view(pair) for pair in args.character or []]
    ensure_unique_probe_rows(scores)
    control_rows, override = v4_controls_input(
        args.controls or args.run / "judge" / "controls.json",
        accept_sha256=args.accept_failed_controls,
        accept_reason=args.accept_reason,
    )
    seeds = json.loads(args.split_seeds.read_text(encoding="utf-8")) if args.split_seeds else None
    floors = facts_inject.effect_floors(seeds) if seeds is not None else None
    recompute = [r for path in args.ran_recompute or [] for r in json.loads(path.read_text(encoding="utf-8"))]
    result = facts_inject.verdict(
        story, character, scores, judge_rows, control_rows=control_rows, controls_override=override, floors=floors,
        split=split,
    )  # fmt: skip
    items = [e for s in [*story, *character] for e in s.all_items() if e.get("split") == split]
    result |= {
        "seal": {"edition": SEALED_EDITION, "sha256": args.seal_sha} if split == "test" else None,
        "embedRecallTimeoutMs": timeouts,
        "factsLoaded": ran_gate.facts_loaded_turns(probes),
        "observations": facts_inject.observations(items, recompute),
    }
    _write(args.out, result)
    _print({facts_inject.EFFECT: result["effects"][facts_inject.EFFECT]["status"], "status": result["status"]}
           | {"invalid": result["invalid"], "controls": result["controls"]["status"]}
           | {"factsLoaded": result["factsLoaded"], "observations": result["observations"], "out": str(args.out)})  # fmt: skip
    return 0


def _v4_judge(args: argparse.Namespace, *, split: str) -> int:
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.verdict_v4 import v4_verdict

    scores = [r for path in args.scores for r in json.loads(path.read_text(encoding="utf-8"))]
    judge_rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    _require_ran(args, scores + judge_rows)
    seal_sha = getattr(args, "seal_sha", None)
    test_drop = getattr(args, "test_drop", None)
    if split == "test":
        require_seal({"test"}, args.run / PREREGISTRATION_FILE, seal_sha=seal_sha, test_drop=test_drop)

    def view(pair: list[str]) -> plants_mod.PlantSet:
        plants_path, split_dir = Path(pair[0]), Path(pair[1])
        return holdout.load_view(
            plants_path,
            split_dir,
            {split},
            preregistration=args.run / PREREGISTRATION_FILE,
            seal_sha=seal_sha,
            test_drop=test_drop,
        )

    story = [view(pair) for pair in args.story]
    character = [view(pair) for pair in args.character]
    ensure_unique_probe_rows(scores)
    controls_path = args.controls or args.run / "judge" / "controls.json"
    control_rows, override = v4_controls_input(
        controls_path, accept_sha256=args.accept_failed_controls, accept_reason=args.accept_reason
    )
    trajectories: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for name, lane, folder in args.trajectory_dir:
        if lane not in ("story", "character"):
            raise SystemExit(f"궤적 레인은 story·character 중 하나다: {lane}")
        points = [
            json.loads(line)
            for path in sorted(Path(folder).glob("trajectory-*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        trajectories[name] = (lane, points)
    section_max = {}
    for item in args.section_max:
        pair, _, value = item.partition("=")
        section_max[pair] = int(value)
    floors = v4_effect_floors_input(args.split_seeds) if args.split_seeds else None
    result = v4_verdict(
        story, character, scores, judge_rows=judge_rows, control_rows=control_rows, trajectories=trajectories,
        section_max=section_max, controls_override=override, effect_floors=floors["floors"] if floors else None,
        with_a0m=args.with_a0m, split=split,
    )  # fmt: skip
    if floors:
        result["effectFloors"] = floors
    default_out = args.run / "b1" / ("measure/verdict.json" if split == "test" else "preview/verdict-dev.json")
    out = args.out or default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, result)
    _print(
        {pair: {lane: t["status"] for lane, t in lanes.items()} for pair, lanes in result["safety"].items()}
        | {k: result["effects"][k]["status"] for k in ("E1", "E2", "E3")}
        | {"nonInferiority": result["nonInferiority"]["status"], "controls": result["controls"]["status"]}
        | {"invalid": result["invalid"], "underpowered": result["underpowered"], "status": result["status"]}
        | {"recommendations": {k: v["status"] for k, v in result["recommendations"]["steps"].items()}}
        | {"stage3Pass": result["recommendations"]["stage3Pass"]["status"]}
        | {"split": result["split"], "outOfScope": result["outOfScope"]}
    )
    return 0


def cmd_judge_agreement(args: argparse.Namespace) -> int:
    """덤프의 판정 줄을 판정 모델마다 같은 입력으로 반복해 다시 보내고 자기 반복·교차 일치율을 낸다. `--dry-run` 은 호출 수·견적만,
    `--allow-paid` 는 실제 호출(원장 상한·멈춤 선·묶음 필수), `--fake-llm` 은 가짜 판정기로 절차만(원장도 따로), 셋 다 없으면 이미
    남은 호출 결과로 집계만 다시 낸다."""
    from memory_eval import judge_agreement as ja

    if args.fake_llm and args.allow_paid:
        raise SystemExit("--fake-llm 과 --allow-paid 는 함께 쓰지 않는다")
    labels = [label.strip() for label in args.models.split(",") if label.strip()]
    if args.candidate not in labels:
        raise SystemExit(f"후보 판정 모델 {args.candidate} 이 --models({args.models})에 없다")
    if "gemini" in labels and not args.gemini_model:
        raise SystemExit("Gemini 판정 모델 id(--gemini-model)를 명시해야 한다 — 전환 전 운영 판정 모델과 같아야 한다")
    call_sites = set(args.call_sites.split(",")) if args.call_sites else None
    lines = ja.load_lines(args.dumps, call_sites=call_sites)
    if args.limit is not None:
        lines = lines[: args.limit]
    if args.controls is not None:
        lines = lines + ja.control_lines(lines, json.loads(args.controls.read_text(encoding="utf-8")))
    rates = ja.parse_tokens_per_char(args.tokens_per_char)
    out_dir: Path = args.out_dir or args.run / "judge-agreement"
    calls_path = out_dir / ("fake-calls.jsonl" if args.fake_llm else "calls.jsonl")

    from api.core.config import settings

    if args.fake_llm:
        ids = {"gemini": args.gemini_model or "", "haiku": settings.anthropic_haiku_model_id}
        models = [
            ja.JudgeModel(label=label, model_id=ids[label], client=ja.FakeJudgeLLM(ids[label])) for label in labels
        ]
    elif args.allow_paid and not args.dry_run:
        book = _ledger(args)
        models = ja.real_models(labels, gemini_model=args.gemini_model or "")
    else:
        # 견적·집계는 클라이언트를 만들지 않는다(키가 없어도 돈다).
        ids = {"gemini": args.gemini_model or "", "haiku": settings.anthropic_haiku_model_id}
        unknown = [label for label in labels if label not in ids]
        if unknown:
            raise SystemExit(f"모르는 판정 모델: {unknown} (gemini·haiku)")
        models = [
            ja.JudgeModel(label=label, model_id=ids[label], client=ja.FakeJudgeLLM(ids[label])) for label in labels
        ]

    candidate_id = next(m.model_id for m in models if m.label == args.candidate)
    estimate = ja.estimate(lines, models, args.reps, rates=rates, output_tokens=args.output_tokens)
    if args.dry_run:
        estimate["ledgerSpentUsd"] = _ledger(args).total_usd()
        _print(estimate)
        return 0
    if args.fake_llm:
        made = asyncio.run(
            ja.run_calls(
                lines,
                models,
                args.reps,
                ledger=Ledger(out_dir / "fake-ledger.jsonl"),
                calls_path=calls_path,
                stage=args.label,
                rates=rates,
                output_tokens=args.output_tokens,
                order_seed=args.order_seed,
            )
        )
    elif args.allow_paid:

        async def paid_run() -> int:
            with ja.without_usage_store():
                return await ja.run_calls(
                    lines,
                    models,
                    args.reps,
                    ledger=book,
                    calls_path=calls_path,
                    stage=args.label,
                    rates=rates,
                    output_tokens=args.output_tokens,
                    order_seed=args.order_seed,
                )

        made = asyncio.run(paid_run())
    else:
        made = 0
    calls = ja.read_calls(calls_path)
    summary = ja.summarize(
        lines,
        calls,
        candidate=args.candidate,
        baseline=args.baseline,
        min_self=args.min_self,
        min_fired_lines=args.min_fired_lines,
        strata=ja.load_strata(args.strata),
        countdown_stat=args.countdown_stat,
        max_quiet_decrement=args.max_quiet_decrement,
        min_decrement=args.min_decrement,
        min_control_reaction=args.min_control_reaction,
    )
    meta = {
        "dumps": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.dumps},
        "models": {m.label: m.model_id for m in models},
        # 덤프를 만든 서버의 판정 모델. 후보 모델과 다르면 덤프 프롬프트는 그 모델의 판정 문안으로 조립됐다 — 두 문안이 바이트까지
        # 같을 때만 이 재판정이 운영 후보 판정과 같은 입력이다.
        "dumpModels": ja.dump_models(lines),
        "dumpJudgedByCandidateModel": all(line.dump_model == candidate_id for line in lines if line.control is None),
        "anthropicStructuredEffort": settings.anthropic_structured_effort,
        "reps": args.reps,
        "orderSeed": args.order_seed,
        "limit": args.limit,
        "callsThisRun": made,
        "fake": bool(args.fake_llm),
    }
    report = {
        "meta": meta,
        "estimate": estimate,
        "measuredTokensPerChar": ja.measured_tokens_per_char(calls),
        "summary": summary,
    }
    _write(out_dir / ("fake-summary.json" if args.fake_llm else "summary.json"), report)
    _write(out_dir / ("fake-lines.json" if args.fake_llm else "lines.json"), ja.line_table(lines, calls))
    _print({"meta": meta, "measuredTokensPerChar": report["measuredTokensPerChar"], "summary": summary})
    return 0


def cmd_judge_majority(args: argparse.Namespace) -> int:
    """이미 남은 판정 반복 기록으로 k 표 다수결 판정의 일치율을 단일 판정 일치율과 함께 어림한다(호출 없음)."""
    from memory_eval import judge_agreement as ja

    deltas = None if args.deltas is None else json.loads(args.deltas.read_text(encoding="utf-8"))
    report = ja.majority_agreement(ja.read_calls(args.calls), model=args.model, k=args.k, vote=args.vote, deltas=deltas)
    report["calls"] = {str(args.calls): hashlib.sha256(args.calls.read_bytes()).hexdigest()}
    _write(args.out, report)
    _print(report)
    return 0


def cmd_judge_reason(args: argparse.Namespace) -> int:
    """스탯 판정 줄을 운영 판정기(Haiku 직결) 그대로 이유 칸 없는 판·있는 판으로 반복 재판정해 두 판의 자기 반복·판 사이 일치율을
    낸다. `--dry-run` 은 줄 수·호출 수·견적만, `--allow-paid` 는 실제 호출(원장 상한·멈춤 선·묶음 필수, 전체 견적이 묶음 여유를
    넘으면 첫 호출 전에 멈춤), `--fake-llm` 은 가짜 판정기로 절차만(결과·원장 파일도 따로), 셋 다 없으면 이미 남은 결과로 집계만."""
    from memory_eval import judge_agreement as ja
    from memory_eval import judge_reason as jr
    from memory_eval.ledger import BudgetExceededError

    from api.core.config import settings

    if args.fake_llm and args.allow_paid:
        raise SystemExit("--fake-llm 과 --allow-paid 는 함께 쓰지 않는다")
    if args.dev_dumps and args.dev_sample is None:
        raise SystemExit("--dev-dumps 는 표본 크기 --dev-sample 을 함께 줘야 한다(개발 덤프 줄 전부를 기본으로 쓰지 않는다)")
    if (args.dev_dumps or args.baseline_sample is not None) and args.seed is None:
        raise SystemExit("표본을 고르는 실행은 씨앗 --seed 를 명시해야 한다(결과를 보기 전에 고른 표본이 다시 나와야 한다)")
    baseline = jr.load_stat_lines(args.baseline_dumps or [])
    if args.baseline_sample is not None:
        baseline = jr.balanced_sample(baseline, args.baseline_sample, seed=args.seed)
    dev = jr.load_stat_lines(args.dev_dumps or [], prefix=jr.DEV_GROUP)
    if args.dev_dumps:
        dev = jr.balanced_sample(dev, args.dev_sample, seed=args.seed)
    lines = baseline + dev
    if not lines:
        raise SystemExit("스탯 판정 줄이 없다 — --baseline-dumps 나 --dev-dumps 를 준다")
    groups = {line.line_id: jr.BASELINE_GROUP for line in baseline} | {line.line_id: jr.DEV_GROUP for line in dev}
    if args.controls is not None:
        lines = lines + ja.control_lines(lines, json.loads(args.controls.read_text(encoding="utf-8")))

    model_id = settings.anthropic_haiku_model_id
    out_dir: Path = args.out_dir or args.run / "s5" / "judge-reason"
    prefix = "fake-" if args.fake_llm else ""
    calls_path = out_dir / f"{prefix}calls.jsonl"
    # 견적은 아직 결과가 없는 호출만 — 끊긴 실행을 이어 돌릴 때 이미 원장에 든 호출을 다시 얹지 않게(전송 오류 줄은 다시 부른다).
    done = {key for key, row in ja.latest_calls(ja.read_calls(calls_path)).items() if row["status"] != "call_error"}
    estimate = jr.estimate(
        lines,
        args.reps,
        model_id=model_id,
        tokens_per_char=args.tokens_per_char,
        plain_output_tokens=args.output_tokens,
        reason_output_tokens=args.reason_output_tokens,
        done=done,
    )
    estimate["lines"] = jr.group_counts(groups, lines)
    estimate["controls"] = sum(1 for line in lines if line.control is not None)
    if args.dry_run:
        book = _ledger(args)
        estimate["ledgerSpentUsd"] = book.total_usd()
        if args.cap_usd is not None:
            estimate["bundleSpentUsd"] = book.bundle_usd()
            estimate["capUsd"] = args.cap_usd
            estimate["headroomUsd"] = args.cap_usd - book.bundle_usd() - estimate["totalUsd"]
        _print(estimate)
        return 0

    # 호출 견적의 출력 자리값은 두 판 중 큰 쪽 — 호출마다 원장 여유를 볼 때 한 호출을 작게 잡아 상한을 넘지 않게.
    per_call_output = max(args.output_tokens, args.reason_output_tokens)
    made = 0
    if args.allow_paid:
        book = _ledger(args)
        limit = args.cap_usd if args.halt_usd is None else min(args.cap_usd, args.halt_usd)
        if book.bundle_usd() + estimate["totalUsd"] > limit:
            raise BudgetExceededError(
                f"묶음 {args.bundle} 누적 ${book.bundle_usd():.4f} + 이번 전체 견적 ${estimate['totalUsd']:.4f} 가 "
                f"상한·멈춤 선 ${limit:.4f} 를 넘는다 — 표본을 줄이거나 승인을 다시 받는다"
            )
        real = ja.real_models(["haiku"], gemini_model="")[0]
        models = jr.variant_models(real.client, real.model_id, real.overrides)

        async def paid_run() -> int:
            with ja.without_usage_store():
                return await ja.run_calls(
                    lines,
                    models,
                    args.reps,
                    ledger=book,
                    calls_path=calls_path,
                    stage=args.label,
                    rates={"*": args.tokens_per_char},
                    output_tokens=per_call_output,
                    order_seed=args.order_seed,
                )

        made = asyncio.run(paid_run())
    elif args.fake_llm:

        def nothing_fired(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
            if schema == jr.ReasonedStatRuleJudgmentResult.__name__:
                return {"fired_rule_ids": [], "reason": ""}
            return {"fired_rule_ids": []}

        made = asyncio.run(
            ja.run_calls(
                lines,
                jr.variant_models(ja.FakeJudgeLLM(model_id, nothing_fired), model_id),
                args.reps,
                ledger=Ledger(out_dir / "fake-ledger.jsonl"),
                calls_path=calls_path,
                stage=args.label,
                rates={"*": args.tokens_per_char},
                output_tokens=per_call_output,
                order_seed=args.order_seed,
            )
        )

    calls = ja.read_calls(calls_path)
    meta = {
        "dumps": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [*(args.baseline_dumps or []), *(args.dev_dumps or [])]
        },
        "modelId": model_id,
        "anthropicStructuredEffort": settings.anthropic_structured_effort,
        "dumpModels": ja.dump_models(lines),
        "dumpJudgedByJudgeModel": all(line.dump_model == model_id for line in lines if line.control is None),
        "lines": jr.group_counts(groups, lines),
        "sampleSeed": args.seed,
        "orderSeed": args.order_seed,
        "baselineSample": args.baseline_sample,
        "devSample": args.dev_sample,
        "reps": args.reps,
        "callsThisRun": made,
        "fake": bool(args.fake_llm),
    }
    report = {
        "meta": meta,
        "estimate": estimate,
        "measuredTokensPerChar": ja.measured_tokens_per_char(calls),
        "summary": jr.summarize(lines, groups, calls),
    }
    _write(out_dir / f"{prefix}summary.json", report)
    _write(
        out_dir / f"{prefix}lines.json",
        [{**row, "group": groups.get(row["lineId"])} for row in ja.line_table(lines, calls)],
    )
    tables_path = out_dir / f"{prefix}tables.md"  # cite-ok: 도구가 쓰는 결과 파일 이름
    tables_path.write_text(jr.render_tables(report), encoding="utf-8")
    _print({"meta": meta, "measuredTokensPerChar": report["measuredTokensPerChar"], "summary": report["summary"]})
    return 0


def cmd_judge_strata(args: argparse.Namespace) -> int:
    """드라이버 로그(층 태그를 `--tag` 로 준 턴)에서 judge-agreement `--strata` 표를 만든다."""
    from memory_eval import judge_sample as js

    strata = js.strata_from_log(args.log, js.load_script(args.script or data_file(args, js.STORY_SCRIPT_FILE)))
    _write(args.out, strata)
    _print({"out": str(args.out), "turns": len(strata)})
    return 0


def cmd_judge_branch(args: argparse.Namespace) -> int:
    """엔딩 갈래 — 얼린 엔딩 층 템플릿에서 갈래마다 작업 DB 를 다시 만들고 판정 차례 턴 하나를 친다. `--dry-run` 은 갈래 목록만,
    `--allow-paid` 가 없으면 서버가 Anthropic 키 없이 떠 생성이 실패한다. 결과는 `<원자료>/branches/results.jsonl` 에 이어 쓴다."""
    from memory_eval import judge_sample as js
    from memory_eval import server

    script = js.load_script(args.script or data_file(args, js.STORY_SCRIPT_FILE))
    wanted = set(args.branches.split(",")) if args.branches else None
    branches = [b for b in script.get("branches", []) if wanted is None or b["id"] in wanted]
    url = _db_url(writes=True)
    checkpoint.ensure_eval_db_name(checkpoint.database_name(url))
    plan = [
        {
            "branch": b["id"],
            "stratum": b["stratum"],
            "turn": js.branch_turn(script),
            "dump": str(js.branch_dump(args.run, b["id"])),
        }
        for b in branches
    ]
    if args.dry_run:
        _print({"template": checkpoint.template_db_name(args.checkpoint, args.label), "plan": plan})
        return 0
    overrides: dict[str, str] = {}
    if args.server_env:
        for line in args.server_env.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                key, _, value = line.partition("=")
                overrides[key.strip()] = value.strip()
    if server.port_in_use(args.port):
        raise SystemExit(f"포트 {args.port} 에 이미 서버가 있다")
    out = args.run / "branches" / "results.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    for branch in branches:
        result = js.run_branch(
            branch,
            database_url=url,
            run_dir=args.run,
            room_id=args.room,
            checkpoint_no=args.checkpoint,
            label=args.label,
            port=args.port,
            cred_file=args.cred_file,
            cookie_file=args.cookie_file,
            server_overrides=overrides,
            allow_paid=args.allow_paid,
        )
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        print(f"{result['branch']} {result['stratum']}: exit {result['exit']} saved {result['saved']}")
    return 0


def cmd_judge_controls(args: argparse.Namespace) -> int:
    """망친 입력 대조군 명세를 정한 규칙·정한 문장(`judge_controls.json`)으로 만든다. 판정 결과는 읽지 않는다 — 덤프 프롬프트,
    대본, 확정 층 표만. 명세 sha256 을 출력한다(재판정 전에 사전 등록 개정 이력에 적는다)."""
    from memory_eval import judge_agreement as ja
    from memory_eval import judge_sample as js

    built = js.build_controls(
        ja.load_lines(args.dumps),
        story=js.load_script(data_file(args, js.STORY_SCRIPT_FILE)),
        character=js.load_script(data_file(args, js.CHARACTER_SCRIPT_FILE)),
        strata=json.loads(args.strata.read_text(encoding="utf-8")),
        config=js.load_controls_config(data_file(args, js.CONTROLS_CONFIG_FILE)),
    )
    _write(args.out, built["controls"])
    _print(
        {
            "out": str(args.out),
            "controls": len(built["controls"]),
            "shortfall": built["shortfall"],
            "sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(),
        }
    )
    return 0


def cmd_judge_sample_estimate(args: argparse.Namespace) -> int:
    """두 대본의 턴 수로 표본 생성(Opus 직결) 원가 견적. 토큰 값은 실측(첫 몇 턴의 원장)으로 바꾼다."""
    from memory_eval import judge_sample as js

    scripts = {
        path.name: js.load_script(path)
        for path in (data_file(args, js.STORY_SCRIPT_FILE), data_file(args, js.CHARACTER_SCRIPT_FILE))
    }
    rooms = {
        name: js.generation_estimate(
            turns=len(script["turns"]),
            prompt_tokens=args.prompt_tokens,
            new_tokens_per_turn=args.new_tokens_per_turn,
            output_tokens=args.output_tokens,
            # 엔딩 갈래는 템플릿에서 복원해 한 턴씩 친다 — 앞 턴 캐시가 없다.
            cold_turns=len(script.get("branches", [])),
        )
        for name, script in scripts.items()
    }
    _print({"rooms": rooms, "totalUsd": sum(r["usd"] for r in rooms.values())})
    return 0


_WORDING_CALL_SITES = {"summary": "chat_memory_summary", "facts": "chat_memory_fact"}


# 요약 슬롯 견적에 더하는 이름 목록 몫(글자) — 방 이름이 많아도 이 안이다.
_WORDING_NAMES_ALLOWANCE = 200


def _wording_checkpoints(args: argparse.Namespace, plant_set: plants_mod.PlantSet) -> dict[str, int]:
    """그 체크포인트까지의 체크포인트별 스냅샷 수(얼릴 때 남긴 지문에서). 고른 체크포인트의 지문은 꼭 있어야 한다."""
    out: dict[str, int] = {}
    for cp in plants_mod.checkpoints(plant_set):
        path = checkpoint.fingerprint_path(args.dumps_dir, cp, args.label)
        if cp <= args.checkpoint and path.exists():
            out[str(cp)] = int(json.loads(path.read_text(encoding="utf-8"))["snapshotCount"])
    if str(args.checkpoint) not in out:
        raise SystemExit(f"{args.label} cp{args.checkpoint} 지문이 없다: {args.dumps_dir}")
    return out


def _wording_run(args: argparse.Namespace, kind: str) -> int:
    from memory_eval import insert, wording_proto as wp
    from memory_eval.plants import PlantSet

    candidate: wp.SummaryCandidate | wp.FactCandidate
    if kind == "summary":
        candidate = wp.load_summary_candidate(args.candidate)
        extra_chars = len(candidate.slot) + max(len(candidate.no_names), _WORDING_NAMES_ALLOWANCE)
    else:
        candidate = wp.load_fact_candidate(args.candidate)
        # 지금 지시문을 빼지 않고 후보 전체를 더한다 — 넉넉한 쪽으로 틀린다.
        extra_chars = len(candidate.instruction)
    plant_set: PlantSet = _plant_view(args)
    lane = insert.plant_lane(plant_set)
    if lane is None:
        raise SystemExit("심기 표에 레인(lane) 칸이 없다 — 묶음 1 심기 표만 받는다")
    snapshots = _wording_checkpoints(args, plant_set)
    template = checkpoint.template_db_name(args.checkpoint, args.label)
    out_dir = args.out_dir or args.run / "wording"
    out = out_dir / f"{kind}-{candidate.version}-{args.label}-cp{args.checkpoint}.jsonl"
    estimate: dict[str, Any] | None = None
    if args.usage_ledger is not None:
        rows = Ledger(args.usage_ledger).rows()
        usage = wp.ledger_usage(rows, stage=args.label, call_site=_WORDING_CALL_SITES[kind])
        estimate = wp.dry_run_estimate(
            calls=snapshots[str(args.checkpoint)], usage=usage, extra_input_chars=extra_chars, margin=args.margin
        )
    if args.dry_run:
        _print(
            {
                "kind": kind,
                "version": candidate.version,
                "template": template,
                "checkpointSnapshots": snapshots,
                "out": str(out),
                "estimate": estimate,
                "ledgerBundleSpentUsd": _ledger(args).bundle_usd(),
            }
        )
        return 0
    if args.fake_llm == args.allow_paid:
        raise SystemExit("--fake-llm 과 --allow-paid 중 정확히 하나(또는 --dry-run)")
    if args.room is None:
        raise SystemExit("--room 이 필요하다")
    url = _db_url(writes=True)
    wp.require_work_db(checkpoint.database_name(url), template)
    from api.llm.client import LLMClient

    llm: LLMClient
    before_call = None
    if args.fake_llm:
        from memory_eval.fake_llm import FakeMemoryLLM

        llm = FakeMemoryLLM()
    else:
        if estimate is None:
            raise SystemExit("유료 실행은 --usage-ledger 로 호출당 견적을 받아 상한을 호출 전에 본다")
        from api.llm.dependencies import get_llm_client

        book = _ledger(args)
        per_call = float(estimate["perCallUsd"])
        llm = insert.LedgerTap(
            get_llm_client(),
            book,
            stage=f"wording-{kind}-{candidate.version}-{args.label}",
            per_call_estimate_usd=per_call,
        )

        def before_call() -> None:
            book.check_headroom(per_call)

    header = {
        "kind": "header",
        "run": kind,
        "version": candidate.version,
        "candidateSha256": candidate.sha256,
        "label": args.label,
        "checkpoint": args.checkpoint,
        "room": str(args.room),
        "lane": lane,
        "checkpointSnapshots": snapshots,
        "llm": "fake" if args.fake_llm else "paid",
    }

    async def run() -> dict[str, Any]:
        from memory_eval.runtime import make_engine

        await checkpoint.clone_database(url, source=template, target=checkpoint.database_name(url), replace=True)
        await checkpoint.clear_room_redis_keys(args.room)
        engine, factory = make_engine(url)
        try:
            common: dict[str, Any] = {
                "room_id": args.room,
                "lane": lane,
                "out_path": out,
                "header": header,
                "expect_snapshots": snapshots[str(args.checkpoint)],
                "before_call": before_call,
            }
            if isinstance(candidate, wp.SummaryCandidate):
                return await wp.replay_summaries(
                    factory, llm, candidate=candidate, writing_model=args.writing_model, **common
                )
            return await wp.replay_facts(factory, llm, candidate=candidate, **common)
        finally:
            await engine.dispose()

    result = asyncio.run(run())
    _print({**result, "version": candidate.version, "label": args.label, "out": str(out)})
    return 0


def cmd_wording_summary(args: argparse.Namespace) -> int:
    """요약 비밀 표기 슬롯 후보로 그 템플릿 방의 접기를 작업 DB 에서 다시 돌린다(템플릿은 복제 원본으로만 쓴다)."""
    return _wording_run(args, "summary")


def cmd_wording_facts(args: argparse.Namespace) -> int:
    """사실 추출 지시문 후보로 그 템플릿 방의 사실 추출을 작업 DB 에서 다시 돌린다."""
    return _wording_run(args, "facts")


def cmd_wording_metrics(args: argparse.Namespace) -> int:
    """결과 파일들의 지표를 개발 문항으로만 세어 숫자만 찍는다(요약 본문·사실 값·문항 id 는 찍지 않는다)."""
    from memory_eval import wording_metrics as wm, wording_proto as wp

    item_ids = [i for i in args.items.split(",") if i] if args.items else None
    per_work: dict[str, dict[str, dict[str, int]]] = {}
    versions: set[tuple[str, str]] = set()
    for work, plants_path, split_dir, result_path in args.set:
        if work in per_work:
            raise SystemExit(f"작품 {work} 가 두 번 들어왔다")
        header, records = wp.read_result(Path(result_path))
        if header.get("run") != args.kind:
            raise SystemExit(f"{work} 결과는 {header.get('run')} 실행이다 — {args.kind} 지표를 셀 수 없다")
        versions.add((str(header.get("version")), str(header.get("candidateSha256"))))
        plant_set = wm.dev_view(Path(plants_path), Path(split_dir))
        count = wm.summary_metrics if args.kind == "summary" else wm.fact_metrics
        per_work[work] = count(plant_set, header, records, item_ids=item_ids)
    if len(versions) != 1:
        raise SystemExit(f"한 번에 한 판만 센다 — 판이 섞였다: {sorted(versions)}")
    _print(wm.report(args.kind, versions.pop()[0], per_work))
    return 0


def cmd_episode_metrics(args: argparse.Namespace) -> int:
    """장면 시제품 결과의 개발 지표(작품마다와 합계). 장면 글·문항 id 는 내보내지 않는다."""
    from memory_eval import wording_metrics as wm

    per_work: dict[str, dict[str, dict[str, int]]] = {}
    versions: set[str] = set()
    for work, plants_path, split_dir, result_path in args.set:
        if work in per_work:
            raise SystemExit(f"작품 {work} 가 두 번 들어왔다")
        result = Path(result_path)
        meta = json.loads(result.with_suffix(".meta.json").read_text(encoding="utf-8"))
        rows = json.loads(result.read_text(encoding="utf-8"))
        versions.add(str(meta.get("version")))
        plant_set = wm.dev_view(Path(plants_path), Path(split_dir))
        per_work[work] = {"all": wm.episode_metrics(plant_set, meta, rows)}
    if len(versions) != 1:
        raise SystemExit(f"한 번에 한 판만 센다 — 판이 섞였다: {sorted(versions)}")
    _print(wm.report("episodes", versions.pop(), per_work))
    return 0


def _kind_quota(value: str) -> tuple[str, int]:
    """`--sample` 한 칸(`종류=수`)."""
    kind, _, count = value.partition("=")
    from memory_eval.judge import VERDICTS

    if kind not in VERDICTS or not count.isdigit() or int(count) < 1:
        raise argparse.ArgumentTypeError(f"표본 수는 '판정 종류=양의 정수' 꼴이다: {value!r}")
    return kind, int(count)


def _check_judge_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.categories is not None and not args.controls:
        parser.error("--categories 는 대조군(--controls)만 거른다")
    if args.boundary_controls and not args.controls:
        parser.error("--boundary-controls 는 대조군(--controls)에서만 쓴다")


def _keep_categories(args: argparse.Namespace, entry: dict[str, Any]) -> bool:
    from memory_eval.judge import judge_kind

    categories: list[str] | None = args.categories
    if args.targeted:
        from memory_eval.verdict_v4 import targeted_asks

        if not targeted_asks(str(entry.get("category")), args.arm):
            return False
    return categories is None or judge_kind(entry) in categories


def _replay_checks(args: argparse.Namespace, points: list[dict[str, Any]], arms: tuple[str, str]) -> dict[str, Any]:
    from memory_eval.verdict import trajectory_checks

    return trajectory_checks(points, recall_section_max=args.section_max, arms=arms)


def _extend_infra(sub: "argparse._SubParsersAction[argparse.ArgumentParser]", parse_categories: Any) -> None:
    """인프라 묶음의 두 명령에 판정 모듈이 필요한 인자를 덧붙인다. 인프라 쪽은 `plan_filter`·`replay_checks` 가 있을 때만 부른다 —
    그래서 이 묶음이 빠진 진입점에서도 두 명령은 판정 없이 돈다."""
    probe = sub.choices.get("probe")
    replay = sub.choices.get("trajectory-replay")
    if probe is None or replay is None:
        raise SystemExit("판정 묶음은 인프라 묶음 뒤에 등록한다(probe·trajectory-replay 가 먼저 있어야 한다)")
    probe.add_argument(
        "--categories",
        type=parse_categories,
        help="이 판정 종류의 문항만 계획한다(쉼표 목록, 기본 전부) — 멈춤 기준도 그 계획의 프로브 수",
    )
    probe.add_argument(
        "--targeted",
        action="store_true",
        help="범주 → 갈래 표대로 이 갈래가 묻는 범주의 문항만 계획한다(표에 없는 범주는 모든 갈래에서) — --categories 와 겹치면 둘 다 맞는 문항",
    )
    # 범주를 고르면 그 범주 문항이 이번 실행의 계획이다(안전 범주만 보내는 갈래) — 멈춤 기준도 그 계획으로 센다.
    probe.set_defaults(plan_filter=_keep_categories)
    replay.add_argument("--section-max", type=int, default=970, help="길이 판정의 같은 턴 차 최대(섹션 최대 + 구분)")
    replay.set_defaults(replay_checks=_replay_checks)


def _v4_args(p: argparse.ArgumentParser, *, out_default: str) -> None:
    """v4-verdict·v4-preview 가 함께 받는 입력 — 두 명령이 같은 판정 함수를 부르므로 입력도 같다."""
    p.add_argument("--story", nargs=2, action="append", required=True, metavar=("PLANTS", "SPLIT_DIR"),
                   help="스토리 대본 하나의 심기 표와 분할 폴더(대본마다 한 번씩)")  # fmt: skip
    p.add_argument(
        "--character",
        nargs=2,
        action="append",
        required=True,
        metavar=("PLANTS", "SPLIT_DIR"),
        help="캐릭터 대본 하나의 심기 표와 분할 폴더(대본마다 한 번씩, 관문 표라 하나 이상 필수)",
    )
    p.add_argument("--scores", type=Path, nargs="+", required=True, help="score 출력(모든 대본·갈래)")
    p.add_argument("--judged", type=Path, nargs="+", required=True, help="judge 출력(모든 대본·갈래)")
    p.add_argument("--controls", type=Path, help="대조군 기록(기본 <원자료>/judge/controls.json)")
    p.add_argument(
        "--split-seeds",
        type=Path,
        help="분할 시드 파일 — 효과마다 합계 하한을 읽어 쌍 수가 그 밑인 효과만 검출력 부족으로 보류한다(없으면 그 효과도 halt)",
    )
    p.add_argument(
        "--accept-failed-controls",
        metavar="SHA256",
        help="관문을 못 넘은 대조군 기록을 사용자가 받아들였을 때 그 기록 파일의 sha256(본 판정 judge 와 같은 값)",
    )
    p.add_argument("--accept-reason", help="--accept-failed-controls 의 이유(누가 왜 — 결과에 남는다)")
    p.add_argument("--trajectory-dir", nargs=3, action="append", default=[], metavar=("SCRIPT", "LANE", "DIR"),
                   help="대본 하나의 trajectory-replay 출력 폴더(대본 이름·레인·폴더)")  # fmt: skip
    p.add_argument(
        "--section-max", nargs="*", default=[], help="쌍마다 섹션 계산 최대 — '기준:비교=글자'(예 b1-A0:b1-A1=970)"
    )
    p.add_argument(
        "--with-a0m",
        action="store_true",
        help="측정에 A0M 갈래를 더했을 때 — A0 대 A0M 쌍을 관문에, 그 비열등을 관찰에 넣는다",
    )
    p.add_argument("--out", type=Path, help=f"기본 {out_default}")
    _ran_args(p)


def register(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    from memory_eval.judge import (
        JUDGE_CONCURRENCY,
        JUDGE_MODEL,
        JUDGE_MODELS,
        parse_categories,
        parse_control_inputs,
        parse_control_tag,
        parse_sha256,
    )

    _extend_infra(sub, parse_categories)

    p = sub.add_parser("recall-offline")
    with_plants(p)
    with_splits(p)
    p.add_argument("--transcript", type=Path, required=True)
    p.add_argument("--episodes", type=Path)
    p.add_argument("--retriever", help="모듈:함수")
    p.add_argument("--checkpoints", default="50,100,300")
    p.add_argument("--context-responses", type=Path, help="[{item, checkpoint, reply}] — B 갈래 맥락 턴 응답")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--out", type=Path)
    p.add_argument("--fusion", choices=["vector", "rrf"], help="벡터 단독 또는 명사·벡터 RRF(없으면 명사 단독)")
    p.add_argument("--embeddings", type=Path, help="미리 계산한 벡터 파일(JSONL)")
    p.add_argument("--embed-model")
    p.add_argument("--embed-dims", type=int)
    _hybrid_args(p, grid=False)
    p.set_defaults(fn=cmd_recall_offline)

    p = sub.add_parser("embed-plan", help="벡터 파일에 없는 장면·질의 글 목록(벡터를 계산할 입력, 호출 없음)")
    with_plants(p)
    with_splits(p)
    p.add_argument("--transcript", type=Path, required=True)
    p.add_argument("--episodes", type=Path, required=True)
    p.add_argument("--checkpoints", default="100,300")
    p.add_argument("--embeddings", type=Path, help="이미 있는 벡터 파일(없으면 전부 빠진 것으로)")
    p.add_argument("--embed-model", required=True)
    p.add_argument("--embed-dims", type=int, required=True)
    p.add_argument("--context-responses", type=Path, help="[{item, checkpoint, reply}] — 지시어 문항 맥락 턴 응답")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_embed_plan)

    p = sub.add_parser("embed-compare", help="임베딩 후보 격자의 견적과 개발 절반 명사·벡터·RRF recall 표")
    p.add_argument("--works", type=Path, required=True, help="작품 목록 JSON(심기 표·분할 폴더·대본·체크포인트별 장면)")
    p.add_argument("--embeddings", type=Path, required=True, help="벡터 파일(JSONL, 유료 실행이면 빠진 글을 덧붙인다)")
    p.add_argument(
        "--candidates", default=None, help="쉼표로 '모델@차원' 목록(기본 Voyage 4 계열 × 4차원 + Gemini 하나)"
    )
    p.add_argument("--retriever", default=SERVER_RETRIEVER, help="명사 쪽 검색 함수(운영 회상만)")
    _hybrid_args(p, grid=True)
    p.add_argument(
        "--objective",
        type=Path,
        default=None,
        help="커밋된 목적함수 파일(rrfGrid) — 주면 RRF 격자에서 그 순서·필수 조건으로 하나를 고른다",
    )
    p.add_argument("--stage", default="s5-embed")
    p.add_argument("--out", type=Path, required=True)
    paid(p)
    p.set_defaults(fn=cmd_embed_compare)

    p = sub.add_parser("export-facts", help="방의 사실 행을 fact-metrics 입력으로(읽기만)")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_export_facts)

    p = sub.add_parser("score")
    with_plants(p)
    with_splits(p)
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("judge")
    with_plants(p)
    with_splits(p)
    paid(p)
    p.add_argument("--controls", action="store_true", help="대조군만")
    p.add_argument(
        "--judge-model",
        choices=sorted(JUDGE_MODELS),
        default=JUDGE_MODEL,
        help="판정자 모델(기본 Haiku 5.5). 다른 모델의 대조군은 controls-<짧은 이름>.json 에 쓴다",
    )
    p.add_argument(
        "--extra-controls", type=Path, nargs="*", default=[], help="실제 응답·합성 견본 대조군(개발 절반 문항만)"
    )
    p.add_argument(
        "--categories",
        type=parse_categories,
        help="대조군을 이 판정 종류만 돌린다(쉼표 목록, 기본 전부). 거르면 결과 파일 이름에 범주 꼬리가 붙는다",
    )
    p.add_argument(
        "--boundary-controls",
        type=Path,
        nargs="+",
        help="경계 견본 파일들(대조군만, id 가 서로·심기 표와 겹치면 거부). 주지 않으면 측정 데이터 폴더의 기본 견본 파일",
    )
    p.add_argument(
        "--control-sources",
        type=parse_control_inputs,
        help="대조군에 넣을 출처(plants·extra·boundary 쉼표 목록, 기본 전부) — 작품마다 나눠 돌리면 경계 견본은 한 번만",
    )
    p.add_argument(
        "--controls-tag",
        type=parse_control_tag,
        help="대조군 결과 파일 이름 꼬리(작품마다 따로 쓰고 judge-controls-merge 로 합친다)",
    )
    p.add_argument(
        "--reuse-judged",
        type=Path,
        help="본 판정: 이 대조군 기록이 같은 입력·같은 표 규칙으로 이미 판정한 응답은 다시 부르지 않고 그 판정을 쓴다",
    )
    p.add_argument(
        "--accept-failed-controls",
        type=parse_sha256,
        metavar="SHA256",
        help="본 판정: 관문을 못 넘은 대조군 기록을 사용자 결정으로 받아들인다 — 그 파일의 sha256 이 같을 때만, 판정 줄마다 남긴다",
    )
    p.add_argument("--accept-reason", help="--accept-failed-controls 의 이유(누가 왜 — 판정 줄마다 남는다)")
    p.add_argument("--probes", type=Path, nargs="*", default=[])
    p.add_argument("--out", type=Path)
    p.add_argument(
        "--concurrency",
        type=int,
        default=JUDGE_CONCURRENCY,
        help=f"동시에 보내는 판정 호출 수 상한(기본 {JUDGE_CONCURRENCY}, 1 이면 직렬)",
    )
    p.set_defaults(fn=cmd_judge, check_args=_check_judge_args)

    p = sub.add_parser("judge-controls-merge", help="작품별 대조군 결과를 본 판정 관문 파일 하나로 합친다")
    p.add_argument("--judge-model", choices=sorted(JUDGE_MODELS), default=JUDGE_MODEL)
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_judge_controls_merge)

    p = sub.add_parser("label-pack", help="실제 프로브 응답의 독립 라벨링 입력(개발 절반만, 파일로만)")
    with_plants(p)
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--kinds", type=parse_categories, help="이 판정 종류만 싣는다(쉼표 목록)")
    p.add_argument(
        "--sample",
        type=_kind_quota,
        action="append",
        help="종류=수 — 그 종류를 (층 표시, 갈래) 칸에 비례해 그 수만 뽑는다(여러 번 줄 수 있다, 없는 종류는 전부)",
    )
    p.add_argument("--seed", type=int, help="--sample 의 시드")
    p.set_defaults(fn=cmd_label_pack)

    p = sub.add_parser("judge-summary", help="판정 결과의 종류별 합격률(unaddressed 따로)")
    p.add_argument("--judged", type=Path, nargs="+", required=True)
    _ran_args(p)
    p.set_defaults(fn=cmd_judge_summary)

    p = sub.add_parser("judge-form-summary", help="거짓 전제 판정의 질문 꼴별 unaddressed 비율(꼴은 심기 표 칸에서)")
    p.add_argument("--judged", type=Path, nargs="+", required=True)
    p.add_argument("--plants", type=Path, nargs="+", required=True, help="판정 줄의 문항이 든 심기 표(대본마다)")
    p.set_defaults(fn=cmd_judge_form_summary)

    p = sub.add_parser("countdown", help="CP300 상영회 카운트다운 — 스탯·노트 본문 존재만, 갈래별")
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.add_argument("--checkpoint", type=int, default=300)
    p.add_argument("--seed-json", type=Path, default=DEFAULT_SEED_JSON)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_countdown)

    p = sub.add_parser("prototype-extract", help="스냅샷마다 장면 시제품 추출(기본 드라이런)")
    paid(p)
    p.add_argument("--fake-llm", action="store_true", help="모델 대신 빈 결과로 렌더·쓰기 경로만 돌린다")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--instruction-file", type=Path, required=True)
    p.add_argument("--version", default="v1")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_prototype_extract)

    p = sub.add_parser("section-grid", help="사실 섹션 선택 방식 격자의 섹션 적중(개발 보기 전용)")
    with_plants(p)
    p.add_argument("--facts", type=Path, required=True, help="사실 행(시제품 JSON 배열 또는 넣기 따라잡기 JSONL)")
    p.add_argument("--checkpoints", default="100,300")
    p.add_argument("--ratios", default="0.3,0.5,0.7", help="상시 몫(상한 대비)")
    p.add_argument("--taus", default="0.4,0.5,0.6", help="관련 행 점수 임계")
    p.add_argument("--max-chars", type=int, help="렌더 상한(기본 700)")
    p.add_argument("--user-name", help="사용자의 이야기 속 이름 — 행에서 자리표시(사용자)로 바꾸고 질의에서도 뺀다")
    p.add_argument("--names", nargs="*", help="질의에서 뺄 이름을 더 준다(인물 이름 등)")
    p.add_argument(
        "--objective",
        type=Path,
        required=True,
        help="고르는 순서를 정한 목적함수 파일(결과보다 먼저 커밋돼 있어야 한다)",
    )
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_section_grid)

    p = sub.add_parser("summary-sections", help="요약 본문의 칸별 글자 수·비율")
    p.add_argument("--inputs", type=Path, nargs="+", required=True, help="memory-snapshots.jsonl 또는 요약 본문 파일")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_summary_sections)

    p = sub.add_parser("s8-verdict", help="최종 짝 비교 판정, 결과 칸 1~7(시험 절반 — 봉인 해시 필요)")
    with_plants(p)
    p.add_argument("--seal-sha", required=True)
    p.add_argument("--scores", type=Path, nargs="+", required=True, help="score 출력(A·B 갈래)")
    p.add_argument("--judged", type=Path, nargs="*", default=[], help="judge 출력")
    p.add_argument("--offline", type=Path, required=True, help="recall-offline 출력(시험 절반)")
    p.add_argument(
        "--trajectory", type=Path, nargs="*", default=[], help="trajectory 점(jsonl, A·B 갈래) — 길이·캐시 블록 칸"
    )
    p.add_argument("--recall-section-max", type=int, help="테스트가 계산한 회상 섹션 최대 글자 — 길이 칸")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_s8)

    p = sub.add_parser("v3-verdict", help="2차 런 최종 짝 비교, 결과 칸 1~7(시험 절반 — 봉인 해시 필요)")
    with_plants(p)
    p.add_argument("--seal-sha", required=True)
    p.add_argument("--scores", type=Path, nargs="+", required=True, help="score 출력(A2·B2 갈래)")
    p.add_argument("--judged", type=Path, nargs="+", required=True, help="judge 출력(A2·B2 갈래)")
    p.add_argument("--controls", type=Path, help="대조군 기록(기본 <원자료>/judge/controls.json)")
    p.add_argument("--trajectory", type=Path, nargs="*", default=[], help="trajectory 점(jsonl, A2·B2)")
    p.add_argument("--section-max", type=int, help="테스트가 계산한 사실 섹션 최대 글자")
    p.add_argument("--unaddressed", default="pass", choices=["pass", "fail", "exclude"])
    p.add_argument("--out", type=Path, help="기본 <원자료>/verdict.json")
    p.set_defaults(fn=cmd_v3_verdict)

    p = sub.add_parser(
        "v4-verdict", help="묶음 1 판정 — 안전 쌍·효과 Holm·비열등·캐릭터 표·켜기 권고(시험 절반 — 봉인 해시 필요)"
    )
    p.add_argument("--seal-sha", required=True)
    p.add_argument(
        "--test-drop", type=Path, help="시험 쪽에서 뺄 id 목록 파일(sha256 이 봉인 문서 머리에 적혀 있어야 한다)"
    )
    _v4_args(p, out_default="<원자료>/b1/measure/verdict.json")
    p.set_defaults(fn=cmd_v4_verdict)

    p = sub.add_parser(
        "v4-preview",
        help="개발 절반 미리보기 — v4-verdict 와 같은 규칙을 개발 문항에(봉인 없이). A0·A1·B1 밖 갈래가 든 쌍·효과는 개발 범위 밖",
    )
    _v4_args(p, out_default="<원자료>/b1/preview/verdict-dev.json")
    p.set_defaults(fn=cmd_v4_preview)

    p = sub.add_parser("v4-power-table", help="봉인 전 통과 최소 불일치 표 — 실제 시험 n 마다 규칙 문턱의 최소 b")
    p.add_argument(
        "--n",
        nargs="+",
        required=True,
        help="표본 — 'secret:story=84' 꼴(키 secret:<레인>·premise:<레인>·effect:<E1|E2>·nonInferiority)",
    )
    p.add_argument("--max-c", type=int, default=5, help="반대쪽 불일치 c 를 0 부터 이 값까지")
    p.add_argument(
        "--facts-inject", action="store_true", help="효과 문턱을 사실 주입 재측정의 효과 표로(키 effect:factsInject)"
    )
    p.set_defaults(fn=cmd_v4_power_table)

    p = sub.add_parser(
        "facts-inject-summary",
        help="사실 주입 재측정 집계 — 현 운영 갈래 → 사실 주입 갈래 효과, 사실 섹션 실림 턴 수, 관찰 칸(시험은 봉인 해시 필요)",
    )
    p.add_argument("--split", choices=("dev", "test"), default="test")
    p.add_argument("--seal-sha", help="시험 절반(--split test)이면 필수 — 이번 판 봉인 문서의 sha256")
    p.add_argument("--test-drop", type=Path, help="시험 쪽에서 뺄 id 목록 파일(sha256 이 봉인 문서 머리에 있어야 한다)")
    p.add_argument("--story", nargs=2, action="append", required=True, metavar=("PLANTS", "SPLIT_DIR"),
                   help="스토리 대본 하나의 심기 표와 분할 폴더(대본마다 한 번씩) — 효과와 관찰 칸")  # fmt: skip
    p.add_argument("--character", nargs=2, action="append", metavar=("PLANTS", "SPLIT_DIR"),
                   help="캐릭터 대본 하나의 심기 표와 분할 폴더 — 관찰 칸에만 든다")  # fmt: skip
    p.add_argument("--scores", type=Path, nargs="+", required=True, help="score 출력(두 갈래)")
    p.add_argument("--judged", type=Path, nargs="+", required=True, help="judge 출력(두 갈래)")
    p.add_argument("--split-seeds", type=Path, help="분할 시드 파일 — 효과의 합계 하한(없으면 표본이 모자란 효과는 halt)")
    p.add_argument("--controls", type=Path, help="판정자 대조군 기록(기본 <원자료>/judge/controls.json, 없으면 halt)")
    p.add_argument(
        "--accept-failed-controls", metavar="SHA256", help="관문을 못 넘은 대조군 기록을 사용자가 받아들였을 때 그 파일의 sha256"
    )
    p.add_argument("--accept-reason", help="--accept-failed-controls 의 이유(누가 왜 — 결과에 남는다)")
    p.add_argument("--out", type=Path, required=True)
    _ran_args(p)
    p.set_defaults(fn=cmd_facts_inject_summary)

    from memory_eval import judge_agreement as ja

    p = sub.add_parser(
        "judge-agreement", help="덤프 판정 줄을 판정 모델마다 반복 재판정 — 자기 반복·교차 일치율(기본 집계만)"
    )
    paid(p)
    p.add_argument("--fake-llm", action="store_true", help="가짜 판정기로 절차만(원장·결과 파일도 따로)")
    p.add_argument("--dumps", type=Path, nargs="+", required=True, help="측정 서버 프롬프트 덤프(JSONL)")
    p.add_argument("--reps", type=int, default=5, help="줄·모델마다 반복 수")
    p.add_argument("--models", default="haiku", help="쉼표 목록(gemini·haiku). 합격 판정은 --candidate 하나로 한다")
    p.add_argument("--gemini-model", help="Gemini 판정 모델 id(전환 전 운영 판정 모델) — gemini 를 쓰면 필수")
    p.add_argument("--call-sites", help="쉼표 목록(기본 범위 전부)")
    p.add_argument("--limit", type=int, help="앞에서 이 수의 판정 줄만(견적용 실측은 --limit 1 --reps 1)")
    p.add_argument("--controls", type=Path, help="망친 입력 대조군 명세 JSON")
    p.add_argument("--strata", type=Path, help="카운트다운 층 표 JSON [{roomId, turn, stratum, expectDecrement}]")
    p.add_argument("--countdown-stat", default="상영회까지")
    p.add_argument("--candidate", default="haiku", help="합격 판정을 받을 판정 모델")
    p.add_argument("--baseline", help="후보와의 교차 일치율을 참고로 낼 모델(판정에 쓰지 않는다)")
    p.add_argument(
        "--min-self",
        type=float,
        default=ja.DEFAULT_MIN_SELF_AGREEMENT,
        help="자기 반복 일치율 하한(전체 줄·발동한 줄 모두)",
    )
    p.add_argument(
        "--min-fired-lines",
        type=int,
        default=ja.DEFAULT_MIN_FIRED_LINES,
        help="호출 위치마다 발동한 줄이 이보다 적으면 판정 보류",
    )
    p.add_argument(
        "--max-quiet-decrement",
        type=float,
        default=ja.DEFAULT_MAX_QUIET_DECREMENT,
        help="시간이 움직이지 않은 층의 감소 비율 상한",
    )
    p.add_argument(
        "--min-decrement", type=float, default=ja.DEFAULT_MIN_DECREMENT, help="시간이 움직인 층의 감소 비율 하한"
    )
    p.add_argument(
        "--min-control-reaction", type=float, default=ja.DEFAULT_MIN_CONTROL_REACTION, help="대조군 반응률 하한"
    )
    p.add_argument("--tokens-per-char", help="견적 자리값: 1.0 또는 gemini=0.7,haiku=1.1")
    p.add_argument("--output-tokens", type=int, default=60, help="견적 자리값: 호출당 출력 토큰")
    p.add_argument(
        "--order-seed",
        type=int,
        help="호출 키(줄 × 판 × 반복) 전체를 이 씨앗으로 섞어 부른다(없으면 줄 → 판 → 반복 순서)",
    )
    p.add_argument("--label", default="judge-agreement", help="원장 단계 이름")
    p.add_argument("--out-dir", type=Path, help="기본 <원자료>/judge-agreement")
    p.set_defaults(fn=cmd_judge_agreement)

    from memory_eval import judge_reason as jr

    p = sub.add_parser(
        "judge-reason",
        help="스탯 판정 줄을 운영 판정기로 이유 칸 없는 판·있는 판 반복 재판정 — 판마다 자기 반복·판 사이 일치율(기본 집계만)",
    )
    paid(p)
    p.add_argument("--fake-llm", action="store_true", help="가짜 판정기로 절차만(원장·결과 파일도 따로)")
    p.add_argument(
        "--baseline-dumps", type=Path, nargs="+", help="기준선 덤프(JSONL) — 줄 id 가 일치율 도구와 같은 꼴, 파일 이름이 겹치면 거부"
    )
    p.add_argument("--baseline-sample", type=int, help="기준선에서 방마다 고르게 고를 줄 수(기본 스탯 줄 전부)")
    p.add_argument(
        "--dev-dumps", type=Path, nargs="+", help="개발 측정 덤프(JSONL, 파일 이름이 같아도 된다 — 공통 상위 폴더의 상대 경로로 가른다)"
    )
    p.add_argument("--dev-sample", type=int, help="개발 덤프에서 방마다 고르게 고를 줄 수(--dev-dumps 와 함께 필수)")
    p.add_argument("--seed", type=int, help="표본 고르기 씨앗(표본을 고르면 필수)")
    p.add_argument("--controls", type=Path, help="망친 입력 대조군 명세 JSON(일치율 도구와 같은 꼴)")
    p.add_argument("--reps", type=int, default=5, help="줄·판마다 반복 수")
    p.add_argument("--tokens-per-char", type=float, default=ja.DEFAULT_TOKENS_PER_CHAR, help="견적 자리값: 글자당 입력 토큰")
    p.add_argument(
        "--output-tokens", type=int, default=jr.DEFAULT_PLAIN_OUTPUT_TOKENS, help="견적 자리값: 이유 없는 판의 호출당 출력 토큰"
    )
    p.add_argument(
        "--reason-output-tokens", type=int, default=jr.DEFAULT_REASON_OUTPUT_TOKENS, help="견적 자리값: 이유 판의 호출당 출력 토큰"
    )
    p.add_argument(
        "--order-seed",
        type=int,
        help="호출 키(줄 × 판 × 반복) 전체를 이 씨앗으로 섞어 부른다(없으면 줄 → 판 → 반복 순서)",
    )
    p.add_argument("--label", default="judge-reason", help="원장 단계 이름")
    p.add_argument("--out-dir", type=Path, help="기본 <원자료>/s5/judge-reason")
    p.set_defaults(fn=cmd_judge_reason)

    p = sub.add_parser(
        "judge-majority", help="판정 반복 기록으로 k 표 다수결과 단일 판정의 일치율 plug-in 어림(호출 없음)"
    )
    p.add_argument("--calls", type=Path, required=True, help="judge-agreement·judge-reason 의 결과 파일(calls.jsonl)")
    p.add_argument("--model", default="haiku", help="볼 판정 모델·판 이름(결과 줄의 model 칸)")
    p.add_argument("--k", type=int, default=3, help="다수결 표 수")
    p.add_argument("--vote", choices=["ruleSet", "appliedChange"], default="ruleSet", help="표를 던지는 공간")
    p.add_argument(
        "--deltas", type=Path, help="짧은 규칙 id → 폭 JSON(한 작품의 스탯 줄 구성) — 변화량·방향 지표에 필요"
    )
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_judge_majority)

    p = sub.add_parser("judge-strata", help="드라이버 로그의 층 태그로 judge-agreement 층 표를 만든다")
    p.add_argument("--log", type=Path, required=True, help="드라이버 --log")
    p.add_argument("--script", type=Path, help="기본 측정 데이터 폴더의 스토리 판정 대본")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_judge_strata)

    p = sub.add_parser("judge-branch", help="엔딩 갈래: 얼린 템플릿에서 복원해 갈래마다 판정 차례 턴 하나(작업 DB 만)")
    paid(p)
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--checkpoint", type=int, required=True, help="얼린 체크포인트 번호(엔딩 층 직전 턴)")
    p.add_argument("--label", required=True, help="얼릴 때 준 단계 이름")
    p.add_argument("--script", type=Path, help="기본 측정 데이터 폴더의 스토리 판정 대본")
    p.add_argument("--branches", help="쉼표 목록(기본 전부)")
    p.add_argument("--cred-file", type=Path, required=True)
    p.add_argument("--cookie-file", type=Path, required=True)
    p.add_argument("--port", type=int, default=8130)
    p.add_argument("--server-env", type=Path, help="서버에 덮어 줄 KEY=VALUE 파일(키 값은 넣지 않는다)")
    p.set_defaults(fn=cmd_judge_branch)

    p = sub.add_parser(
        "judge-controls", help="망친 입력 대조군 명세를 정한 규칙·문장으로 만든다(판정 결과를 읽지 않음)"
    )
    p.add_argument("--dumps", type=Path, nargs="+", required=True, help="judge-agreement 에 줄 덤프와 같은 목록")
    p.add_argument("--strata", type=Path, required=True, help="확정 층 표")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_judge_controls)

    p = sub.add_parser("judge-sample-estimate", help="판정 표본 생성(Opus 직결) 원가 견적 — 호출 없음")
    p.add_argument("--prompt-tokens", type=int, default=20_000, help="턴당 평균 생성 프롬프트 토큰")
    p.add_argument("--new-tokens-per-turn", type=int, default=1_200, help="턴마다 새로 붙어 캐시에 쓰는 토큰")
    p.add_argument("--output-tokens", type=int, default=600)
    p.set_defaults(fn=cmd_judge_sample_estimate)

    for name, fn in (("b1-wording-summary", cmd_wording_summary), ("b1-wording-facts", cmd_wording_facts)):
        p = sub.add_parser(name, help="얼린 개발 투입 템플릿을 작업 DB 로 복제해 후보 문안으로 다시 돌린다")
        with_plants(p)
        paid(p)
        p.add_argument("--fake-llm", action="store_true")
        p.add_argument("--candidate", type=Path, required=True, help="후보 문안 파일(JSON)")
        p.add_argument("--label", required=True, help="투입 단계 이름(템플릿 lm_eval_<이름>_cp<T>_frozen)")
        p.add_argument("--checkpoint", type=int, default=300)
        p.add_argument("--dumps-dir", type=Path, required=True, help="템플릿을 얼릴 때 남긴 지문 폴더")
        p.add_argument("--room", type=uuid.UUID)
        p.add_argument("--usage-ledger", type=Path, help="견적 바탕 — 그 템플릿을 만든 투입의 원장")
        p.add_argument("--margin", type=float, default=1.25, help="견적 여유 배수")
        p.add_argument("--out-dir", type=Path, help="결과 폴더(기본 <원자료>/wording)")
        p.add_argument(
            "--writing-model",
            default="opus",
            choices=["gemini", "sonnet", "opus"],
            help="템플릿 투입에서 응답을 쓴 모델(접기의 기억 사용 범위 판정에 쓴다)",
        )
        p.set_defaults(fn=fn)

    p = sub.add_parser("b1-wording-metrics", help="문안 시제품 결과의 지표 — 개발 문항으로만, 숫자만")
    p.add_argument("--kind", choices=("summary", "facts"), required=True)
    p.add_argument(
        "--set",
        nargs=4,
        action="append",
        required=True,
        metavar=("WORK", "PLANTS", "SPLIT_DIR", "RESULT"),
        help="작품 이름·심기 표·분할 폴더·결과 파일(작품마다 한 번)",
    )
    p.add_argument("--items", help="개발 문항 id 로 좁혀 센다(쉼표). 시험 id 는 거부한다")
    p.set_defaults(fn=cmd_wording_metrics)

    p = sub.add_parser("b1-episode-metrics", help="장면 시제품 결과의 지표 — 개발 문항으로만, 숫자만")
    p.add_argument(
        "--set",
        nargs=4,
        action="append",
        required=True,
        metavar=("WORK", "PLANTS", "SPLIT_DIR", "RESULT"),
        help="작품 이름·심기 표·분할 폴더·장면 시제품 결과 JSON(옆에 .meta.json)",
    )
    p.set_defaults(fn=cmd_episode_metrics)
