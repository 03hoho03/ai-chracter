"""측정 하네스 CLI 의 인프라 하위 명령 — 대본·심기 표·견적, 작업 DB·체크포인트, 투입·궤적, 임베딩 채우기, 프로브, 원장.

판정·집계 모듈을 import 하지 않는다. 판정 하위 명령은 따로 묶음 모듈을 두고 같은 진입점(`memory_eval_cli.py`)에 등록한다."""

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memory_eval import checkpoint, holdout, ledger as ledger_mod, plants as plants_mod, workers
from memory_eval.arm_env import BUNDLE1_ARMS
from memory_eval.ledger import Ledger
from memory_eval.cli_common import (
    DEFAULT_SEED_JSON,
    _db_url,
    _hybrid_args,
    _hybrid_params,
    _ints,
    _ledger,
    _paid,
    _plant_view,
    _print,
    _probe_rows,
    _range,
    _refuse_v2,
    _replay_embedding_args,
    _replay_embeddings,
    _splits,
    _write,
    data_file,
    paid,
    update_status,
    with_plants,
    with_splits,
)
from memory_eval.transcript import LengthRule, check_script, load_transcript, work_text_from_seed

if TYPE_CHECKING:
    from api.llm.client import LLMClient

    from memory_eval.fact_catchup import FactCatchUp


def _embedding_catch_up(args: argparse.Namespace) -> Any:
    """임베딩 따라잡기 — 운영 채우기 함수를 가짜 실행이면 네트워크 없는 흉내 클라이언트로, 유료 실행이면 원장에 적는 Voyage
    클라이언트로 부른다."""
    from memory_eval.embed_catchup import EmbeddingCatchUp, LedgerVoyageClient, fake_embedding_client

    if not args.embed_model or not args.embed_dims:
        raise SystemExit("임베딩 채우기는 --embed-model 과 --embed-dims 를 함께 준다")
    if args.fake_llm:
        return EmbeddingCatchUp(fake_embedding_client(model=args.embed_model, dims=args.embed_dims))
    from api.core.config import settings

    if not settings.voyage_api_key.strip():
        raise SystemExit("임베딩 채우기 유료 실행은 VOYAGE_API_KEY 가 있어야 한다")
    client = LedgerVoyageClient(
        api_key=settings.voyage_api_key,
        model=args.embed_model,
        dims=args.embed_dims,
        ledger=_ledger(args),
        stage=f"{args.label}-embed",
    )
    return EmbeddingCatchUp(client)


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


def cmd_split_bundle(args: argparse.Namespace) -> int:
    """대본 셋을 시드 파일의 층별 시드로 한꺼번에 나눈다. 표준출력은 층별 개수·합계 판정(·작품별 시험 정답 해시)뿐이다."""
    from memory_eval import bundle_split

    if args.dry_run:
        plan = bundle_split.plan_bundle(args.config)
        _print({"counts": plan["counts"], "totals": plan["totals"]})
        return 0 if plan["ok"] else 1
    result = bundle_split.write_bundle(args.config, args.out_root or args.run / holdout.SPLIT_DIR)
    _print({k: result[k] for k in ("counts", "totals", "testKeysSha256")})
    if not result["ok"]:
        print("시험 합계 하한을 못 채운 항목이 있어 어떤 작품의 분할 파일도 쓰지 않았다", file=sys.stderr)
        return 1
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    if args.cap_usd is None:
        raise SystemExit("견적은 묶음 상한(--cap-usd)을 명시해야 여유를 계산한다")
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
    book = _ledger(args)
    estimate["ledgerSpentUsd"] = book.total_usd()
    estimate["bundle"] = args.bundle
    estimate["bundleSpentUsd"] = book.bundle_usd()
    estimate["haltUsd"] = args.halt_usd
    _print(estimate)
    return 0


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


def cmd_ending_stats(args: argparse.Namespace) -> int:
    """엔딩 층 — 작업 DB 의 방 스탯을 파일 값(`{"<스탯 이름>": 값, …}`)으로 맞춘다. 엔딩에 닿는 값을 받는다."""
    from memory_eval.ending_stats import apply_ending_stats
    from memory_eval.runtime import make_engine

    url = _db_url(writes=True)
    values = json.loads(args.stats.read_text(encoding="utf-8"))

    async def run() -> dict[str, Any]:
        engine, factory = make_engine(url)
        try:
            async with factory() as db:
                return await apply_ending_stats(db, args.room, values)
        finally:
            await engine.dispose()

    _print(asyncio.run(run()))
    return 0


def cmd_media_book(args: argparse.Namespace) -> int:
    """합성 미디어 북을 작업 DB 에 있는 작품의 현재 발행 버전에 넣는다. 방은 만들 때 버전을 고정하므로 방보다 먼저 돌린다.
    작품을 주지 않으면 튜토리얼 스토리다."""
    from seed_content.upsert import story_content_id

    from api.db.models import Content
    from memory_eval.media_book import SPEC_FILE, insert_media_book, load_spec
    from memory_eval.runtime import make_engine

    spec = load_spec(args.spec or data_file(args, SPEC_FILE))
    url = _db_url(writes=True)
    content_id = args.content_id or story_content_id("tutorial-filmclub")

    async def run() -> dict[str, Any]:
        engine, factory = make_engine(url)
        try:
            async with factory() as db:
                content = await db.get(Content, content_id)
                if content is None or content.current_published_version_id is None:
                    raise SystemExit(f"발행 버전이 있는 작품이 아니다: {content_id}")
                report = await insert_media_book(
                    db, content.current_published_version_id, content.creator_user_id, spec
                )
                await db.commit()
                return {"contentId": str(content_id), "versionId": str(content.current_published_version_id), **report}
        finally:
            await engine.dispose()

    _print(asyncio.run(run()))
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


