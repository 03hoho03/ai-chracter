"""두 계열 투입 — 접기마다 요약을 비밀 표기 슬롯 꺼짐(A 계열)·켜짐(B 계열) 두 판으로 함께 만든다.

계열마다 따로 투입하면 장면·사실 추출이 LLM 무작위로 달라 두 계열 갈래의 차이에 추출 잡음이 섞인다. 그래서 투입은 한 번이고, 방에
커밋되는 것은 A 판이다: 앱의 접기 함수(`fold_memory`)를 요약 비밀 표기 스위치를 끈 채로 부른다(프로세스 설정이 켜져 있어도 끈다
— A 계열의 정의가 슬롯 없음이다). B 판은 커밋하지 않고 줄 파일(`{"snapshotId", "summary"}`)로만 남겨, `series-template` 이 A 계열
템플릿을 복제한 B 계열 템플릿의 스냅샷 요약 글을 그 판으로 바꾼다.

B 판 프롬프트는 스위치를 켠 접기가 같은 순간에 만들 프롬프트와 바이트까지 같다: 같은 접기 구간(`plan_fold`), 같은 이름 출처
읽기(`memory_fold._room_people` — 방 사실 행, 스토리 방이면 미디어 북 인물, 캐릭터 방이면 작품 이름), 같은 조립 함수. 이름 출처는
A 판을 커밋하기 전에 읽는다 — 서버도 요약 호출 전에 읽고, 그 사이 바뀌는 행은 없다(사실 추출은 접기 뒤다). 다른 점은 직전
요약뿐이다: B 판은 자기 계열의 직전 판(지금 현재 스냅샷의 B 판)을 이어 받는다. 되감기로 스냅샷이 지워지면 현재 스냅샷이 앞
스냅샷으로 돌아가고 그 B 판을 이어 받는다 — 지워진 스냅샷의 B 판 줄은 파일에 남지만 `series-template` 은 템플릿에 없는 줄을 무시한다.

A 판은 커밋됐는데 B 판 호출이 끝내 실패하면 그 스냅샷의 B 판이 영영 비므로(이어 넣기는 다음 턴부터다) 멈춘다 — B 계열 템플릿은
그 방 스냅샷 하나라도 B 판이 없으면 만들어지지 않는다."""

import contextlib
import json
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold
from api.chat.memory_window import load_current_summary, select_current_snapshot
from api.chat.prompt_builder import MemorySummaryResult, PromptNames, build_memory_summary_prompt
from api.core.config import settings
from api.db.models import ChatMessage, ChatRoomMemorySnapshot, PromptSection, PromptSet
from api.llm.chat_models import ChatModelId, PromptSetModelId
from api.llm.client import LLMCallContext, LLMClient

from memory_eval.arm_env import B_SERIES_SUFFIX
from memory_eval.series_template import load_summaries

# B 판 요약 호출을 한 접기에서 다시 부르는 최대 횟수(접기 연속 실패 상한과 같은 수).
B_SUMMARY_ATTEMPTS = 3


def summaries_path(run_dir: Path, label: str) -> Path:
    """투입 단계 이름의 B 판 요약 파일 — B 계열 템플릿 이름과 같은 꼬리를 붙인다."""
    return run_dir / f"summaries-{label}{B_SERIES_SUFFIX}.jsonl"


