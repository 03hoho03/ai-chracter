"""장기 기억 평가 하네스 CLI(실험 브랜치 전용 — 병합하지 않는다).

    cd apps/api
    uv run --env-file .env python scripts/memory_eval_cli.py <명령> --run <원자료 폴더> ...

DB 를 쓰는 명령은 실행 명령의 `DATABASE_URL` 로 작업 DB(이름 `lm_eval_` 로 시작)를 준다 — `.env` 의 값보다 명령의 값이 이긴다.
유료 호출이 날 수 있는 명령(insert·probe·judge·prototype-extract·trajectory 의 토큰 세기)은 `--dry-run` 이 기본 동작이고, 실제
호출은 `--allow-paid` 를 명시해야 한다(원장 상한을 본 뒤). 가짜 LLM(`--fake-llm`)은 절차 확인용이다.

종료 코드: 0 정상 · 1 검사 위반(check-script) · 2 인자·환경 거부 · 20 원장 상한."""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memory_eval import checkpoint, holdout, ledger as ledger_mod, plants as plants_mod
from memory_eval.ledger import EXIT_BUDGET, BudgetExceededError, Ledger
from memory_eval.seal import PREREGISTRATION_FILE, require_seal
from memory_eval.transcript import LengthRule, check_script, load_transcript, work_text_from_seed

if TYPE_CHECKING:
    from api.llm.client import LLMClient

    from memory_eval.fact_catchup import FactCatchUp

DEFAULT_SEED_JSON = Path(__file__).resolve().parent / "seed_content/data/tutorial/stories/tutorial-filmclub.json"


def _range(raw: str) -> tuple[int, int]:
    low, high = raw.split(",")
    return int(low), int(high)