def cmd_consent(args: argparse.Namespace) -> int:
    """측정 작업 DB 회원의 약관 동의를 현행판으로 맞춘다(방 만들기·모델 바꾸기처럼 재동의 게이트가 걸린 HTTP 단계 전에).
    `--room` 을 주면 그 방 주인만, 아니면 탈퇴하지 않은 회원 전원. 프로브는 복원할 때마다 방 주인에게 스스로 부른다."""
    from api.db.models import ChatRoom
    from memory_eval.room import ensure_current_consent
    from memory_eval.runtime import make_engine

    url = _db_url(writes=True)

    async def run() -> dict[str, list[str]]:
        engine, factory = make_engine(url)
        try:
            async with factory() as db:
                user_ids = None
                if args.room is not None:
                    room = await db.get(ChatRoom, args.room)
                    if room is None:
                        raise SystemExit(f"방이 없다: {args.room}")
                    user_ids = [room.user_id]
                updated = await ensure_current_consent(db, user_ids)
                await db.commit()
                return updated
        finally:
            await engine.dispose()

    _print({"updated": asyncio.run(run())})
    return 0


def cmd_set_model(args: argparse.Namespace) -> int:
    from memory_eval.room import set_room_model

    _print(set_room_model(args.base, args.cookie_file.read_text(encoding="utf-8").strip(), args.room, args.model))
    return 0


def cmd_insert(args: argparse.Namespace) -> int:
    from memory_eval import insert
    from memory_eval.pinned_stats import load_pinned_doc
    from memory_eval.two_series import BSeries, summaries_path

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
            b_series=args.b_series,
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
    embeddings = _embedding_catch_up(args) if args.fill_embeddings else None
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
            b_series=BSeries(summaries_path(args.run, args.label)) if args.b_series else None,
            embeddings=embeddings,
        )
    )
    _print(result)
    return 0


def cmd_trajectory(args: argparse.Namespace) -> int:
    from memory_eval.offline_embedding import recall_settings
    from memory_eval.runtime import make_engine
    from memory_eval.trajectory import append_point, assemble_point
    from memory_eval.trajectory_replay import require_query_embedded

    embeddings = _replay_embeddings(args, args.arms.split(","))

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
                        embeddings=embeddings,
                    )
                # 임베딩 회상 갈래가 명사 단독으로 조립된 점은 쓰기 전에 끊는다(재조립 명령과 같은 단언).
                require_query_embedded([point])
                append_point(args.run / f"trajectory-{args.label}-{arm}.jsonl", point)
                points.append(point)
        finally:
            await engine.dispose()
        return points

    with recall_settings(_hybrid_params(args)):
        _print(asyncio.run(go()))
    return 0


