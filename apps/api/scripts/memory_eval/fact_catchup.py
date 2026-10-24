"""넣기 절차의 사실 추출 따라잡기 — 운영 모듈이 있으면 그것을, 없으면 하네스 시제품을 부르는 어댑터.

운영 사실 추출 모듈(`api.chat.memory_facts`)은 아직 없다. 생기면 장면 추출(`memory_episodes.extract_pending_episode`)과 같은
꼴이어야 한다 — 이 어댑터가 그 계약을 가정한다:

    await memory_facts.extract_pending_facts(
        session_factory, llm, *, room_id, user_id, prompt_set, sections, is_story_chat, names
    ) -> None

가장 오래된 미추출 스냅샷 하나를 처리하고 실패는 다음 턴에 다시 잡는다. 문안은 판정 세트의 `fact` 칸(`(PromptSet, 섹션 목록)`),
진행 상태는 `chat_memory_fact_extractions`(스냅샷마다 한 행, 끝나면 `status = 'done'`)에서 읽는다.

모듈이 없으면 시제품(`prototype_facts`)이 같은 자리에서 돈다: 접힌 창을 DB 에서 만들고, 가장 이른 미추출 창 하나를 호출해
원자료 폴더의 따라잡기 기록(JSONL)에 덧붙인다. 그 기록에 있는 스냅샷이 완료다."""

import importlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.llm.client import LLMClient

from memory_eval.ledger import BudgetExceededError
from memory_eval.prototype_extract import Window
from memory_eval.prototype_facts import FactCaller, FactStore, extract_next

OPERATIONAL_MODULE = "api.chat.memory_facts"
OPERATIONAL_FUNCTION = "extract_pending_facts"

SessionFactory = async_sessionmaker[AsyncSession]


