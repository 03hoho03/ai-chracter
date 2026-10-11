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
from typing import Any

from memory_eval import checkpoint, ledger as ledger_mod, plants as plants_mod
from memory_eval.ledger import EXIT_BUDGET, BudgetExceededError, Ledger
from memory_eval.seal import PREREGISTRATION_FILE, require_seal
from memory_eval.transcript import LengthRule, check_script, load_transcript, work_text_from_seed

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


# ---------------------------------------------------------------- 대본·심기 표·예산


def cmd_check_script(args: argparse.Namespace) -> int:
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
    plant_set = plants_mod.load_plants(args.plants)
    _print([plants_mod.split_agreement(plant_set, rule=rule) for rule in ("category", "role")])
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    plant_set = plants_mod.load_plants(args.plants)
    extras = {name: float(value) for name, value in (e.split("=") for e in args.extra)}
    estimate = ledger_mod.budget_estimate(
        plant_set,
        arms=args.arms,
        opus_turn_usd=args.opus_turn_usd,
        server_judgment_turn_usd=args.judgment_turn_usd,
        extras=extras,
        cap_usd=args.cap,
    )
    estimate["ledgerSpentUsd"] = Ledger(args.run / "ledger.jsonl", cap_usd=args.cap).total_usd()
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

    plant_set = plants_mod.load_plants(args.plants)
    freeze_at = _ints(args.freeze_at)
    if args.dry_run:
        report = insert.plan(
            plant_set, start_turn=args.start, until_turn=args.until, freeze_at=freeze_at, extract=args.extract
        )
        report["ledgerSpentUsd"] = Ledger(args.run / "ledger.jsonl").total_usd()
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
            Ledger(args.run / "ledger.jsonl"),
            stage=args.label,
            per_call_estimate_usd=insert.FOLD_CALL_ESTIMATE_USD,
        )
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
        )
    )
    _print(result)
    return 0


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
    plant_set = plants_mod.load_plants(args.plants)
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


# ---------------------------------------------------------------- 프로브·채점


def cmd_probe(args: argparse.Namespace) -> int:
    from memory_eval import probe as probe_mod

    plant_set = plants_mod.load_plants(args.plants)
    cps = _ints(args.checkpoints)
    items = set(args.items.split(",")) if args.items else None
    probes = [p for cp in cps for p in plants_mod.opus_probes(plant_set, cp) if items is None or p.item_id in items]
    book = Ledger(args.run / "ledger.jsonl")
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
    return 0


def _probe_rows(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def cmd_score(args: argparse.Namespace) -> int:
    from memory_eval.judge import deterministic

    splits = _splits(args)
    from memory_eval.judge import ensure_unique_probe_rows

    plant_set = plants_mod.load_plants(args.plants)
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

    plant_set = plants_mod.load_plants(args.plants)
    controls_path = args.run / "judge" / "controls.json"
    if args.controls:
        items = judge_mod.controls(plant_set)
        for path in args.extra_controls:
            items += judge_mod.load_extra_controls(path, plant_set)
    else:
        splits = _splits(args)
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

    judge = judge_mod.HaikuJudge(settings.anthropic_direct_api_key, Ledger(args.run / "ledger.jsonl"), stage="judge")

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
        accuracy = sum(1 for r in judged if r["judged"] == r["expected"]) / len(results) if results else 0.0
        _write(controls_path, {"passed": judge_mod.controls_pass(results), "accuracy": accuracy, "rows": results})
    else:
        _write(args.out, results)
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
    plant_set = plants_mod.load_plants(args.plants)
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

            book = Ledger(args.run / "ledger.jsonl")
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


def cmd_s8(args: argparse.Namespace) -> int:
    from memory_eval.judge import ensure_unique_probe_rows
    from memory_eval.verdict import s8_verdict

    require_seal({"test"}, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha)
    plant_set = plants_mod.load_plants(args.plants)
    scores = [r for path in args.scores for r in json.loads(path.read_text(encoding="utf-8"))]
    ensure_unique_probe_rows(scores)
    judge_rows = [r for path in args.judged for r in json.loads(path.read_text(encoding="utf-8"))]
    offline = json.loads(args.offline.read_text(encoding="utf-8"))["rows"]
    result = s8_verdict(plant_set, scores, judge_rows=judge_rows, offline_rows=offline)
    _write(args.out, result)
    _print({k: result[k].get("pass") for k in ("1", "2", "3", "4", "5")} | {"allPass": result["allPass"]})
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    book = Ledger(args.run / "ledger.jsonl")
    rows = book.rows()
    by_stage: dict[str, float] = {}
    for row in rows:
        by_stage[row["stage"]] = by_stage.get(row["stage"], 0.0) + ledger_mod.row_cost(row)
    _print({"calls": len(rows), "totalUsd": book.total_usd(), "byStage": by_stage, "capUsd": book.cap_usd})
    return 0


# ---------------------------------------------------------------- 인자


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memory_eval_cli")
    ap.add_argument("--run", type=Path, required=True, help="원자료 폴더(대본·덤프·원장·결과)")
    sub = ap.add_subparsers(dest="command", required=True)

    def with_plants(p: argparse.ArgumentParser) -> None:
        p.add_argument("--plants", type=Path, required=True)

    def with_splits(p: argparse.ArgumentParser) -> None:
        p.add_argument("--splits", default="dev", help="dev · test · dev,test (시험 절반은 봉인 해시가 있어야 한다)")
        p.add_argument("--seal-sha", help="v2 봉인 사전 등록의 sha256")

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

    p = sub.add_parser("budget")
    with_plants(p)
    p.add_argument("--arms", type=int, default=3)
    p.add_argument("--opus-turn-usd", type=float, default=0.13)
    p.add_argument("--judgment-turn-usd", type=float, default=0.003)
    p.add_argument("--extra", action="append", default=[], help="이름=달러 (여러 번)")
    p.add_argument("--cap", type=float, default=ledger_mod.APPROVED_CAP_USD)
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

    p = sub.add_parser("probe")
    with_plants(p)
    paid(p)
    p.add_argument("--checkpoint-label", help="복원할 템플릿의 단계 이름(넣기 실행의 --label, 기본 = --stage)")
    p.add_argument("--stage", required=True)
    p.add_argument("--arm", required=True, choices=["baseline", "A", "B"])
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
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_attribution)

    p = sub.add_parser("prototype-extract")
    paid(p)
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--instruction-file", type=Path, required=True)
    p.add_argument("--version", default="v1")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_prototype_extract)

    p = sub.add_parser("s8-verdict", help="최종 짝 비교 ①~⑤ 판정(시험 절반 — 봉인 해시 필요)")
    with_plants(p)
    p.add_argument("--seal-sha", required=True)
    p.add_argument("--scores", type=Path, nargs="+", required=True, help="score 출력(A·B 갈래)")
    p.add_argument("--judged", type=Path, nargs="*", default=[], help="judge 출력")
    p.add_argument("--offline", type=Path, required=True, help="recall-offline 출력(시험 절반)")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_s8)

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