def cmd_trajectory_replay(args: argparse.Namespace) -> int:
    """얼린 체크포인트에서 지난 턴들의 생성 프롬프트를 그때 상태로 갈래마다 다시 조립해 궤적 점을 쓴다(LLM 없음, 읽기만).
    기준 궤적을 주면 표본 턴을 기준 갈래(설정 덮어쓰기 없음)로 다시 조립해 넣기 때 기록과 견주고, 어긋나면 갈래 점을 쓰지 않고
    멈춘다. 임베딩 회상 갈래에서 질의 임베딩이 `ok` 가 아닌 점이 하나라도 있으면 궤적을 쓰지 않고 멈춘다.

    `--label`·`--checkpoint` 를 주면 갈래마다 자기 계열의 템플릿 DB(A 계열은 그 단계 이름, B 계열은 꼬리를 붙인 이름)를 열고, 열기
    전에 지문 파일과 견준다(B 계열은 요약 글 해시 포함). B 계열 갈래는 대화 기록 뒤 섹션을 끈 자기 재렌더 점(`-bare`)도 함께
    만들고 그 앞 두 블록 비교를 낸다. 주지 않으면 지금 작업 DB 하나에서 조립하므로 B 계열 갈래를 거부한다."""
    from sqlalchemy.engine import make_url

    from memory_eval import trajectory_replay as tr
    from memory_eval.arm_env import BUNDLE1_ARMS, series_label, template_series
    from memory_eval.offline_embedding import recall_settings
    from memory_eval.runtime import generation_set, load_room, make_engine

    arms = args.arms.split(",")
    b_series = [arm for arm in arms if arm in BUNDLE1_ARMS and template_series(arm) == "B"]
    if b_series and not args.label:
        raise SystemExit(
            f"B 계열 갈래 {b_series} 는 --label(A 계열 템플릿을 얼린 넣기의 단계 이름)과 --checkpoint 를 줘야 자기 계열 "
            "템플릿에서 조립한다 — 지금 작업 DB 에서 조립하면 A 요약 위에서 조립된다"
        )
    if args.label and args.checkpoint is None:
        raise SystemExit("--label 을 주면 --checkpoint(조립할 템플릿의 체크포인트)도 준다")
    built_arms = arms + [tr.bare_arm(arm) for arm in b_series]
    embeddings = _replay_embeddings(args, built_arms)
    if args.embed_plan_out and embeddings is None:
        raise SystemExit("--embed-plan-out 은 임베딩 회상 갈래가 있을 때만 쓴다")
    # 계획 모드: 빠진 질의 글을 모으기만 하고 궤적 점은 쓰지 않는다.
    missing: list[dict[str, str]] | None = [] if args.embed_plan_out else None
    counts = tr.snapshot_counts(
        [json.loads(line) for line in args.insert_log.read_text(encoding="utf-8").splitlines() if line]
    )
    recorded = (
        {
            int(p["turn"]): p
            for p in (json.loads(x) for x in args.baseline.read_text(encoding="utf-8").splitlines() if x)
        }
        if args.baseline
        else {}
    )
    low, high = _range(args.turns)
    work_url = _db_url(writes=False)
    if args.label:
        groups = tr.arms_by_series(built_arms)
        if recorded:
            groups.setdefault("A", [])
    else:
        groups = {"work": built_arms}

    async def build_group(series: str, group: list[str]) -> tuple[dict[int, Any], dict[str, list[dict[str, Any]]]]:
        url = work_url
        if series != "work":
            probe_arm = group[0] if group else "baseline"
            name = tr.replay_template(args.checkpoint, args.label, probe_arm)
            url = make_url(work_url).set(database=name).render_as_string(hide_password=False)
        engine, factory = make_engine(url)
        try:
            async with factory() as db:
                ctx = await load_room(db, args.room)
                if series != "work":
                    label = args.label if series == "A" else series_label(args.label, b_series[0])
                    expected = json.loads(
                        checkpoint.fingerprint_path(args.run / "dumps", args.checkpoint, label).read_text(
                            encoding="utf-8"
                        )
                    )
                    conn = await db.connection()
                    digest = await checkpoint.compute_summary_digest(conn, args.room) if series == "B" else None
                    tr.check_template(expected, await checkpoint.compute_fingerprint(conn, args.room), digest=digest)
                timeline = await tr.load_timeline(db, ctx)
                persona = await tr.injected_persona(db, ctx)
                prompt_set = await generation_set(db, args.model, lane=ctx.lane)
                headers = {
                    "recall_header": tr.section_header(prompt_set[1], "memory_recall"),
                    "fact_header": tr.section_header(prompt_set[1], "memory_facts"),
                }

                async def point(turn: int, arm: str) -> dict[str, Any]:
                    built, _ = await tr.replay_point(
                        db, ctx, timeline, turn=turn, counts=counts, arm=arm, prompt_set=prompt_set,
                        persona=persona, embeddings=embeddings, missing=missing, **headers,
                    )  # fmt: skip
                    return built

                compared: dict[int, Any] = {}
                if series in ("A", "work"):
                    sample = [t for t in _ints(args.compare_turns) if t in recorded]
                    compared = {t: tr.point_diff(recorded[t], await point(t, "baseline")) for t in sample}
                    if any(compared.values()):
                        return compared, {}
                return compared, {arm: [await point(t, arm) for t in range(low, high + 1)] for arm in group}
        finally:
            await engine.dispose()

    async def go() -> dict[str, Any]:
        compared: dict[int, Any] = {}
        points: dict[str, list[dict[str, Any]]] = {}
        for series in sorted(groups, key=lambda s: s != "A" and s != "work"):
            seen, built = await build_group(series, groups[series])
            compared |= seen
            if any(seen.values()):
                return {"baselineCompare": compared, "halted": "기준 궤적과 다르다 — 재구성 규칙을 확인한다"}
            points |= built
        if missing is not None:
            args.embed_plan_out.parent.mkdir(parents=True, exist_ok=True)
            args.embed_plan_out.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in missing), encoding="utf-8"
            )
            return {"embedPlan": str(args.embed_plan_out), "missingQueries": len(missing), "trajectoryWritten": False}
        flat = [p for rows in points.values() for p in rows]
        # 명사 단독으로 조립된 임베딩 회상 궤적은 쓰기 전에 끊는다(나중 판정이 무효 궤적을 읽지 않게).
        query_check = tr.require_query_embedded(flat)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for arm, rows in points.items():
            (args.out_dir / f"trajectory-{arm}.jsonl").write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
            )
        summary: dict[str, Any] = {"baselineCompare": compared, "turns": [low, high], "queryEmbedded": query_check}
        if recorded:
            summary["recordedMismatch"] = {
                arm: [p["turn"] for p in rows if p["turn"] in recorded and tr.point_diff(recorded[p["turn"]], p)]
                for arm, rows in points.items()
                if tr.arm_series(arm) == "A"
            }
        if b_series:
            summary["selfRender"] = tr.self_render_checks(flat)
        replay_checks = getattr(args, "replay_checks", None)
        if replay_checks is not None and len(arms) == 2:
            # 다른 묶음이 덧붙인 앞 두 캐시 블록·길이 판정 요약 — 두 갈래를 견줄 때만.
            summary["checks"] = replay_checks(args, flat, (arms[0], arms[1]))
        return summary

    with recall_settings(_hybrid_params(args)):
        _print(asyncio.run(go()))
    return 0


def cmd_embed_run(args: argparse.Namespace) -> int:
    """`embed-plan` 글 목록을 한 후보로 임베딩해 벡터 파일에 덧붙인다. 벡터 파일에 이미 있는 글은 건너뛴다. `--allow-paid`
    없이는 견적만 낸다(키·HTTP 클라이언트 없음)."""
    from memory_eval import embed_api as ea
    from memory_eval.embed_offline import EmbeddingTable

    candidate = ea.Candidate.parse(args.candidate)
    table = (
        EmbeddingTable.load(args.embeddings, model=candidate.model, dims=candidate.dims)
        if args.embeddings.exists()
        else EmbeddingTable(model=candidate.model, dims=candidate.dims, vectors={})
    )
    rows = [r for r in ea.read_plan(args.plan) if (r["inputType"], r["sha256"]) not in table.vectors]
    if not _paid(args):
        _print(ea.estimate(rows, candidate, ledger_rows=Ledger(args.run / "ledger.jsonl").rows()))
        return 0
    ledger = _ledger(args)
    embedder = ea.make_embedder(candidate)
    _print(ea.embed_rows(rows, embedder, ledger=ledger, out=args.embeddings, stage=args.stage))
    return 0


def cmd_series_template(args: argparse.Namespace) -> int:
    """B 계열 템플릿을 만든다 — A 계열 체크포인트 템플릿을 복제하고 스냅샷 요약 글만 B 판으로 갈아 끼운다. 템플릿을 복제하므로
    서버와 드라이버를 먼저 내린다."""
    from memory_eval import series_template as st

    result = asyncio.run(
        st.derive_b_templates(
            _db_url(writes=True),
            room_id=args.room,
            base_label=args.label,
            checkpoints=_ints(args.checkpoints),
            summaries=st.load_summaries(args.summaries),
            dumps_dir=args.run / "dumps",
            container=args.pg_container,
            db_user=args.db_user,
        )
    )
    _print(result)
    return 0