class FactCatchUp(Protocol):
    name: str

    async def run_once(self, session_factory: SessionFactory, room_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        """한 번 따라잡는다. `pendingBefore`·`doneBefore`·`doneAfter` 를 돌려준다(연속 실패 판정은 부르는 쪽이)."""
        ...

    async def snapshot_status(self, db: AsyncSession, snapshot_id: uuid.UUID) -> str | None:
        """그 스냅샷의 사실 추출 상태(끝났으면 `done`, 기록이 없으면 None)."""
        ...


def operational_module() -> ModuleType | None:
    try:
        module = importlib.import_module(OPERATIONAL_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == OPERATIONAL_MODULE:
            return None
        raise
    if not callable(getattr(module, OPERATIONAL_FUNCTION, None)):
        raise SystemExit(f"{OPERATIONAL_MODULE} 에 {OPERATIONAL_FUNCTION} 가 없다 — 하네스가 가정한 계약과 다르다")
    return module


async def _count(db: AsyncSession, sql: str, room_id: uuid.UUID) -> int:
    return int(await db.scalar(text(sql), {"room": room_id}) or 0)


_PENDING_SQL = (
    "SELECT count(*) FROM chat_room_memory_snapshots s WHERE s.chat_room_id = :room AND NOT EXISTS "
    "(SELECT 1 FROM chat_memory_fact_extractions x WHERE x.snapshot_id = s.id AND x.status = 'done')"
)
_DONE_SQL = (
    "SELECT count(*) FROM chat_memory_fact_extractions x JOIN chat_room_memory_snapshots s ON s.id = x.snapshot_id "
    "WHERE s.chat_room_id = :room AND x.status = 'done'"
)


@dataclass
class OperationalFacts:
    module: ModuleType
    llm: LLMClient
    name: str = "operational"

    async def run_once(self, session_factory: SessionFactory, room_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        from memory_eval.runtime import judgment_sets, load_room

        async with session_factory() as db:
            ctx = await load_room(db, room_id)
            sets = await judgment_sets(db, ctx)
            pending = await _count(db, _PENDING_SQL, room_id)
            done_before = await _count(db, _DONE_SQL, room_id)
        fact_set = getattr(sets, "fact", None)
        if fact_set is None:
            raise SystemExit("판정 세트에 사실 추출 칸(fact)이 없다 — 하네스가 가정한 계약과 다르다")
        await getattr(self.module, OPERATIONAL_FUNCTION)(
            session_factory,
            self.llm,
            room_id=room_id,
            user_id=user_id,
            prompt_set=fact_set[0],
            sections=fact_set[1],
            is_story_chat=ctx.lane == "story",
            names=ctx.names,
            call_model=sets.call_model("fact"),
        )
        async with session_factory() as db:
            done_after = await _count(db, _DONE_SQL, room_id)
        return {"backend": self.name, "pendingBefore": pending, "doneBefore": done_before, "doneAfter": done_after}

    async def snapshot_status(self, db: AsyncSession, snapshot_id: uuid.UUID) -> str | None:
        status = await db.scalar(
            text("SELECT status FROM chat_memory_fact_extractions WHERE snapshot_id = :snapshot"),
            {"snapshot": snapshot_id},
        )
        return str(status) if status is not None else None


@dataclass(frozen=True)
class LoadedWindows:
    windows: list[Window]
    render: Callable[[Window], str]
    user_name: str


async def load_windows_from_db(session_factory: SessionFactory, room_id: uuid.UUID) -> LoadedWindows:
    from memory_eval.prototype_extract import build_windows, render_window
    from memory_eval.runtime import judgment_sets, load_room

    async with session_factory() as db:
        ctx = await load_room(db, room_id)
        windows = await build_windows(db, room_id)
        sets = await judgment_sets(db, ctx)
    prompt_set = sets.summary[0]
    return LoadedWindows(
        windows=windows,
        render=lambda w: render_window(w, prompt_set, ctx.names),
        user_name=ctx.names.judgment_user_name,
    )


@dataclass
class PrototypeFacts:
    store: FactStore
    caller: FactCaller
    instruction: str
    version: str
    load: Callable[[SessionFactory, uuid.UUID], Awaitable[LoadedWindows]] = load_windows_from_db
    name: str = "prototype"
    errors: list[str] = field(default_factory=list)

    async def run_once(self, session_factory: SessionFactory, room_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        """호출 실패(파싱·거부·네트워크)는 진전 없음으로 남기고 다음 턴에 같은 창을 다시 잡는다 — 운영 추출의 재시도와 같은
        자리다. 원장 상한은 그대로 멈춘다."""
        loaded = await self.load(session_factory, room_id)
        ids = {str(w.snapshot_id) for w in loaded.windows}
        done_before = len(ids & self.store.done_ids())
        state: dict[str, Any] = {
            "backend": self.name,
            "pendingBefore": len(ids) - done_before,
            "doneBefore": done_before,
        }
        try:
            await extract_next(
                loaded.windows,
                self.store,
                render=loaded.render,
                caller=self.caller,
                instruction=self.instruction,
                user_name=loaded.user_name,
                version=self.version,
            )
        except BudgetExceededError:
            raise
        except Exception as exc:  # 시제품 호출 실패 — 진전 없음으로 센다
            state["error"] = f"{type(exc).__name__}: {exc}"[:300]
            self.errors.append(state["error"])
        state["doneAfter"] = len(ids & self.store.done_ids())
        return state

    async def snapshot_status(self, db: AsyncSession, snapshot_id: uuid.UUID) -> str | None:
        return "done" if str(snapshot_id) in self.store.done_ids() else None


def fact_catch_up(
    llm: LLMClient,
    *,
    store: FactStore,
    caller: FactCaller | None,
    instruction: str | None,
    version: str,
    find_module: Callable[[], ModuleType | None] = operational_module,
) -> FactCatchUp:
    """운영 모듈이 있으면 그것(넣기의 LLM 클라이언트로), 없으면 시제품(주어진 호출 함수와 문안으로)."""
    module = find_module()
    if module is not None:
        return OperationalFacts(module=module, llm=llm)
    if caller is None or instruction is None:
        raise SystemExit(
            "운영 사실 추출 모듈이 없다 — 시제품으로 돌리려면 사실 문안 파일(--facts-instruction-file)을 준다"
        )
    return PrototypeFacts(store=store, caller=caller, instruction=instruction, version=version)
