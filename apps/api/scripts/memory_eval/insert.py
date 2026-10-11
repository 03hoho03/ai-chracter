"""고정 대본을 격리 작업 DB 의 방에 턴 단위로 넣는다 — 운영과 같은 순서로 접기·추출·되감기를 일으킨다.

턴마다: 사용자·진행자 메시지를 한 문장씩 넣고(`clock_timestamp` 라 넣은 순서가 곧 키 순서) 방 턴 수를 올려 커밋 → 실제
`fold_memory` 를 직접 부른다(서버 백그라운드와 같은 함수, 같은 세트·이름) → 추출을 켠 실행이면 운영처럼 턴마다
추출 작업을 한 번(연속 3턴 진전이 없으면 멈춘다) → 되감기 항목이 있으면 그 메시지를 담은 스냅샷이 막 생기고 추출까지 끝난 턴에 실제 메시지 삭제 API(앱을 프로세스
안에서 ASGI 로)로 지우고 지워진 스냅샷이 정확히 1개인지 단언 → 궤적 갈래마다 다음 턴의 생성 프롬프트를 조립해 기록 → 얼릴
체크포인트면 (스탯 고정 파일을 줬으면 그 체크포인트의 값으로 방 스탯을 맞춘 뒤) 템플릿으로 얼린다.

LLM 은 셋 중 하나로만 돈다: 가짜(유료 호출 0 — 절차 확인용), 실제(명시 승인 인자가 있을 때만, 원장 상한 확인 뒤), 드라이런(DB 도
LLM 도 건드리지 않고 계획·견적만). 이미 넣은 턴 뒤에서 이어 넣는다(방의 턴 수부터)."""

import dataclasses
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold
from api.chat.memory_window import load_current_summary
from api.db.models import ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot
from api.llm.chat_models import ChatModelId
from api.llm.client import CallUsage, LLMCallContext, LLMClient

from memory_eval.checkpoint import database_name, freeze, pinned_path
from memory_eval.ledger import Ledger
from memory_eval.pinned_stats import apply_pinned_stats, pinned_for_checkpoint, preflight_pinned
from memory_eval.plants import PlantSet
from memory_eval.runtime import app_client, load_room, make_engine, story_judgment_sets
from memory_eval.trajectory import DEFAULT_RECALL_HEADER, append_point, assemble_point
from memory_eval.transcript import ScriptTurn

T = TypeVar("T", bound=BaseModel)

# 실호출 견적(접기 한 번, Haiku 5.5): 요약 입력 약 3.2K 토큰 × 토크나이저 1.3 + 출력 약 0.6K → 넉넉히 반올림.
FOLD_CALL_ESTIMATE_USD = 0.002
MAX_CONSECUTIVE_FOLD_FAILURES = 3
MAX_CONSECUTIVE_EXTRACT_FAILURES = 3
# 되감기 직전 그 스냅샷의 추출을 따라잡게 부르는 최대 횟수(추출 작업 자신의 재시도 3회와 같은 수).
REWIND_EXTRACT_ATTEMPTS = 3