def cmd_export_episodes(args: argparse.Namespace) -> int:
    """방의 장면을 오프라인 회상 입력(JSON)으로 — 명사는 저장된 값, 검색 대상이 되는 첫 턴은 스냅샷 커서로 계산. 읽기만."""
    from memory_eval.runtime import make_engine
    from memory_eval.server_recall import export_episode_vectors, export_episodes

    async def go() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                vectors = await export_episode_vectors(db, args.room) if args.vectors_out else []
                return await export_episodes(db, args.room), vectors
        finally:
            await engine.dispose()

    rows, vectors = asyncio.run(go())
    _write(args.out, rows)
    print(f"장면 {len(rows)}개 → {args.out}")
    if args.vectors_out:
        args.vectors_out.parent.mkdir(parents=True, exist_ok=True)
        args.vectors_out.write_text("".join(json.dumps(v) + "\n" for v in vectors), encoding="utf-8")
        print(f"저장된 장면 벡터 {len(vectors)}줄 → {args.vectors_out}")
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


def cmd_injection_warnings(args: argparse.Namespace) -> int:
    """프로브 결과 파일들의 시도 서버 로그에서 사실·회상 주입 실패 경고 줄 수, 갈래별."""
    from memory_eval.probe import injection_warnings_by_arm

    _print(injection_warnings_by_arm(_probe_rows(args.probes)))
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    from memory_eval import probe as probe_mod

    from memory_eval.arm_env import bundle1_env_pairs, require_lane_arm, series_label

    # 같은 프로브가 큐에 두 번 들면 두 작업자가 같은 시도 폴더를 쓴다 — 한쪽이 다시 돌며 옆으로 옮기는 지난 폴더가 다른 쪽이 쓰는
    # 폴더다. 계획 전에 거부한다.
    for flag, raw in (("--checkpoints", args.checkpoints), ("--items", args.items or "")):
        values = [v.strip() for v in raw.split(",") if v.strip()]
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise SystemExit(f"{flag} 에 중복된 값이 있다: {repeated}")
    plant_set = _plant_view(args, _splits(args))
    bundle1 = args.arm in BUNDLE1_ARMS
    if bundle1:
        require_lane_arm(args.arm, plant_set.raw.get("lane"))
    cps = _ints(args.checkpoints)
    items = set(args.items.split(",")) if args.items else None
    for item_id in sorted(items or ()):
        plant_set.item(item_id)  # 숨긴 시험 문항이면 거부, 없는 문항이면 KeyError
    planned = [p for cp in cps for p in plants_mod.opus_probes(plant_set, cp)]
    plan_filter = getattr(args, "plan_filter", None)
    if plan_filter is not None:
        # 다른 묶음이 덧붙인 문항 거르기(판정 종류) — 거른 문항이 이번 실행의 계획이고, 멈춤 기준도 그 계획으로 센다.
        planned = [p for p in planned if plan_filter(args, plant_set.item(p.item_id))]
    # 불능 멈춤의 기준은 이번 실행이 사전 등록 문항으로 계획한 프로브 전체(일부 문항만 다시 돌려도 같다). 앞 측정의 문항 수가
    # 기본값으로 남으면 문항 수가 다른 측정에서 멈춤 선이 조용히 어긋나므로, 명시한 기준이 계획과 다르면 거부한다.
    halt_base = len(planned)
    if args.halt_base is not None and args.halt_base != halt_base:
        raise SystemExit(f"불능 멈춤 기준 {args.halt_base} 가 계획한 프로브 수 {halt_base} 와 다르다")
    probes = [p for p in planned if items is None or p.item_id in items]
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
                "haltBase": halt_base,
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
    elif bundle1:
        if not args.embed_model or not args.embed_dims:
            raise SystemExit("묶음 1 갈래는 --embed-model 과 --embed-dims 를 줘야 한다(서버 env 의 임베딩 모델·차원)")
        overrides.update(
            dict(
                bundle1_env_pairs(
                    args.arm,
                    lane=str(plant_set.raw["lane"]),
                    embed_model=args.embed_model,
                    embed_dims=args.embed_dims,
                    recall=_hybrid_params(args),
                    embed_timeout_ms=args.memory_embed_recall_timeout_ms,
                )
            )
        )
    else:
        from memory_eval.arm_env import ARM_ENV, env_pairs

        if args.arm in ARM_ENV:
            # 2차 런 갈래는 env 표를 그대로 쓴다 — 파일을 손으로 옮기다 공통 줄이 갈래마다 갈리지 않게.
            overrides.update(dict(env_pairs(args.arm)))
    from memory_eval import server
    from memory_eval.runtime import require_arm_supported

    require_arm_supported(args.arm)
    if bundle1:
        from memory_eval.arm_env import leaked_embed_keys

        env_path = server.API_DIR / ".env"
        env_file = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        leaked = leaked_embed_keys(overrides, env_file=env_file, environ=os.environ)
        if leaked:
            raise SystemExit(
                f"측정 서버 env 가 정하지 않은 임베딩 설정 {leaked} 가 .env·실행 환경에 있다 — 서버가 그 값을 읽어 갈래 설정이 "
                "바뀐다(df 상한 '없음'은 env 로 쓸 수 없어 줄을 뺀다). .env 에서 그 줄을 지우고 다시"
            )
    from api.core.config import settings

    if args.room is None or args.cred_file is None or args.cookie_file is None:
        raise SystemExit("프로브는 --room·--cred-file·--cookie-file 을 줘야 돈다")
    slots = workers.worker_slots(
        args.workers,
        base_port=args.port,
        database_url=_db_url(writes=True),
        redis_url=settings.redis_url,
        redis_db_base=args.redis_db_base,
        cookie_file=args.cookie_file,
    )
    busy = [slot.port for slot in slots if server.port_in_use(slot.port)]
    if busy:
        raise SystemExit(f"작업자 포트 {busy} 에 이미 서버가 있다")
    trees = server.harness_trees(server.API_DIR)
    own_ports = {slot.port for slot in slots}

    def no_other_servers() -> None:
        # 이 실행의 작업자 서버(이 트리·작업자 포트)는 통과시키고, 같은 자원을 쓰는 트리의 다른 서버는 거부한다. 작업자가 서버를
        # 띄우기 직전마다 다시 본다 — 실행 중에 다른 측정 서버가 뜰 수 있다.
        others = server.conflicting_servers(
            server.running_api_servers(), trees, own_pids=set(), own_ports=own_ports, own_tree=str(server.API_DIR)
        )
        if others:
            raise SystemExit(f"같은 격리 Redis·DB 를 쓰는 다른 API 서버가 떠 있다 — 내린 뒤 다시: {others}")

    no_other_servers()
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
        # 묶음 1 갈래는 자기 템플릿 계열의 단계 이름으로 복원한다(요약 표기 갈래는 B 계열 템플릿).
        checkpoint_label=(
            series_label(args.checkpoint_label or args.stage, args.arm)
            if bundle1
            else args.checkpoint_label or args.stage
        ),
        clone_lock=args.run / "clone.lock",
        before_start=no_other_servers,
    )
    counts = {"unprobeable": unprobeable, "halted": False}

    def on_result(result: dict[str, Any]) -> bool:
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        print(f"{result['item']} cp{result['checkpoint']}: {result['status']}", flush=True)
        counts["unprobeable"] += result["status"] == "unprobeable"
        if probe_mod.should_halt(int(counts["unprobeable"]), halt_base):
            counts["halted"] = True
        return bool(counts["halted"])

    def progress(states: list[dict[str, Any]]) -> None:
        if args.status_dir is not None:
            update_status(args.status_dir, {"workers": states})

    outcome = workers.run_parallel(
        run,
        probes,
        slots,
        on_result=on_result,
        progress=progress,
        failures_file=args.run / "probes" / f"{args.stage}-{args.arm}.failures.jsonl",
    )
    if out.exists():
        _print(probe_mod.probe_summary(_probe_rows([out])))
    if counts["halted"]:
        raise SystemExit(f"프로브 불능 {counts['unprobeable']}건 — 멈추고 묻는다")
    if outcome.budget_stop is not None:
        raise outcome.budget_stop
    if outcome.failures:
        raise SystemExit(
            f"작업 단위 {len(outcome.failures)}건 실패(남은 단위 {outcome.remaining}) — "
            f"{args.stage}-{args.arm}.failures.jsonl 을 보고 다시 돌리면 결과 파일에 없는 단위만 돈다"
        )
    return 0