class BSeries:
    """B 판 요약 줄 파일. 이어 넣기를 위해 열 때 있던 줄을 읽는다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.rows: dict[str, str] = load_summaries(path) if path.exists() else {}

    def previous(self, snapshot_id: uuid.UUID | None) -> str:
        """지금 현재 스냅샷의 B 판(스냅샷이 없으면 첫 요약이라 빈 글). 현재 스냅샷의 B 판이 없으면 이 방은 두 계열로 넣지 않은
        구간이 있어 B 계열을 이어 만들 수 없다."""
        if snapshot_id is None:
            return ""
        if str(snapshot_id) not in self.rows:
            raise SystemExit(f"현재 스냅샷 {snapshot_id} 의 B 판 요약이 없다 — 이 방은 처음부터 두 계열로 넣어야 한다")
        return self.rows[str(snapshot_id)]

    def append(self, snapshot_id: uuid.UUID, summary: str) -> None:
        if str(snapshot_id) in self.rows:
            raise SystemExit(f"스냅샷 {snapshot_id} 의 B 판 요약이 이미 있다")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"snapshotId": str(snapshot_id), "summary": summary}, ensure_ascii=False) + "\n")
        self.rows[str(snapshot_id)] = summary


@contextlib.contextmanager
def secret_marking(on: bool) -> Iterator[None]:
    saved = settings.memory_summary_secret_marking
    settings.memory_summary_secret_marking = on
    try:
        yield
    finally:
        settings.memory_summary_secret_marking = saved


async def current_snapshot(db: AsyncSession, room_id: uuid.UUID) -> tuple[uuid.UUID, Any, uuid.UUID] | None:
    """현재 스냅샷의 (id, 커서 시각, 커서 메시지 id) — 앱의 현재 요약 고르기와 같은 문장."""
    snap = ChatRoomMemorySnapshot
    row = (
        await db.execute(select_current_snapshot(room_id, snap.id, snap.cursor_created_at, snap.cursor_message_id))
    ).first()
    return None if row is None else (row.id, row.cursor_created_at, row.cursor_message_id)


async def b_summary_prompt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    room_id: uuid.UUID,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    names: PromptNames,
    previous_summary: str,
    turns: list[ChatMessage],
) -> str:
    """스위치를 켠 접기가 이 구간에 만들 요약 프롬프트(직전 요약만 B 판)."""
    people = await memory_fold._room_people(
        session_factory, room_id, is_story_chat=is_story_chat, names=names, user_label=prompt_set.user_label
    )
    return build_memory_summary_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=is_story_chat,
        previous_summary=previous_summary,
        turns=turns,
        names=names,
        room_people=people,
    )


async def _b_summary(llm: LLMClient, prompt: str, *, room_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """접기와 같은 호출 위치·같은 자르기. 빈 요약이나 호출 실패는 몇 번 다시 부르고, 끝내 안 되면 멈춘다."""
    errors: list[str] = []
    for _ in range(B_SUMMARY_ATTEMPTS):
        try:
            result = await llm.generate_structured(
                prompt,
                MemorySummaryResult,
                usage=LLMCallContext(call_site="chat_memory_summary", user_id=user_id, room_id=room_id),
            )
        except Exception as exc:
            errors.append(repr(exc))
            continue
        summary = result.summary.strip()[: memory_fold.SUMMARY_MAX_LENGTH]
        if summary:
            return summary
        errors.append("빈 요약")
    raise SystemExit(
        f"B 판 요약을 {B_SUMMARY_ATTEMPTS}번 다 실패했다 — A 판은 커밋됐다, 이 방은 처음부터 다시 넣는다: {errors}"
    )


async def fold_both(
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMClient,
    *,
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    prompt_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    names: PromptNames,
    series: BSeries | None,
    writing_model: ChatModelId,
    call_model: PromptSetModelId | None = None,
) -> dict[str, Any]:
    """A 판 접기(앱 함수, 슬롯 꺼짐)와, `series` 를 주면 그 접기가 스냅샷을 만들었을 때 같은 구간의 B 판. 접은 스냅샷의 커서가
    미리 계산한 구간과 다르면(그사이 방이 바뀌었다) B 판을 만들지 않고 멈춘다. `writing_model` 은 넣은 턴에 응답을 쓴 것으로 칠
    모델(투입의 생성 모델)이다 — 앱 접기는 이 모델과 방 레인으로 기억 사용 범위를 가른다. `call_model` 은 앱 접기에 그대로 넘기는
    요약 칸의 부를 모델이다(모델 배정 표의 행이 정한 값, 행이 없으면 None 이라 요약 모델 설정으로 간다)."""
    plan = None
    b_prompt = None
    async with session_factory() as db:
        before = await current_snapshot(db, room_id)
        if series is not None:
            current = await load_current_summary(db, room_id)
            unsummarized = await memory_fold._load_unsummarized(db, room_id, current.cursor if current else None)
            plan = memory_fold.plan_fold(unsummarized)
    if series is not None and plan is not None:
        b_prompt = await b_summary_prompt(
            session_factory, room_id=room_id, prompt_set=prompt_set, sections=sections, is_story_chat=is_story_chat,
            names=names, previous_summary=series.previous(before[0] if before else None), turns=plan.turns,
        )  # fmt: skip
    with secret_marking(False):
        await memory_fold.fold_memory(
            session_factory, llm, room_id=room_id, user_id=user_id, prompt_set=prompt_set, sections=sections,
            is_story_chat=is_story_chat, names=names, writing_model=writing_model, call_model=call_model,
        )  # fmt: skip
    async with session_factory() as db:
        after = await current_snapshot(db, room_id)
    folded = after is not None and (before is None or after[0] != before[0])
    if not folded or series is None:
        return {"folded": folded, "bSummary": False}
    assert after is not None
    if plan is None or b_prompt is None or (after[1], after[2]) != plan.cursor:
        raise SystemExit(f"방 {room_id}: 접은 스냅샷의 구간이 B 판을 만들 구간과 다르다 — B 판을 만들지 않고 멈춘다")
    series.append(after[0], await _b_summary(llm, b_prompt, room_id=room_id, user_id=user_id))
    return {"folded": True, "bSummary": True}