class LedgerTap(LLMClient):
    """실제 클라이언트를 감싸 구조화 호출마다 사용량을 원장에 적고, 부르기 전에 상한을 본다. 사용량은 파싱 실패 전에 모이므로
    실패한 호출의 원가도 적는다."""

    def __init__(self, inner: LLMClient, ledger: Ledger, *, stage: str, per_call_estimate_usd: float) -> None:
        self.inner = inner
        self.ledger = ledger
        self.stage = stage
        self.per_call_estimate_usd = per_call_estimate_usd

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise RuntimeError("하네스의 접기·추출 경로는 생성 호출을 하지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        self.ledger.check_headroom(self.per_call_estimate_usd)
        sink: list[CallUsage] = []
        try:
            return await self.inner.generate_structured(
                prompt, response_schema, images, usage=dataclasses.replace(usage, usage_sink=sink)
            )
        finally:
            for call in sink:
                self.ledger.append(
                    stage=self.stage,
                    call_site=call.call_site,
                    model=call.model,
                    input_tokens=call.prompt_tokens or 0,
                    cached_tokens=call.cached_tokens or 0,
                    cache_write_tokens=call.cache_write_tokens or 0,
                    output_tokens=call.output_tokens or 0,
                    thoughts_tokens=call.thoughts_tokens or 0,
                )


def rewind_items(plant_set: PlantSet) -> list[dict[str, Any]]:
    return [p for p in plant_set.plants if p.get("rewind")]


def plan(
    plant_set: PlantSet, *, start_turn: int, until_turn: int, freeze_at: Sequence[int], extract: bool
) -> dict[str, Any]:
    """드라이런 계획. 접기 턴은 명목(30턴에 첫 접기, 뒤로 10턴마다) — 원문이 24,000자를 넘으면 더 일찍 접힐 수 있다."""
    folds = [
        t
        for t in range(start_turn, until_turn + 1)
        if t >= memory_fold.FOLD_AT_TURNS and t % memory_fold.FOLD_TURNS == 0
    ]
    calls = len(folds) * (2 if extract else 1)
    return {
        "turns": [start_turn, until_turn],
        "nominalFoldTurns": folds,
        "llmCalls": calls,
        "estimateUsd": calls * FOLD_CALL_ESTIMATE_USD,
        "freezeAt": [t for t in freeze_at if start_turn <= t <= until_turn],
        "rewinds": [
            {"item": p["id"], "plantTurn": p["plantTurn"], "nominalDeleteAfterTurn": p["rewind"].get("deleteAfterTurn")}
            for p in rewind_items(plant_set)
        ],
    }


async def _snapshot_count(db: AsyncSession, room_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ChatRoomMemorySnapshot)
            .where(ChatRoomMemorySnapshot.chat_room_id == room_id)
        )
        or 0
    )


async def _fold_due(db: AsyncSession, room_id: uuid.UUID) -> bool:
    current = await load_current_summary(db, room_id)
    unsummarized = await memory_fold._load_unsummarized(db, room_id, current.cursor if current else None)
    return memory_fold.plan_fold(unsummarized) is not None


async def _pending_extractions(db: AsyncSession, room_id: uuid.UUID) -> int:
    value = await db.scalar(
        text(
            "SELECT count(*) FROM chat_room_memory_snapshots s WHERE s.chat_room_id = :room AND NOT EXISTS "
            "(SELECT 1 FROM chat_memory_extractions x WHERE x.snapshot_id = s.id AND x.status = 'done')"
        ),
        {"room": room_id},
    )
    return int(value or 0)


async def _done_extractions(db: AsyncSession, room_id: uuid.UUID) -> int:
    value = await db.scalar(
        text(
            "SELECT count(*) FROM chat_memory_extractions x JOIN chat_room_memory_snapshots s ON s.id = x.snapshot_id "
            "WHERE s.chat_room_id = :room AND x.status = 'done'"
        ),
        {"room": room_id},
    )
    return int(value or 0)


async def _extract_once(
    session_factory: async_sessionmaker[AsyncSession], llm: LLMClient, room_id: uuid.UUID, user_id: uuid.UUID
) -> dict[str, int]:
    """운영과 같이 턴마다 추출 작업을 한 번 부른다(그 작업이 가장 오래된 미추출 스냅샷 하나를 처리하고, 실패는 시도 3회까지
    다음 턴에 다시 잡는다). 미추출·완료 수를 앞뒤로 돌려준다 — 연속 실패 판정은 부르는 쪽이 한다."""
    try:
        from api.chat import memory_episodes
    except ImportError as exc:
        raise SystemExit("추출 켬 실행은 추출을 구현한 코드에서만 돈다(에피소드 추출 모듈이 없다)") from exc
    async with session_factory() as db:
        ctx = await load_room(db, room_id)
        sets = await story_judgment_sets(db)
        pending = await _pending_extractions(db, room_id)
        done_before = await _done_extractions(db, room_id)
    episode_set = getattr(sets, "episode", None)
    if episode_set is None:
        raise SystemExit("판정 세트에 추출 칸이 없다(추출을 구현한 코드에서만 돈다)")
    await memory_episodes.extract_pending_episode(
        session_factory,
        llm,
        room_id=room_id,
        user_id=user_id,
        prompt_set=episode_set[0],
        sections=episode_set[1],
        is_story_chat=True,
        names=ctx.names,
    )
    async with session_factory() as db:
        done_after = await _done_extractions(db, room_id)
    return {"pendingBefore": pending, "doneBefore": done_before, "doneAfter": done_after}