def cmd_latency(args: argparse.Namespace) -> int:
    """프로브 결과 파일들의 갈래별 상태 수와 첫 글자 지연 p50·p95."""
    from memory_eval.probe import probe_summary

    _print(probe_summary(_probe_rows(args.probes)))
    return 0


def cmd_attribution(args: argparse.Namespace) -> int:
    from memory_eval.attribution import attribute, secret_covariates, window_layout
    from memory_eval.runtime import generation_set, load_room, make_engine
    from memory_eval.transcript import work_text_from_seed as seed_text

    async def load_layout() -> Any:
        # 원문 창의 경계는 그 방 레인의 생성 세트에서 읽는다 — 서버가 대화 기록 뒤에 잇는 섹션 순서가 거기 있다.
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                ctx = await load_room(db, args.room)
                prompt_set, sections = await generation_set(db, args.model, lane=ctx.lane)
        finally:
            await engine.dispose()
        assistant = prompt_set.story_assistant_label if ctx.lane == "story" else prompt_set.character_assistant_label
        return window_layout(sections, scope=ctx.lane, user_label=prompt_set.user_label, assistant_label=assistant)

    layout = asyncio.run(load_layout())
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
        answer_key = entry.get("answer_key") or {}
        # 비밀 문항은 정답 묶음이 없다 — 비밀 묶음의 자리를 따로 귀속하고, 질문 턴(마지막 턴)에 섹션별 공변량을 낸다.
        leak_keys = (answer_key.get("leak_bundles") or []) if entry.get("category") == "secret" else []
        last = len(row["turns"]) - 1
        for i in range(len(row["turns"])):
            prompt = generation[i]["prompt"] if i < len(generation) else None
            snap = memory[min(i, len(memory) - 1)] if memory else {}
            context = row["turns"][0]["reply"] if i == 1 else None
            summary = str(snap.get("summary") or "")
            result: dict[str, Any] = (
                attribute(
                    entry.get("answerKeys") or [],
                    prompt,
                    note=str(snap.get("note") or ""),
                    summary=summary,
                    recall_header=args.recall_header,
                    static_texts=statics,
                    context_response=context,
                    fact_header=args.fact_header,
                    old_keys=answer_key.get("reject_bundles") or [],
                    leak_keys=leak_keys,
                )
                if prompt
                else {"unattributable": "덤프 없음"}
            )
            if prompt and leak_keys and i == last:
                result["secretCovariates"] = secret_covariates(
                    prompt,
                    summary=summary,
                    recall_header=args.recall_header,
                    fact_header=args.fact_header,
                    layout=layout,
                    user_message=row["turns"][i]["user"],
                    leak_keys=leak_keys,
                    owner=str(entry.get("secretOwner") or ""),
                )
            out.append(
                {"item": row["item"], "arm": row["arm"], "checkpoint": row["checkpoint"], "turnIndex": i, **result}
            )
    _write(args.out, out)
    print(f"{len(out)}줄 → {args.out}")
    return 0