def _ints(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


def _splits(args: argparse.Namespace) -> set[str]:
    splits = set(args.splits.split(","))
    require_seal(splits, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha)
    return splits


def _ledger(args: argparse.Namespace) -> Ledger:
    """원장 — 상한과 멈춤 선은 실행 인자(기본은 이 런의 승인 값)."""
    return Ledger(args.run / "ledger.jsonl", cap_usd=args.cap_usd, halt_usd=args.halt_usd)


def _plant_view(args: argparse.Namespace, splits: set[str] | None = None) -> plants_mod.PlantSet:
    """심기 표를 읽는 모든 명령의 입구. 1차 형식은 항목의 분할 칸을 그대로 쓰고, 2차 형식은 분할 파일로 보기를 만든다 — 절반을
    주지 않으면 개발 보기이고, 시험 절반은 봉인 확인을 지나야 시험 정답 파일을 연다."""
    raw = json.loads(args.plants.read_text(encoding="utf-8"))
    if not holdout.is_v2(raw):
        return plants_mod.load_plants(args.plants)
    return holdout.load_view(
        args.plants,
        args.split_dir or args.run / holdout.SPLIT_DIR,
        splits or {"dev"},
        preregistration=args.run / PREREGISTRATION_FILE,
        seal_sha=getattr(args, "seal_sha", None),
    )


def _refuse_v2(args: argparse.Namespace, command: str) -> None:
    if holdout.is_v2(json.loads(args.plants.read_text(encoding="utf-8"))):
        raise SystemExit(
            f"{command} 는 1차 형식 심기 표 전용이다(2차 형식은 항목에 분할 칸이 없고 시험 문항을 함께 읽게 된다)"
        )


# ---------------------------------------------------------------- 대본·심기 표·예산


def cmd_check_script(args: argparse.Namespace) -> int:
    _refuse_v2(args, "check-script")
    plant_set = plants_mod.load_plants(args.plants)
    report = check_script(
        load_transcript(args.transcript),
        plant_set,
        work_text=work_text_from_seed(args.seed_json),
        rule=LengthRule(user=_range(args.user_len), narrator=_range(args.narrator_len)),
        expected_turns=args.turns,
    )
    import hashlib

    report["transcriptSha256"] = hashlib.sha256(args.transcript.read_bytes()).hexdigest()
    report["plantsSha256"] = hashlib.sha256(args.plants.read_bytes()).hexdigest()
    _write(args.out, report)
    print(f"위반 {len(report['violations'])}건 → {args.out}")
    return 1 if report["violations"] else 0


def cmd_split_check(args: argparse.Namespace) -> int:
    _refuse_v2(args, "split-check")
    plant_set = plants_mod.load_plants(args.plants)
    _print([plants_mod.split_agreement(plant_set, rule=rule) for rule in ("category", "role")])
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    """2차 형식 심기 표를 개발/시험으로 한 번 나눈다. 표준출력은 범주별 개수와 시험 정답 파일 sha256 뿐이다."""
    result = holdout.write_split(args.plants, args.out_dir or args.run / holdout.SPLIT_DIR)
    _print({"counts": result["counts"], "testKeysSha256": result["testKeysSha256"]})
    if not result["ok"]:
        print(
            f"시험 절반 주 지표 {result['testPrimary']}개 — 하한 {holdout.TEST_PRIMARY_MIN} 미만이라 쓰지 않았다",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    plant_set = _plant_view(args, _splits(args))
    extras = {name: float(value) for name, value in (e.split("=") for e in args.extra)}
    estimate = ledger_mod.budget_estimate(
        plant_set,
        arms=args.arms,
        opus_turn_usd=args.opus_turn_usd,
        server_judgment_turn_usd=args.judgment_turn_usd,
        extras=extras,
        cap_usd=args.cap_usd,
    )
    estimate["ledgerSpentUsd"] = _ledger(args).total_usd()
    estimate["haltUsd"] = args.halt_usd
    _print(estimate)
    return 0


# ---------------------------------------------------------------- DB


def _db_url(*, writes: bool) -> str:
    from memory_eval.runtime import work_database_url

    return work_database_url(writes=writes)


def cmd_init_work_db(args: argparse.Namespace) -> int:
    from replay.local_db import ensure_local_database

    from api.core.config import settings

    ensure_local_database(settings.database_url, tool="memory_eval")
    checkpoint.ensure_eval_db_name(checkpoint.database_name(settings.database_url))
    asyncio.run(
        checkpoint.clone_database(
            settings.database_url,
            source=args.source,
            target=checkpoint.database_name(settings.database_url),
            replace=args.replace,
        )
    )
    print(f"{args.source} → {checkpoint.database_name(settings.database_url)} 복제 완료")
    return 0


def cmd_drop_eval_db(args: argparse.Namespace) -> int:
    asyncio.run(checkpoint.drop_database(_db_url(writes=True), args.name))
    print(f"{args.name} 삭제")
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    url = _db_url(writes=True)
    result = asyncio.run(
        checkpoint.freeze(
            url,
            work_db=checkpoint.database_name(url),
            checkpoint=args.checkpoint,
            room_id=args.room,
            dumps_dir=args.run / "dumps",
            container=args.pg_container,
            db_user=args.db_user,
            label=args.label,
            require_episode_rows=args.require_episodes,
        )
    )
    _print(result)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    url = _db_url(writes=True)
    _print(
        asyncio.run(
            checkpoint.restore(
                url,
                work_db=checkpoint.database_name(url),
                checkpoint=args.checkpoint,
                room_id=args.room,
                dumps_dir=args.run / "dumps",
                label=args.label,
            )
        )
    )
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    _print(asyncio.run(checkpoint.read_fingerprint(_db_url(writes=False), args.room)))
    return 0


def cmd_grant_clover(args: argparse.Namespace) -> int:
    from api.db.models import ChatRoom

    from memory_eval.room import grant_clover
    from memory_eval.runtime import make_engine

    async def go() -> None:
        engine, factory = make_engine(_db_url(writes=True))
        try:
            async with factory() as db:
                room = await db.get(ChatRoom, args.room)
                if room is None:
                    raise SystemExit("방이 없다")
                await grant_clover(db, room.user_id, args.amount)
        finally:
            await engine.dispose()

    asyncio.run(go())
    print(f"클로버 {args.amount} 지급")
    return 0


def cmd_set_model(args: argparse.Namespace) -> int:
    from memory_eval.room import set_room_model

    _print(set_room_model(args.base, args.cookie_file.read_text(encoding="utf-8").strip(), args.room, args.model))
    return 0


# ---------------------------------------------------------------- 넣기·궤적


def cmd_insert(args: argparse.Namespace) -> int:
    from memory_eval import insert
    from memory_eval.pinned_stats import load_pinned_doc

    plant_set = _plant_view(args)
    freeze_at = _ints(args.freeze_at)
    if args.dry_run:
        report = insert.plan(
            plant_set,
            start_turn=args.start,
            until_turn=args.until,
            freeze_at=freeze_at,
            extract=args.extract,
            extract_facts=args.extract_facts,
        )
        report["ledgerSpentUsd"] = _ledger(args).total_usd()
        _print(report)
        return 0
    if args.fake_llm == args.allow_paid:
        raise SystemExit("--fake-llm 과 --allow-paid 중 정확히 하나(또는 --dry-run)")
    from api.llm.client import LLMClient

    llm: LLMClient
    if args.fake_llm:
        from memory_eval.fake_llm import FakeMemoryLLM

        llm = FakeMemoryLLM()
    else:
        from api.llm.dependencies import get_llm_client

        llm = insert.LedgerTap(
            get_llm_client(),
            _ledger(args),
            stage=args.label,
            per_call_estimate_usd=insert.FOLD_CALL_ESTIMATE_USD,
        )
    facts = _fact_catch_up(args, llm) if args.extract_facts else None
    result = asyncio.run(
        insert.run_insert(
            script=load_transcript(args.transcript),
            plant_set=plant_set,
            room_id=args.room,
            until_turn=args.until,
            freeze_at=freeze_at,
            llm=llm,
            extract=args.extract,
            arms=[a for a in args.arms.split(",") if a],
            trajectory_model=args.trajectory_model,
            run_dir=args.run,
            label=args.label,
            cookie_value=args.cookie_file.read_text(encoding="utf-8") if args.cookie_file else None,
            database_url=_db_url(writes=True),
            container=args.pg_container,
            db_user=args.db_user,
            recall_field=args.recall_field,
            recall_header=args.recall_header,
            pinned_doc=load_pinned_doc(args.checkpoint_stats) if args.checkpoint_stats else None,
            facts=facts,
        )
    )
    _print(result)
    return 0


def _fact_catch_up(args: argparse.Namespace, llm: "LLMClient") -> "FactCatchUp":
    """사실 추출 따라잡기 — 운영 모듈이 있으면 넣기의 LLM 클라이언트로 그것을, 없으면 시제품을 부른다. 시제품의 호출은 가짜
    LLM 실행이면 빈 결과, 유료 실행이면 Anthropic 직결(원장 상한 확인 뒤)이다."""
    from memory_eval import prototype_facts as pf
    from memory_eval.fact_catchup import fact_catch_up

    instruction = args.facts_instruction_file.read_text(encoding="utf-8") if args.facts_instruction_file else None
    if args.fake_llm:

        async def caller(prompt: str) -> pf.PrototypeFactResult:
            return pf.PrototypeFactResult(facts=[])

        instruction = instruction or "(가짜 실행 — 문안 없음)"
    else:
        from api.core.config import settings

        book = _ledger(args)

        async def caller(prompt: str) -> pf.PrototypeFactResult:
            return await pf.call_haiku(settings.anthropic_direct_api_key, prompt, book, stage=f"{args.label}-facts")

    return fact_catch_up(
        llm,
        store=pf.FactStore(args.run / f"facts-{args.label}.jsonl"),
        caller=caller,
        instruction=instruction,
        version=args.facts_version,
    )


def cmd_trajectory(args: argparse.Namespace) -> int:
    from memory_eval.runtime import make_engine
    from memory_eval.trajectory import append_point, assemble_point

    async def go() -> list[dict[str, Any]]:
        engine, factory = make_engine(_db_url(writes=False))
        points = []
        try:
            for arm in args.arms.split(","):
                async with factory() as db:
                    point, _ = await assemble_point(
                        db,
                        args.room,
                        next_turn=args.next_turn,
                        user_content=args.user_text,
                        arm=arm,
                        model=args.model,
                        recall_header=args.recall_header,
                        recall_field=args.recall_field,
                    )
                append_point(args.run / f"trajectory-{args.label}-{arm}.jsonl", point)
                points.append(point)
        finally:
            await engine.dispose()
        return points

    _print(asyncio.run(go()))
    return 0


# ---------------------------------------------------------------- 오프라인 회상


def cmd_recall_offline(args: argparse.Namespace) -> int:
    from memory_eval import recall_offline as ro

    splits = _splits(args)
    plant_set = _plant_view(args, splits)
    script = load_transcript(args.transcript)
    context = {}
    if args.context_responses:
        for row in json.loads(args.context_responses.read_text(encoding="utf-8")):
            context[(str(row["item"]), int(row["checkpoint"]))] = str(row["reply"])
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
    retriever = ro.load_retriever(args.retriever)
    rows = [
        r
        for cp in cps
        for r in ro.run_checkpoint(plant_set, script, cp, episodes, retriever, splits=splits, context_responses=context)
    ]
    report = {
        "splits": sorted(splits),
        "rows": rows,
        "byForm": ro.summarize(rows, key=lambda r: f"cp{r['checkpoint']}:{r['kind']}:{r['form']}"),
        "extraction": ro.extraction_report(plant_set, episodes, splits=splits),
    }
    _write(args.out, report)
    print(f"{len(rows)}문항 → {args.out}")
    return 0


def cmd_export_episodes(args: argparse.Namespace) -> int:
    """방의 장면을 오프라인 회상 입력(JSON)으로 — 명사는 저장된 값, 검색 대상이 되는 첫 턴은 스냅샷 커서로 계산. 읽기만."""
    from memory_eval.runtime import make_engine
    from memory_eval.server_recall import export_episodes

    async def go() -> list[dict[str, Any]]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                return await export_episodes(db, args.room)
        finally:
            await engine.dispose()

    rows = asyncio.run(go())
    _write(args.out, rows)
    print(f"장면 {len(rows)}개 → {args.out}")
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


def cmd_recall_parity(args: argparse.Namespace) -> int:
    """같은 질의를 두 검색 함수로 돌린 `recall-offline` 출력 둘을 행 단위로 견준다."""
    from memory_eval.recall_offline import compare_rows

    a, b = (json.loads(path.read_text(encoding="utf-8"))["rows"] for path in (args.a, args.b))
    result = {"a": str(args.a), "b": str(args.b), **compare_rows(a, b)}
    _write(args.out, result)
    _print({k: result[k] for k in ("rows", "matched", "rate")})
    return 0


def cmd_recall_warnings(args: argparse.Namespace) -> int:
    """로그 파일마다 서버 회상 실패 경고 줄 수와 합계."""
    from memory_eval.probe import recall_warning_count

    counts = {str(p): recall_warning_count(p.read_text(encoding="utf-8", errors="replace")) for p in args.logs}
    _print({"files": len(counts), "total": sum(counts.values()), "nonzero": {k: v for k, v in counts.items() if v}})
    return 0


# ---------------------------------------------------------------- 프로브·채점


def cmd_probe(args: argparse.Namespace) -> int:
    from memory_eval import probe as probe_mod

    plant_set = _plant_view(args, _splits(args))
    cps = _ints(args.checkpoints)
    items = set(args.items.split(",")) if args.items else None
    for item_id in sorted(items or ()):
        plant_set.item(item_id)  # 숨긴 시험 문항이면 거부, 없는 문항이면 KeyError
    probes = [p for cp in cps for p in plants_mod.opus_probes(plant_set, cp) if items is None or p.item_id in items]
    book = _ledger(args)
    out = args.run / "probes" / f"{args.stage}-{args.arm}.jsonl"
    done = (
        [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        if out.exists()
        else []
    )
    probes, unprobeable = probe_mod.pending_probes(probes, done)
    if args.dry_run or not args.allow_paid:
        turns = sum(len(p.turns) for p in probes)
        _print(
            {
                "stage": args.stage,
                "arm": args.arm,
                "probes": len(probes),
                "turns": turns,
                "twoTurn": sum(1 for p in probes if p.two_turn),
                "estimateUsd": turns * (args.opus_turn_usd + args.judgment_turn_usd),
                "ledgerSpentUsd": book.total_usd(),
                "alreadyDone": len(done),
                "unprobeableSoFar": unprobeable,
                "plan": [{"cp": p.checkpoint, "item": p.item_id, "turns": p.turns} for p in probes],
            }
        )
        return 0
    overrides: dict[str, str] = {"CHAT_PREMIUM_MODELS_ENABLED": "true"}
    if args.server_env:
        for line in args.server_env.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                key, _, value = line.partition("=")
                overrides[key.strip()] = value.strip()
    else:
        from memory_eval.arm_env import ARM_ENV, env_pairs

        if args.arm in ARM_ENV:
            # 2차 런 갈래는 env 표를 그대로 쓴다 — 파일을 손으로 옮기다 공통 줄이 갈래마다 갈리지 않게.
            overrides.update(dict(env_pairs(args.arm)))
    from memory_eval import server
    from memory_eval.runtime import require_arm_supported

    require_arm_supported(args.arm)
    if server.port_in_use(args.port):
        raise SystemExit(f"포트 {args.port} 에 이미 서버가 있다")
    trees = [str(p) for p in server.API_DIR.parents[1].parent.glob("long-memory*")]
    others = server.conflicting_servers(server.running_api_servers(), trees, own_pids=set())
    if others:
        raise SystemExit(f"같은 격리 Redis·DB 를 쓰는 다른 API 서버가 떠 있다 — 내린 뒤 다시: {others}")
    run = probe_mod.ProbeRun(
        stage=args.stage,
        arm=args.arm,
        room_id=args.room,
        run_dir=args.run,
        database_url=_db_url(writes=True),
        cred_file=args.cred_file,
        cookie_file=args.cookie_file,
        port=args.port,
        server_overrides=overrides,
        allow_paid=args.allow_paid,
        opus_turn_usd=args.opus_turn_usd,
        judgment_turn_usd=args.judgment_turn_usd,
        ledger=book,
        pacer=probe_mod.BurstPacer(limit=args.burst_limit, window_seconds=60.0),
        checkpoint_label=args.checkpoint_label or args.stage,
    )
    for p in probes:
        result = probe_mod.run_probe(run, p)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        print(f"{p.item_id} cp{p.checkpoint}: {result['status']}")
        unprobeable += result["status"] == "unprobeable"
        if probe_mod.should_halt(unprobeable, args.halt_base):
            raise SystemExit(f"프로브 불능 {unprobeable}건 — 멈추고 묻는다")
    if out.exists():
        _print(probe_mod.probe_summary(_probe_rows([out])))
    return 0


def _probe_rows(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def cmd_latency(args: argparse.Namespace) -> int:
    """프로브 결과 파일들의 갈래별 상태 수와 첫 글자 지연 p50·p95."""
    from memory_eval.probe import probe_summary

    _print(probe_summary(_probe_rows(args.probes)))
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

    controls_path = args.run / "judge" / "controls.json"
    if args.controls:
        # 대조군은 개발 절반 문항만 — 판정 문안을 대조군 오판으로 다듬으므로 시험 문항이 섞이면 안 된다.
        plant_set = _plant_view(args, {"dev"})
        items = judge_mod.controls(plant_set)
        for path in args.extra_controls:
            items += judge_mod.load_extra_controls(path, plant_set)
    else:
        splits = _splits(args)
        plant_set = _plant_view(args, splits)
        rows = [r for r in _probe_rows(args.probes) if r["split"] in splits and r["status"] == "accept"]
        items = [
            {
                "item": r["item"],
                "arm": r["arm"],
                "checkpoint": r["checkpoint"],
                "kind": kind,
                "replies": [t["reply"] for t in r["turns"]],
            }
            for r in rows
            if (kind := judge_mod.judge_kind(plant_set.item(r["item"]))) is not None
        ]
    if args.dry_run or not args.allow_paid:
        _print(
            {
                "calls": len(items),
                "estimateUsd": judge_mod.judge_estimate_usd(len(items)),
                "controls": args.controls,
            }
        )
        return 0
    if not args.controls:
        judge_mod.require_controls_passed(controls_path)
    from api.core.config import settings

    judge = judge_mod.HaikuJudge(settings.anthropic_direct_api_key, _ledger(args), stage="judge")

    async def go() -> list[dict[str, Any]]:
        out = []
        for item in items:
            entry = plant_set.item(item["item"])
            replies = judge_mod.control_replies(item) if args.controls else item["replies"]
            prompt = judge_mod.judge_prompt(item["kind"], entry, replies)
            judged, votes = await judge_mod.judged_majority(judge, item["kind"], prompt)
            out.append({**item, "judged": judged, "votes": votes})
        return out

    results = asyncio.run(go())
    if args.controls:
        judged = [r for r in results if r["judged"] is not None]
        accuracy = sum(1 for r in judged if judge_mod.control_correct(r)) / len(results) if results else 0.0
        _write(
            controls_path,
            {
                "passed": judge_mod.controls_pass(results),
                "accuracy": accuracy,
                "accuracyByKind": judge_mod.control_accuracy(results),
                "rows": results,
            },
        )
    else:
        _write(args.out, results)
    return 0


def cmd_judge_summary(args: argparse.Namespace) -> int:
    """판정 결과의 종류별 합격률을 `unaddressed` 처리 방식 세 가지로 모두 낸다 — 봉인 문서가 하나를 고정하더라도 요약이 셋을
    함께 보여 결과를 본 뒤 유리한 방식을 고르는 일이 드러나게."""
    from memory_eval.judge import UNADDRESSED_POLICIES, summarize_judged

    rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    _print({policy: summarize_judged(rows, unaddressed=policy) for policy in UNADDRESSED_POLICIES})
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


def cmd_attribution(args: argparse.Namespace) -> int:
    from memory_eval.attribution import attribute
    from memory_eval.transcript import work_text_from_seed as seed_text

    splits = _splits(args)
    plant_set = _plant_view(args, splits)
    statics = [seed_text(args.seed_json)]
    out = []
    for row in _probe_rows(args.probes):
        if row["split"] not in splits or row["status"] != "accept":
            continue
        entry = plant_set.item(row["item"])
        folder = Path(row["attempts"][-1]["folder"])
        dumps = [
            json.loads(line)
            for line in (folder / "prompt-dump.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        generation = [d for d in dumps if d.get("kind") == "generation"]
        snapshots = [
            json.loads(line)
            for line in (folder / "memory-snapshots.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # 기억 조회는 바뀐 턴에만 전문이 남는다 — 그 턴 이전의 마지막 전문을 쓴다.
        memory = [s for s in snapshots if s.get("kind") == "memorySnapshot"]
        for i in range(len(row["turns"])):
            prompt = generation[i]["prompt"] if i < len(generation) else None
            snap = memory[min(i, len(memory) - 1)] if memory else {}
            context = row["turns"][0]["reply"] if i == 1 else None
            result = (
                attribute(
                    entry.get("answerKeys") or [],
                    prompt,
                    note=str(snap.get("note") or ""),
                    summary=str(snap.get("summary") or ""),
                    recall_header=args.recall_header,
                    static_texts=statics,
                    context_response=context,
                    fact_header=args.fact_header,
                    old_keys=(entry.get("answer_key") or {}).get("reject_bundles") or [],
                )
                if prompt
                else {"unattributable": "덤프 없음"}
            )
            out.append(
                {"item": row["item"], "arm": row["arm"], "checkpoint": row["checkpoint"], "turnIndex": i, **result}
            )
    _write(args.out, out)
    print(f"{len(out)}줄 → {args.out}")
    return 0


# ---------------------------------------------------------------- 시제품 추출


def cmd_prototype_extract(args: argparse.Namespace) -> int:
    from memory_eval import prototype_extract as pe
    from memory_eval.runtime import load_room, make_engine, story_judgment_sets

    async def go() -> dict[str, Any]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                ctx = await load_room(db, args.room)
                windows = await pe.build_windows(db, args.room)
                sets = await story_judgment_sets(db)
            prompt_set = sets.summary[0]
            instruction = args.instruction_file.read_text(encoding="utf-8")
            if args.dry_run or not args.allow_paid:
                chars = [
                    len(
                        pe.build_prompt(
                            instruction, ctx.names.judgment_user_name, [], pe.render_window(w, prompt_set, ctx.names)
                        )
                    )
                    for w in windows
                ]
                return {
                    "windows": len(windows),
                    "promptChars": chars,
                    "estimateUsd": len(windows) * pe.EXTRACT_CALL_ESTIMATE_USD,
                }
            from api.core.config import settings

            book = _ledger(args)
            rows: list[dict[str, Any]] = []
            titles: list[str] = []
            for window in windows:
                prompt = pe.build_prompt(
                    instruction,
                    ctx.names.judgment_user_name,
                    titles[-2:],
                    pe.render_window(window, prompt_set, ctx.names),
                )
                result = await pe.call_haiku(
                    settings.anthropic_direct_api_key, prompt, book, stage=f"s5-{args.version}"
                )
                episodes = pe.episode_rows(window, result, version=args.version)
                rows.extend(episodes)
                titles = [e["title"] for e in episodes] or titles
            pe.write_json(args.out, rows)
            return {"windows": len(windows), "episodes": len(rows), "out": str(args.out)}
        finally:
            await engine.dispose()

    _print(asyncio.run(go()))
    return 0


def cmd_prototype_facts(args: argparse.Namespace) -> int:
    """스냅샷마다 사실 시제품 추출. 기본은 드라이런(창 수·입력 글자·견적), 실제 호출은 --allow-paid 일 때만."""
    from memory_eval import prototype_extract as pe, prototype_facts as pf
    from memory_eval.runtime import load_room, make_engine, story_judgment_sets

    async def go() -> dict[str, Any]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                ctx = await load_room(db, args.room)
                windows = await pe.build_windows(db, args.room)
                sets = await story_judgment_sets(db)
        finally:
            await engine.dispose()
        prompt_set = sets.summary[0]
        instruction = args.instruction_file.read_text(encoding="utf-8")
        user_name = ctx.names.judgment_user_name

        def render(window: pe.Window) -> str:
            return pe.render_window(window, prompt_set, ctx.names)

        if args.dry_run or not args.allow_paid:
            return {
                "windows": len(windows),
                "promptChars": [len(pf.build_prompt(instruction, user_name, [], render(w))) for w in windows],
                "estimateUsd": len(windows) * pf.FACT_CALL_ESTIMATE_USD,
                "model": args.model,
            }
        if args.out is None:
            raise SystemExit("실제 추출은 --out 이 있어야 한다")
        from api.core.config import settings

        book = _ledger(args)

        async def caller(prompt: str) -> pf.PrototypeFactResult:
            return await pf.call_haiku(
                settings.anthropic_direct_api_key, prompt, book, stage=f"facts-{args.version}", model=args.model
            )

        rows = await pf.extract_windows(
            windows, render=render, caller=caller, instruction=instruction, user_name=user_name, version=args.version
        )
        _write(args.out, rows)
        return {"windows": len(windows), "facts": len(rows), "out": str(args.out)}

    _print(asyncio.run(go()))
    return 0


def cmd_fact_metrics(args: argparse.Namespace) -> int:
    """사실 계층 오프라인 지표(보존율·중복 키·상한 탈락, 범주별). 개발 보기가 기본이다."""
    from memory_eval.facts import RENDER_MAX_CHARS, fact_metrics
    from memory_eval.prototype_facts import load_fact_rows

    splits = _splits(args)
    plant_set = _plant_view(args, splits)
    rows = load_fact_rows(args.facts)
    cps: list[int | None] = list(_ints(args.checkpoints)) if args.checkpoints else [None]
    report: dict[str, Any] = {
        "splits": sorted(splits),
        "facts": str(args.facts),
        "results": [
            fact_metrics(plant_set.all_items(), rows, checkpoint=cp, max_chars=args.max_chars or RENDER_MAX_CHARS)
            for cp in cps
        ],
    }
    _write(args.out, report)
    _print(
        [
            {"checkpoint": r["checkpoint"], "preserved": r["overall"]["preserved"]["rate"], "rows": r["rows"]}
            for r in report["results"]
        ]
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


def cmd_arm_env(args: argparse.Namespace) -> int:
    """2차 런 갈래의 측정 서버 env 줄을 출력한다(`--server-env` 파일로 쓸 수 있다)."""
    from memory_eval.arm_env import env_text

    print(env_text(args.arm, prompt_dump=args.prompt_dump), end="")
    return 0


def cmd_s8(args: argparse.Namespace) -> int:
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.verdict import s8_verdict

    require_seal({"test"}, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha)
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
    """2차 런 최종 짝 비교 ①~⑦(①·④ 시험 절반, ②·③ 전체 문항 — 봉인 확인 뒤). 결과는 `verdict.json`."""
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.verdict_v3 import v3_verdict

    require_seal({"test"}, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha)
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


def cmd_ledger(args: argparse.Namespace) -> int:
    book = _ledger(args)
    rows = book.rows()
    by_stage: dict[str, float] = {}
    for row in rows:
        by_stage[row["stage"]] = by_stage.get(row["stage"], 0.0) + ledger_mod.row_cost(row)
    _print(
        {
            "calls": len(rows),
            "totalUsd": book.total_usd(),
            "byStage": by_stage,
            "capUsd": book.cap_usd,
            "haltUsd": book.halt_usd,
        }
    )
    return 0


# ---------------------------------------------------------------- 인자


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memory_eval_cli")
    ap.add_argument("--run", type=Path, required=True, help="원자료 폴더(대본·덤프·원장·결과)")
    ap.add_argument("--cap-usd", type=float, default=ledger_mod.APPROVED_CAP_USD, help="원장 상한(넘지 않는다)")
    ap.add_argument(
        "--halt-usd", type=float, default=ledger_mod.RUN_HALT_USD, help="누적 멈춤 선(닿으면 멈추고 묻는다)"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def with_plants(p: argparse.ArgumentParser) -> None:
        p.add_argument("--plants", type=Path, required=True)
        p.add_argument("--split-dir", type=Path, help="2차 형식 분할 폴더(기본 <원자료>/split)")

    def with_splits(p: argparse.ArgumentParser) -> None:
        p.add_argument("--splits", default="dev", help="dev · test · dev,test (시험 절반은 봉인 해시가 있어야 한다)")
        p.add_argument("--seal-sha", help="이번 런 봉인 사전 등록의 sha256")

    def paid(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--allow-paid", action="store_true", help="유료 호출을 실제로 한다(사용자 승인 뒤에만)")

    p = sub.add_parser("check-script")
    with_plants(p)
    p.add_argument("--transcript", type=Path, required=True)
    p.add_argument("--seed-json", type=Path, default=DEFAULT_SEED_JSON)
    p.add_argument("--user-len", default="20,120")
    p.add_argument("--narrator-len", default="150,350")
    p.add_argument("--turns", type=int, default=300)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_check_script)

    p = sub.add_parser("split-check")
    with_plants(p)
    p.set_defaults(fn=cmd_split_check)

    p = sub.add_parser("split", help="2차 형식 심기 표를 개발/시험으로 한 번 나눈다(이미 있으면 거부)")
    p.add_argument("--plants", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, help="분할 폴더(기본 <원자료>/split)")
    p.set_defaults(fn=cmd_split)

    p = sub.add_parser("budget")
    with_plants(p)
    with_splits(p)
    p.add_argument("--arms", type=int, default=3)
    p.add_argument("--opus-turn-usd", type=float, default=0.13)
    p.add_argument("--judgment-turn-usd", type=float, default=0.003)
    p.add_argument("--extra", action="append", default=[], help="이름=달러 (여러 번)")
    p.set_defaults(fn=cmd_budget)

    p = sub.add_parser("init-work-db", help="격리 DB 를 작업 DB(실행 명령 DATABASE_URL 의 이름)로 복제")
    p.add_argument("--source", required=True)
    p.add_argument("--replace", action="store_true")
    p.set_defaults(fn=cmd_init_work_db)

    p = sub.add_parser("drop-eval-db")
    p.add_argument("--name", required=True)
    p.set_defaults(fn=cmd_drop_eval_db)

    for name, fn in (("freeze", cmd_freeze), ("restore", cmd_restore)):
        p = sub.add_parser(name)
        p.add_argument("--room", type=uuid.UUID, required=True)
        p.add_argument("--checkpoint", type=int, required=True)
        p.add_argument("--label", required=True, help="단계 이름(s4·s8) — 템플릿·덤프 이름에 들어간다")
        p.add_argument("--pg-container")
        p.add_argument("--db-user", default="postgres")
        p.add_argument("--require-episodes", action="store_true", help="에피소드가 0 이면 얼리지 않는다")
        p.set_defaults(fn=fn)

    p = sub.add_parser("fingerprint")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.set_defaults(fn=cmd_fingerprint)

    p = sub.add_parser("grant-clover")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--amount", type=int, required=True)
    p.set_defaults(fn=cmd_grant_clover)

    p = sub.add_parser("set-model")
    p.add_argument("--base", required=True)
    p.add_argument("--cookie-file", type=Path, required=True)
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--model", default="opus")
    p.set_defaults(fn=cmd_set_model)

    p = sub.add_parser("insert")
    with_plants(p)
    paid(p)
    p.add_argument("--transcript", type=Path)
    p.add_argument("--room", type=uuid.UUID)
    p.add_argument("--start", type=int, default=1, help="드라이런 계획의 시작 턴(실행은 방 턴 수 다음부터)")
    p.add_argument("--until", type=int, default=300)
    p.add_argument("--freeze-at", default="50,100,300")
    p.add_argument("--fake-llm", action="store_true")
    p.add_argument("--extract", action="store_true")
    p.add_argument(
        "--extract-facts", action="store_true", help="턴마다 사실 추출을 따라잡는다(운영 모듈, 없으면 시제품)"
    )
    p.add_argument("--facts-instruction-file", type=Path, help="시제품 사실 추출 문안(운영 모듈이 없을 때)")
    p.add_argument("--facts-version", default="v1")
    p.add_argument("--arms", default="baseline")
    p.add_argument("--trajectory-model", default="opus")
    p.add_argument("--label", default="s4")
    p.add_argument("--recall-field", help="조립 결과의 회상 칸 이름(B 갈래 궤적에 필수)")
    p.add_argument(
        "--checkpoint-stats", type=Path, help="체크포인트별 스탯 고정 파일 — 얼리기 직전에 방 스탯을 그 값으로"
    )
    p.add_argument("--recall-header", default="[지난 기억 — 참고]")
    p.add_argument("--cookie-file", type=Path)
    p.add_argument("--pg-container")
    p.add_argument("--db-user", default="postgres")
    p.set_defaults(fn=cmd_insert)

    p = sub.add_parser("trajectory")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--next-turn", type=int, required=True)
    p.add_argument("--user-text", required=True)
    p.add_argument("--arms", default="baseline")
    p.add_argument("--model", default="opus")
    p.add_argument("--label", default="point")
    p.add_argument("--recall-field")
    p.add_argument("--recall-header", default="[지난 기억 — 참고]")
    p.set_defaults(fn=cmd_trajectory)

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
    p.set_defaults(fn=cmd_recall_offline)

    p = sub.add_parser("export-episodes", help="방의 장면을 오프라인 회상 입력으로(읽기만)")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_export_episodes)

    p = sub.add_parser("export-facts", help="방의 사실 행을 fact-metrics 입력으로(읽기만)")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_export_facts)

    p = sub.add_parser("recall-parity", help="두 recall-offline 출력의 행 단위 일치")
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_recall_parity)

    p = sub.add_parser("recall-warnings", help="로그의 서버 회상 실패 경고 줄 수")
    p.add_argument("--logs", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_recall_warnings)

    p = sub.add_parser("probe")
    with_plants(p)
    with_splits(p)
    paid(p)
    p.add_argument("--checkpoint-label", help="복원할 템플릿의 단계 이름(넣기 실행의 --label, 기본 = --stage)")
    p.add_argument("--stage", required=True)
    p.add_argument("--arm", required=True, choices=["baseline", "A", "B", "A2", "B2"])
    p.add_argument("--checkpoints", default="50,100,300")
    p.add_argument("--items")
    p.add_argument("--room", type=uuid.UUID)
    p.add_argument("--cred-file", type=Path)
    p.add_argument("--cookie-file", type=Path)
    p.add_argument("--port", type=int, default=8130)
    p.add_argument("--server-env", type=Path, help="서버에 덮어 줄 KEY=VALUE 파일(모델 배정 등 — 키 값은 넣지 않는다)")
    p.add_argument("--opus-turn-usd", type=float, default=0.13)
    p.add_argument("--judgment-turn-usd", type=float, default=0.003)
    p.add_argument("--burst-limit", type=int, default=9)
    p.add_argument("--halt-base", type=int, default=56, help="불능 멈춤 기준 문항 수(갈래당)")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("latency", help="프로브 결과의 갈래별 상태 수·첫 글자 지연 p50/p95")
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_latency)

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
        "--extra-controls", type=Path, nargs="*", default=[], help="실제 응답·합성 견본 대조군(개발 절반 문항만)"
    )
    p.add_argument("--probes", type=Path, nargs="*", default=[])
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_judge)

    p = sub.add_parser("judge-summary", help="판정 결과의 종류별 합격률(unaddressed 따로)")
    p.add_argument("--judged", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_judge_summary)

    p = sub.add_parser("countdown", help="CP300 상영회 카운트다운 — 스탯·노트 본문 존재만, 갈래별")
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.add_argument("--checkpoint", type=int, default=300)
    p.add_argument("--seed-json", type=Path, default=DEFAULT_SEED_JSON)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_countdown)

    p = sub.add_parser("attribution")
    with_plants(p)
    with_splits(p)
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.add_argument("--seed-json", type=Path, default=DEFAULT_SEED_JSON)
    p.add_argument("--recall-header", default="[지난 기억 — 참고]")
    p.add_argument(
        "--fact-header", help="사실 섹션 머리글(사실을 싣는 갈래의 귀속 자리) — 운영 렌더의 머리글을 그대로 준다"
    )
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_attribution)

    p = sub.add_parser("prototype-extract")
    paid(p)
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--instruction-file", type=Path, required=True)
    p.add_argument("--version", default="v1")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_prototype_extract)

    p = sub.add_parser("prototype-facts", help="스냅샷마다 사실 시제품 추출(기본 드라이런)")
    paid(p)
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--instruction-file", type=Path, required=True)
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument("--version", default="v1")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_prototype_facts)

    p = sub.add_parser("fact-metrics", help="사실 계층 오프라인 지표(개발 보기 기본)")
    with_plants(p)
    with_splits(p)
    p.add_argument("--facts", type=Path, required=True, help="사실 행(시제품 JSON 배열 또는 넣기 따라잡기 JSONL)")
    p.add_argument("--checkpoints", help="체크포인트별로 나눠 센다(비우면 전체 행 한 번)")
    p.add_argument("--max-chars", type=int, help="렌더 상한(기본 700)")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_fact_metrics)

    p = sub.add_parser("summary-sections", help="요약 본문의 칸별 글자 수·비율")
    p.add_argument("--inputs", type=Path, nargs="+", required=True, help="memory-snapshots.jsonl 또는 요약 본문 파일")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_summary_sections)

    p = sub.add_parser("arm-env", help="2차 런 갈래(A2·B2)의 측정 서버 env 줄")
    p.add_argument("--arm", required=True, choices=["A2", "B2"])
    p.add_argument("--prompt-dump", help="PROMPT_DUMP_PATH 줄을 더한다(프로브는 폴더마다 따로 넣는다)")
    p.set_defaults(fn=cmd_arm_env)

    p = sub.add_parser("s8-verdict", help="최종 짝 비교 ①~⑤ 판정(시험 절반 — 봉인 해시 필요)")
    with_plants(p)
    p.add_argument("--seal-sha", required=True)
    p.add_argument("--scores", type=Path, nargs="+", required=True, help="score 출력(A·B 갈래)")
    p.add_argument("--judged", type=Path, nargs="*", default=[], help="judge 출력")
    p.add_argument("--offline", type=Path, required=True, help="recall-offline 출력(시험 절반)")
    p.add_argument("--trajectory", type=Path, nargs="*", default=[], help="trajectory 점(jsonl, A·B 갈래) — ⑥·⑦")
    p.add_argument("--recall-section-max", type=int, help="테스트가 계산한 회상 섹션 최대 글자 — ⑥")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_s8)

    p = sub.add_parser("v3-verdict", help="2차 런 최종 짝 비교 ①~⑦(시험 절반 — 봉인 해시 필요)")
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

    p = sub.add_parser("ledger")
    p.set_defaults(fn=cmd_ledger)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code: int = args.fn(args)
    except BudgetExceededError as stop:
        print(stop)
        return EXIT_BUDGET
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code, file=sys.stderr)
            return 2
        raise
    return code


if __name__ == "__main__":
    sys.exit(main())