async def _message_key(db: AsyncSession, room_id: uuid.UUID, content: str) -> tuple[Any, uuid.UUID] | None:
    rows = (
        await db.execute(
            select(ChatMessage.created_at, ChatMessage.id).where(
                ChatMessage.chat_room_id == room_id,
                ChatMessage.role == ChatMessageRole.USER,
                ChatMessage.content == content,
            )
        )
    ).all()
    if not rows:
        return None
    if len(rows) != 1:
        raise SystemExit(f"되감기 대상 사용자 메시지가 {len(rows)}개다(정확히 1개여야 한다)")
    return rows[0].created_at, rows[0].id


async def run_insert(
    *,
    script: Sequence[ScriptTurn],
    plant_set: PlantSet,
    room_id: uuid.UUID,
    until_turn: int,
    freeze_at: Sequence[int],
    llm: LLMClient,
    extract: bool,
    arms: Sequence[str],
    trajectory_model: ChatModelId,
    run_dir: Path,
    label: str,
    cookie_value: str | None,
    database_url: str,
    container: str | None,
    db_user: str,
    recall_field: str | None = None,
    recall_header: str = DEFAULT_RECALL_HEADER,
    pinned_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_turn = {t.turn: t for t in script}
    engine, session_factory = make_engine(database_url)
    log_path = run_dir / f"insert-{label}.jsonl"
    rewinds = {p["id"]: p for p in rewind_items(plant_set)}
    done_rewinds = _done_rewinds(log_path)
    consecutive_fold_failures = 0
    extraction_streak = ExtractionStreak(limit=MAX_CONSECUTIVE_EXTRACT_FAILURES)
    try:
        async with session_factory() as db:
            ctx = await load_room(db, room_id)
            start = ctx.room.turn_count + 1
            sets = await story_judgment_sets(db)
            if pinned_doc is not None:
                await preflight_pinned(
                    db, room_id, ctx.setup.id, pinned_doc, [t for t in freeze_at if start <= t <= until_turn]
                )
        summary_set, summary_sections = sets.summary
        for turn in range(start, until_turn + 1):
            row = by_turn.get(turn)
            if row is None:
                raise SystemExit(f"대본에 턴 {turn} 이 없다")
            started = time.perf_counter()
            async with session_factory() as db:
                db.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content=row.user))
                await db.flush()
                db.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content=row.assistant))
                await db.flush()
                await db.execute(
                    update(ChatRoom).where(ChatRoom.id == room_id).values(turn_count=ChatRoom.turn_count + 1)
                )
                await db.commit()
                before = await _snapshot_count(db, room_id)
                due = await _fold_due(db, room_id)
            await memory_fold.fold_memory(
                session_factory,
                llm,
                room_id=room_id,
                user_id=ctx.room.user_id,
                prompt_set=summary_set,
                sections=summary_sections,
                is_story_chat=True,
                names=ctx.names,
            )
            async with session_factory() as db:
                after = await _snapshot_count(db, room_id)
            folded = after > before
            consecutive_fold_failures = consecutive_fold_failures + 1 if due and not folded else 0
            record: dict[str, Any] = {"turn": turn, "foldDue": due, "folded": folded, "snapshots": after}
            if extract:
                state = await _extract_once(session_factory, llm, room_id, ctx.room.user_id)
                record["extract"] = state
                if extraction_streak.observe(
                    pending_before=state["pendingBefore"],
                    done_before=state["doneBefore"],
                    done_after=state["doneAfter"],
                ):
                    _append(log_path, record)
                    raise SystemExit(f"턴 {turn}: 추출이 {extraction_streak.failures}번 연속 진전 없음 — 멈춘다")
            for item_id, plant in rewinds.items():
                if item_id in done_rewinds:
                    continue
                deleted = await _maybe_rewind(
                    session_factory, room_id, plant, by_turn, cookie_value, extract=extract, llm=llm
                )
                if deleted is not None:
                    done_rewinds.add(item_id)
                    record.setdefault("rewinds", []).append(deleted)
            next_row = by_turn.get(turn + 1)
            if next_row is not None:
                for arm in arms:
                    async with session_factory() as db:
                        point, _ = await assemble_point(
                            db,
                            room_id,
                            next_turn=turn + 1,
                            user_content=next_row.user,
                            arm=arm,
                            model=trajectory_model,
                            recall_header=recall_header,
                            recall_field=recall_field,
                        )
                    append_point(run_dir / f"trajectory-{label}-{arm}.jsonl", point)
            record["ms"] = round((time.perf_counter() - started) * 1000, 1)
            _append(log_path, record)
            if consecutive_fold_failures >= MAX_CONSECUTIVE_FOLD_FAILURES:
                raise SystemExit(
                    f"턴 {turn}: 접기가 {consecutive_fold_failures}번 연속 실패 — 멈춘다(서버 로그·원장 확인)"
                )
            if turn in freeze_at:
                pinned: dict[str, Any] | None = None
                if pinned_doc is not None:
                    async with session_factory() as db:
                        pinned = await apply_pinned_stats(
                            db, room_id, ctx.setup.id, pinned_for_checkpoint(pinned_doc, turn)
                        )
                    _append(log_path, {"turn": turn, "pinnedStats": pinned})
                await engine.dispose()
                frozen = await freeze(
                    database_url,
                    work_db=database_name(database_url),
                    checkpoint=turn,
                    room_id=room_id,
                    dumps_dir=run_dir / "dumps",
                    container=container,
                    db_user=db_user,
                    label=label,
                    require_episode_rows=extract,
                )
                if pinned is not None:
                    path = pinned_path(run_dir / "dumps", turn, label)
                    path.write_text(json.dumps(pinned["pinned"], ensure_ascii=False) + "\n", encoding="utf-8")
                _append(log_path, {"turn": turn, "frozen": frozen["template"], "fingerprint": frozen["fingerprint"]})
        return {"start": start, "until": until_turn, "log": str(log_path)}
    finally:
        await engine.dispose()