def cmd_prototype_facts(args: argparse.Namespace) -> int:
    """스냅샷마다 사실 시제품 추출. 기본은 드라이런(창 수·입력 글자·견적), 실제 호출은 --allow-paid 일 때만."""
    from memory_eval import prototype_extract as pe, prototype_facts as pf
    from memory_eval.runtime import judgment_sets, load_room, make_engine

    async def go() -> dict[str, Any]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            async with factory() as db:
                ctx = await load_room(db, args.room)
                windows = await pe.build_windows(db, args.room)
                sets = await judgment_sets(db, lane=ctx.lane)
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
        per_window = [sum(1 for r in rows if r["snapshot_id"] == str(w.snapshot_id)) for w in windows]
        return {
            "windows": len(windows),
            "facts": len(rows),
            "emptyWindows": per_window.count(0),
            "perWindow": per_window,
            "out": str(args.out),
        }

    _print(asyncio.run(go()))
    return 0


def cmd_fact_metrics(args: argparse.Namespace) -> int:
    """사실 계층 오프라인 지표(보존율·중복 키·상한 탈락, 범주별). 개발 보기가 기본이다."""
    from memory_eval.facts import RENDER_MAX_CHARS, alias_user, fact_metrics
    from memory_eval.prototype_facts import load_fact_rows

    splits = _splits(args)
    if args.dev_rows and splits != {"dev"}:
        raise SystemExit("--dev-rows 는 개발 보기에서만 쓴다(시험 항목의 행을 내지 않게)")
    plant_set = _plant_view(args, splits)
    rows = alias_user(load_fact_rows(args.facts), args.user_name)
    cps: list[int | None] = list(_ints(args.checkpoints)) if args.checkpoints else [None]
    report: dict[str, Any] = {
        "splits": sorted(splits),
        "facts": str(args.facts),
        "results": [
            fact_metrics(
                plant_set.all_items(),
                rows,
                checkpoint=cp,
                max_chars=args.max_chars or RENDER_MAX_CHARS,
                with_rows=args.dev_rows,
            )
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


def cmd_arm_env(args: argparse.Namespace) -> int:
    """2차 런 갈래의 측정 서버 env 줄을 출력한다(`--server-env` 파일로 쓸 수 있다)."""
    from memory_eval.arm_env import env_text

    print(env_text(args.arm, prompt_dump=args.prompt_dump), end="")
    return 0


def cmd_filter_recompute(args: argparse.Namespace) -> int:
    """프로브 결과 줄마다 질문 턴의 지식 범위 필터를 서버 함수로 다시 계산한다(LLM 없음, 템플릿 DB 읽기만). 프로브는 그 갈래 계열의
    체크포인트 템플릿에서 보냈으므로 같은 템플릿을 열고, 열기 전에 지문을 견준다. 필터를 켠 갈래에서 턴 기록의 실은 행이 뺀 행에
    들면 `consistent: false` 다."""
    from sqlalchemy.engine import make_url

    from api.chat.memory_window import load_current_summary
    from memory_eval import knowledge_recompute as kr
    from memory_eval import trajectory_replay as tr
    from memory_eval.arm_env import series_label
    from memory_eval.runtime import ARMS, generation_set, load_room, make_engine

    rows = [
        json.loads(line)
        for path in args.probes
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    accepted = [r for r in rows if r.get("status") in ("accept", "count_wrong") and r.get("turns")]
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in accepted:
        groups.setdefault((int(row["checkpoint"]), tr.arm_series(str(row["arm"]))), []).append(row)
    work_url = _db_url(writes=False)

    async def go() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for (cp, series), members in sorted(groups.items()):
            label = series_label(args.label, str(members[0]["arm"])) if series == "B" else args.label
            url = make_url(work_url).set(database=checkpoint.template_db_name(cp, label))
            engine, factory = make_engine(url.render_as_string(hide_password=False))
            try:
                async with factory() as db:
                    conn = await db.connection()
                    expected = json.loads(
                        checkpoint.fingerprint_path(args.run / "dumps", cp, label).read_text(encoding="utf-8")
                    )
                    digest = await checkpoint.compute_summary_digest(conn, args.room) if series == "B" else None
                    tr.check_template(expected, await checkpoint.compute_fingerprint(conn, args.room), digest=digest)
                    ctx = await load_room(db, args.room)
                    current = await load_current_summary(db, args.room)
                    if current is None:
                        raise SystemExit(f"cp{cp} 템플릿에 요약이 없다 — 사실 섹션이 없는 체크포인트다")
                    prompt_set, _ = await generation_set(db, args.model, lane=ctx.lane)
                    for row in members:
                        result = await kr.recompute_probe(
                            db, args.room, cursor=current.cursor, turns=row["turns"], names=ctx.names,
                            user_label=prompt_set.user_label,
                            ignore_quoted_reply_names=kr.ignores_quoted_reply_names(ARMS[str(row["arm"])]),
                        )  # fmt: skip
                        arm_settings_of = ARMS[str(row["arm"])]
                        filter_on = bool(arm_settings_of.get("memory_knowledge_filter")) and bool(
                            arm_settings_of.get("memory_facts_inject")
                        )
                        recorded = (row.get("memoryFacts") or [None])[-1]
                        compared = kr.compare_recorded(result, recorded, filter_on=filter_on)
                        out.append(
                            {"arm": row["arm"], "item": row["item"], "checkpoint": cp, "filterOn": filter_on}
                            | result
                            | compared
                        )
            finally:
                await engine.dispose()
        return out

    result = asyncio.run(go())
    _write(args.out, result)
    _print(
        {
            "rows": len(result),
            "inconsistent": [f"{r['arm']}:{r['item']}" for r in result if r["consistent"] is False],
            "droppedSecretTotal": sum(len(r["droppedSecret"]) for r in result),
        }
    )
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    book = _ledger(args)
    rows = book.rows()
    by_stage: dict[str, float] = {}
    by_bundle: dict[str, float] = {}
    for row in rows:
        # 하네스 전에 손으로 남긴 줄에는 단계 칸이 없다 — 그 줄도 원가는 세되 단계는 따로 묶는다.
        stage = str(row.get("stage") or ledger_mod.NO_STAGE)
        by_stage[stage] = by_stage.get(stage, 0.0) + ledger_mod.row_cost(row)
        key = str(row.get("bundle"))
        by_bundle[key] = by_bundle.get(key, 0.0) + ledger_mod.row_cost(row)
    _print(
        {
            "calls": len(rows),
            "totalUsd": book.total_usd(),
            "byStage": by_stage,
            "byBundle": by_bundle,
            "bundle": book.bundle,
            "bundleUsd": book.bundle_usd(),
            "capUsd": args.cap_usd,
            "haltUsd": args.halt_usd,
        }
    )
    return 0


def register(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """인프라 하위 명령을 등록한다."""
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

    p = sub.add_parser(
        "split-bundle", help="대본 셋을 층별 시드로 한꺼번에 나누고 작품을 넘는 시험 합계 하한을 확인한다"
    )
    p.add_argument("--config", type=Path, required=True, help="층별 시드·합계 하한 파일")
    p.add_argument("--out-root", type=Path, help="작품별 분할 폴더의 부모(기본 <원자료>/split)")
    p.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 개수와 합계 판정만 찍는다")
    p.set_defaults(fn=cmd_split_bundle)

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

    p = sub.add_parser("ending-stats", help="엔딩 층: 작업 DB 의 방 스탯을 지정 값으로(엔딩 문턱 위도 받는다)")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--stats", type=Path, required=True, help='JSON {"<스탯 이름>": 값, …}')
    p.set_defaults(fn=cmd_ending_stats)

    p = sub.add_parser("media-book", help="작업 DB 의 작품 발행 버전에 합성 미디어 북(방을 만들기 전에)")
    p.add_argument("--content-id", type=uuid.UUID, help="기본 튜토리얼 스토리")
    p.add_argument("--spec", type=Path, help="명세 파일(기본 = 측정 데이터 폴더의 기본 명세)")
    p.set_defaults(fn=cmd_media_book)

    p = sub.add_parser(
        "consent", help="측정 작업 DB 회원의 약관 동의를 현행판으로(재동의 게이트가 측정 계정을 막지 않게)"
    )
    p.add_argument("--room", type=uuid.UUID, help="그 방 주인만(없으면 탈퇴하지 않은 회원 전원)")
    p.set_defaults(fn=cmd_consent)

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
    p.add_argument(
        "--b-series",
        action="store_true",
        help="접기마다 요약 비밀 표기 켜짐 판(B 계열)을 함께 만들어 <원자료>/summaries-<label>-b.jsonl 에 적는다(series-template 입력)",
    )
    p.add_argument(
        "--fill-embeddings",
        action="store_true",
        help="턴마다 운영 채우기 함수로 미임베딩 장면·사실 행을 따라잡고 얼리기 전에 다 채운다(--embed-model·--embed-dims)",
    )
    p.add_argument("--embed-model", help="임베딩 채우기 모델(서버 env 의 MEMORY_EMBED_MODEL 과 같게)")
    p.add_argument("--embed-dims", type=int, help="임베딩 채우기 차원(서버 env 의 MEMORY_EMBED_DIMS 와 같게)")
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
    _replay_embedding_args(p)
    p.set_defaults(fn=cmd_trajectory)

    p = sub.add_parser(
        "trajectory-replay", help="얼린 체크포인트에서 지난 턴의 생성 프롬프트를 그때 상태로 갈래마다 다시 조립"
    )
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--insert-log", type=Path, required=True, help="그 체크포인트를 만든 넣기 기록(턴별 스냅샷 수)")
    p.add_argument("--baseline", type=Path, help="넣기 때 남긴 기준 갈래 궤적 — 표본 턴을 다시 조립해 견준다")
    p.add_argument("--compare-turns", default="2,30,31,41,100,101,200,300", help="기준 궤적과 견줄 표본 턴")
    p.add_argument("--turns", default="2,300", help="조립할 턴 범위(양끝 포함)")
    p.add_argument("--arms", default="A2,B2")
    p.add_argument("--model", default="opus")
    p.add_argument(
        "--label", help="A 계열 템플릿을 얼린 넣기의 단계 이름 — 주면 갈래마다 자기 계열 템플릿에서 조립한다"
    )
    p.add_argument("--checkpoint", type=int, help="--label 과 함께, 조립할 템플릿의 체크포인트")
    p.add_argument("--out-dir", type=Path, required=True)
    _replay_embedding_args(p)
    p.add_argument(
        "--embed-plan-out",
        type=Path,
        help="계획 모드 — 질의 벡터가 빠진 글을 embed-plan 꼴(JSONL)로 모아 쓰고 궤적 점은 쓰지 않는다(embed-run 의 입력)",
    )
    p.set_defaults(fn=cmd_trajectory_replay)

    p = sub.add_parser("embed-run", help="embed-plan 글 목록을 한 후보(모델@차원)로 임베딩해 벡터 파일에 덧붙인다")
    p.add_argument("--plan", type=Path, required=True, help="embed-plan 출력(JSONL)")
    p.add_argument(
        "--candidate", required=True, help="voyage-4-lite·voyage-4·voyage-4-large@차원 또는 gemini-embedding-2@차원"
    )
    p.add_argument("--embeddings", type=Path, required=True, help="덧붙일 벡터 파일(JSONL)")
    p.add_argument("--stage", default="s5-embed")
    paid(p)
    p.set_defaults(fn=cmd_embed_run)

    p = sub.add_parser(
        "series-template", help="A 계열 체크포인트 템플릿에서 요약 글만 B 판으로 바꾼 B 계열 템플릿(서버를 내린 뒤)"
    )
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--label", required=True, help="A 계열 템플릿을 얼린 넣기 실행의 --label")
    p.add_argument("--checkpoints", default="100,300")
    p.add_argument("--summaries", type=Path, required=True, help='줄마다 {"snapshotId", "summary"}')
    p.add_argument("--pg-container")
    p.add_argument("--db-user", default="postgres")
    p.set_defaults(fn=cmd_series_template)

    p = sub.add_parser("export-episodes", help="방의 장면을 오프라인 회상 입력으로(읽기만)")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--vectors-out", type=Path, help="저장된 장면 벡터를 오프라인 벡터 파일(JSONL)로도 쓴다")
    p.set_defaults(fn=cmd_export_episodes)

    p = sub.add_parser("recall-parity", help="두 recall-offline 출력의 행 단위 일치")
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_recall_parity)

    p = sub.add_parser("recall-warnings", help="로그의 서버 회상 실패 경고 줄 수")
    p.add_argument("--logs", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_recall_warnings)

    p = sub.add_parser("injection-warnings", help="프로브 시도 서버 로그의 사실·회상 주입 실패 경고 줄 수(갈래별)")
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_injection_warnings)

    from api.core.config import Settings

    p = sub.add_parser("probe")
    with_plants(p)
    with_splits(p)
    paid(p)
    p.add_argument("--checkpoint-label", help="복원할 템플릿의 단계 이름(넣기 실행의 --label, 기본 = --stage)")
    p.add_argument("--stage", required=True)
    p.add_argument("--arm", required=True, choices=["baseline", "A", "B", "A2", "B2", *BUNDLE1_ARMS])
    p.add_argument("--embed-model", help="묶음 1 갈래의 서버 env 임베딩 모델(MEMORY_EMBED_MODEL)")
    p.add_argument("--embed-dims", type=int, help="묶음 1 갈래의 서버 env 임베딩 차원(MEMORY_EMBED_DIMS)")
    _hybrid_args(p, grid=False)
    p.add_argument(
        "--memory-embed-recall-timeout-ms",
        type=int,
        default=Settings.model_fields["memory_embed_recall_timeout_ms"].default,
        help="묶음 1 갈래의 서버 env 질의 임베딩 시간 상한(밀리초, 기본 = 앱 기본값) — env 에 늘 싣는다",
    )
    p.add_argument("--checkpoints", default="50,100,300")
    p.add_argument("--items")
    p.add_argument("--room", type=uuid.UUID)
    p.add_argument("--cred-file", type=Path)
    p.add_argument("--cookie-file", type=Path)
    p.add_argument("--port", type=int, default=8130, help="작업자 i(1부터)의 서버 포트는 이 값 + i")
    p.add_argument(
        "--workers",
        type=int,
        default=workers.DEFAULT_WORKERS,
        help=f"프로브 작업자 수(1~{workers.MAX_WORKERS}). 작업자마다 서버 포트·작업 DB(<작업 DB>_probe_w<i>)·Redis 번호·쿠키 파일이 따로다",
    )
    p.add_argument(
        "--redis-db-base",
        type=int,
        default=workers.DEFAULT_REDIS_DB_BASE,
        help="작업자 i 의 Redis DB 번호는 이 값 + i(기본이면 9~15)",
    )
    p.add_argument("--server-env", type=Path, help="서버에 덮어 줄 KEY=VALUE 파일(모델 배정 등 — 키 값은 넣지 않는다)")
    p.add_argument("--opus-turn-usd", type=float, default=0.13)
    p.add_argument("--judgment-turn-usd", type=float, default=0.003)
    p.add_argument("--burst-limit", type=int, default=9)
    p.add_argument(
        "--halt-base", type=int, help="불능 멈춤 기준 프로브 수(갈래당, 기본 = 계획한 프로브 수 — 다르면 거부)"
    )
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("latency", help="프로브 결과의 갈래별 상태 수·첫 글자 지연 p50/p95")
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.set_defaults(fn=cmd_latency)

    p = sub.add_parser("attribution")
    with_plants(p)
    with_splits(p)
    p.add_argument("--probes", type=Path, nargs="+", required=True)
    p.add_argument("--seed-json", type=Path, default=DEFAULT_SEED_JSON)
    p.add_argument("--recall-header", default="[지난 기억 — 참고]")
    p.add_argument(
        "--fact-header", help="사실 섹션 머리글(사실을 싣는 갈래의 귀속 자리) — 운영 렌더의 머리글을 그대로 준다"
    )
    p.add_argument("--room", type=uuid.UUID, required=True, help="원문 창 경계를 읽을 생성 세트의 방(그 방의 레인)")
    p.add_argument("--model", default="opus", help="원문 창 경계를 읽을 생성 세트의 모델")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_attribution)

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
    p.add_argument("--user-name", help="사용자의 이야기 속 이름 — 행에서 기대 사실의 자리표시(사용자)로 바꿔 견준다")
    p.add_argument(
        "--dev-rows", action="store_true", help="항목마다 기대 사실과 그 키의 행·키만 빼고 맞는 행을 붙인다(개발 전용)"
    )
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_fact_metrics)

    p = sub.add_parser("arm-env", help="2차 런 갈래(A2·B2)의 측정 서버 env 줄")
    p.add_argument("--arm", required=True, choices=["A2", "B2"])
    p.add_argument("--prompt-dump", help="PROMPT_DUMP_PATH 줄을 더한다(프로브는 폴더마다 따로 넣는다)")
    p.set_defaults(fn=cmd_arm_env)

    p = sub.add_parser(
        "filter-recompute", help="프로브 질문 턴의 지식 범위 필터를 서버 함수로 다시 계산(템플릿 DB 읽기만)"
    )
    p.add_argument("--probes", type=Path, nargs="+", required=True, help="probe 결과(jsonl)")
    p.add_argument("--room", type=uuid.UUID, required=True)
    p.add_argument("--label", required=True, help="A 계열 템플릿을 얼린 넣기의 단계 이름")
    p.add_argument("--model", default="opus")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_filter_recompute)

    p = sub.add_parser("ledger")
    p.set_defaults(fn=cmd_ledger)