@dataclasses.dataclass(frozen=True)
class RewindState:
    snapshot_id: str | None
    extraction_status: str | None
    covering_episodes: int | None


def rewind_ready(state: RewindState, *, extract: bool) -> bool:
    """지워도 되는가. 추출을 켠 실행은 그 메시지를 덮는 스냅샷의 추출이 끝났고(done) 그 턴을 덮는 에피소드가 있어야 한다 —
    아니면 지운 핵심어가 애초에 에피소드에 없어 되감기 누출 검사가 아무것도 검증하지 못한다. 추출을 끈 실행은 기다리지 않는다."""
    if not extract:
        return True
    return state.extraction_status == "done" and bool(state.covering_episodes)


async def ensure_rewind_ready(
    read: Callable[[], Awaitable[RewindState]],
    extract_once: Callable[[], Awaitable[None]],
    *,
    extract_enabled: bool,
    attempts: int,
) -> RewindState:
    """지울 준비가 될 때까지 추출을 따라잡게 다시 부른다. 횟수 안에 안 되면 넣기를 멈춘다."""
    state = await read()
    for _ in range(attempts):
        if rewind_ready(state, extract=extract_enabled):
            return state
        await extract_once()
        state = await read()
    if rewind_ready(state, extract=extract_enabled):
        return state
    raise SystemExit(f"되감기 전 추출이 {attempts}번 안에 끝나지 않았다 — 넣기를 멈춘다: {state}")


async def _maybe_rewind(
    session_factory: async_sessionmaker[AsyncSession],
    room_id: uuid.UUID,
    plant: dict[str, Any],
    by_turn: dict[int, ScriptTurn],
    cookie_value: str | None,
    *,
    extract: bool,
    llm: LLMClient,
) -> dict[str, Any] | None:
    """그 메시지를 담은 스냅샷이 생긴 첫 턴(그 접기와 추출이 끝난 직후, 다음 접기 전)에 지운다. 추출을 켠 실행은 그 스냅샷의
    추출이 끝나고 그 턴을 덮는 에피소드가 생길 때까지 추출을 따라잡게 한 뒤 지운다. 지울 때의 상태를 기록에 남긴다."""
    content = by_turn[int(plant["plantTurn"])].user
    async with session_factory() as db:
        key = await _message_key(db, room_id, content)
        if key is None:
            return None
        current = await load_current_summary(db, room_id)
        if current is None or key > current.cursor:
            return None
        user_id = await db.scalar(select(ChatRoom.user_id).where(ChatRoom.id == room_id))
    plant_turn = int(plant["plantTurn"])

    async def read() -> RewindState:
        async with session_factory() as db:
            return await _rewind_state(db, room_id, key, plant_turn)

    async def extract_once() -> None:
        assert user_id is not None
        await _extract_once(session_factory, llm, room_id, user_id)

    state = await ensure_rewind_ready(read, extract_once, extract_enabled=extract, attempts=REWIND_EXTRACT_ATTEMPTS)
    async with session_factory() as db:
        before = await _snapshot_count(db, room_id)
        turn_count = int(await db.scalar(select(ChatRoom.turn_count).where(ChatRoom.id == room_id)) or 0)
    if cookie_value is None:
        raise SystemExit("되감기 항목을 지우려면 세션 쿠키 파일이 필요하다(실제 삭제 API 를 부른다)")
    async with app_client(cookie_value) as client:
        response = await client.delete(f"/chat-rooms/{room_id}/messages/{key[1]}")
    if response.status_code != 204:
        raise SystemExit(f"메시지 삭제 API 가 {response.status_code}: {response.text[:200]}")
    async with session_factory() as db:
        after = await _snapshot_count(db, room_id)
    removed = before - after
    if removed != 1:
        raise SystemExit(f"{plant['id']}: 삭제로 지워진 스냅샷이 {removed}개다(정확히 1개여야 한다)")
    nominal = plant["rewind"].get("deleteAfterTurn")
    return {
        "item": plant["id"],
        "messageId": str(key[1]),
        "atTurn": turn_count,
        "nominalTurn": nominal,
        "snapshotsRemoved": removed,
        "snapshotId": state.snapshot_id,
        "extractionStatus": state.extraction_status,
        "coveringEpisodes": state.covering_episodes,
    }


async def _rewind_state(
    db: AsyncSession, room_id: uuid.UUID, key: tuple[Any, uuid.UUID], plant_turn: int
) -> RewindState:
    """그 메시지를 덮는 스냅샷(커서가 메시지 키 이상인 가장 이른 스냅샷), 그 스냅샷의 추출 상태, 그 턴을 덮는 에피소드 수.
    추출 테이블이 없는 코드(추출 전)면 추출 상태·에피소드 수는 None."""
    snapshot = await db.scalar(
        select(ChatRoomMemorySnapshot.id)
        .where(
            ChatRoomMemorySnapshot.chat_room_id == room_id,
            tuple_(ChatRoomMemorySnapshot.cursor_created_at, ChatRoomMemorySnapshot.cursor_message_id) >= key,
        )
        .order_by(ChatRoomMemorySnapshot.cursor_created_at, ChatRoomMemorySnapshot.cursor_message_id)
        .limit(1)
    )
    if not await db.scalar(text("SELECT to_regclass('chat_memory_extractions') IS NOT NULL")):
        return RewindState(
            snapshot_id=str(snapshot) if snapshot else None, extraction_status=None, covering_episodes=None
        )
    status = await db.scalar(
        text("SELECT status FROM chat_memory_extractions WHERE snapshot_id = :snapshot"), {"snapshot": snapshot}
    )
    episodes = await db.scalar(
        text(
            "SELECT count(*) FROM chat_memory_episodes WHERE chat_room_id = :room "
            "AND start_turn <= :turn AND end_turn >= :turn"
        ),
        {"room": room_id, "turn": plant_turn},
    )
    return RewindState(
        snapshot_id=str(snapshot) if snapshot else None,
        extraction_status=str(status) if status is not None else None,
        covering_episodes=int(episodes or 0),
    )


def _append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _done_rewinds(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        for entry in json.loads(line).get("rewinds", []):
            done.add(str(entry["item"]))
    return done


class ExtractionStreak:
    """추출 연속 실패 세기. 완료되지 않은 스냅샷(실패 상태로 남은 것 포함 — 재시도해도 진전이 없으면 실패로 센다)이 있었는데 이번 추출 작업 뒤 완료 수가 늘지 않으면 실패 한 번, 늘면 초기화. 할 일이
    없던 턴은 세지 않는다. `observe` 가 참이면 한도에 닿았다(넣기를 멈춘다)."""

    def __init__(self, *, limit: int) -> None:
        self.limit = limit
        self.failures = 0

    def observe(self, *, pending_before: int, done_before: int, done_after: int) -> bool:
        if pending_before == 0:
            return False
        self.failures = 0 if done_after > done_before else self.failures + 1
        return self.failures >= self.limit
