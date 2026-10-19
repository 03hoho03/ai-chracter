"""얼린 체크포인트에서 지난 턴의 생성 프롬프트를 그때 상태로 다시 조립하는 궤적 — 넣기 동안 남기지 못한 갈래(A2·B2, 묶음 1
여섯 갈래)의 점을 나중에 만든다. LLM 없음, DB 는 읽기만 한다. 묶음 1 갈래는 자기 계열의 체크포인트 템플릿에서 조립한다(아래
계열 고르기) — 두 계열은 스냅샷 요약 글만 다르고 스냅샷·장면·사실 행은 같아, 넣기 기록의 턴별 스냅샷 수가 두 계열에 똑같이 맞다.

턴 T 의 상태는 넣기 순서에서 나온다. 넣기는 턴마다 사용자·진행자 메시지를 넣고 → 접기 → 추출 → 다음 턴(T+1)의 프롬프트를
조립했다. 그래서 턴 T 의 프롬프트가 본 요약은 턴 T−1 까지의 접기가 만든 마지막 스냅샷이다(턴 30 의 접기는 턴 31 부터 보인다).
그 스냅샷 수는 넣기 기록의 `snapshots`(턴 T−1 줄)이고, 스냅샷 생성 시각이 턴 T 사용자 메시지보다 이른 것의 수와 같아야 한다 —
둘이 어긋나면 되감기나 늦은 접기로 순서를 확신할 수 없으므로 거부한다.

히스토리는 턴 T 사용자 메시지 앞까지(오프닝 포함), 사용자 발화는 그 메시지, 기억 노트는 빈 값, 스탯·대화 프로필은 방의 지금 값
(넣기는 스탯을 바꾸지 않는다), 회상·사실 줄은 비워 두어(None) 그 턴 커서로 다시 고르게 한다 — 회상·사실 후보는 커서 이하
스냅샷의 행만 보므로 나중 행이 섞이지 않는다. 임베딩 회상을 켠 갈래는 측정 서버처럼 질의 임베딩 클라이언트를 받아 조립한다 —
질의 벡터는 미리 계산한 벡터 파일에서 읽는다(`memory_eval.offline_embedding`, 외부 호출 없음)."""

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.keyword_notes import match_keyword_notes
from api.chat.memory_window import CurrentSummary, prompt_window
from api.chat.room_stats import load_room_stats
from api.chat.turn_prompt import InjectedPersona, InjectedTurnState, build_room_prompt
from api.core.config import settings
from api.db.models import ChatMessage, ChatMessageRole, ChatRoomMemorySnapshot
from api.db.models.persona import UserPersona
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import KeywordNote
from api.llm.client import SegmentedPrompt

from memory_eval import checkpoint
from memory_eval.arm_env import BARE_SUFFIX, BUNDLE1_ARMS, series_label, template_series
from memory_eval.embed_offline import EmbeddingTable
from memory_eval.offline_embedding import client_for
from memory_eval.runtime import RoomContext, arm_settings


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def turn_user_indices(roles: Sequence[ChatMessageRole]) -> list[int]:
    """턴 번호(1부터) 순의 사용자 메시지 인덱스. 바로 뒤가 응답인 사용자 메시지만 턴이다."""
    return [
        i
        for i in range(len(roles) - 1)
        if roles[i] == ChatMessageRole.USER and roles[i + 1] == ChatMessageRole.ASSISTANT
    ]


def snapshot_counts(insert_rows: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """넣기 기록에서 턴 → 그 턴 접기 뒤 스냅샷 수. 얼리기·스탯 고정 줄(스냅샷 칸이 없다)은 건너뛴다."""
    return {int(r["turn"]): int(r["snapshots"]) for r in insert_rows if "snapshots" in r}


def snapshots_seen_at(turn: int, counts: Mapping[int, int]) -> int:
    """턴 `turn` 의 프롬프트가 본 스냅샷 수 — 접기는 앞 턴 응답 뒤에 일어나므로 앞 턴 줄의 값이다. 턴 1 은 0."""
    if turn == 1:
        return 0
    if turn - 1 not in counts:
        raise SystemExit(f"넣기 기록에 턴 {turn - 1} 줄이 없다 — 턴 {turn} 의 요약을 정할 수 없다")
    return counts[turn - 1]


def check_snapshot_order(created: Sequence[datetime], cursors: Sequence[tuple[Any, Any]]) -> None:
    """생성 순과 커서 순이 같아야 "n 번째로 만든 스냅샷 = 그때 커서 최대 행"(앱의 현재 요약 규칙)이 된다."""
    if list(created) != sorted(created) or list(cursors) != sorted(cursors):
        raise SystemExit("스냅샷의 생성 순과 커서 순이 다르다 — 그때의 현재 요약을 정할 수 없다")


def check_snapshot_count(turn: int, *, from_log: int, created_before: int) -> None:
    if from_log != created_before:
        raise SystemExit(
            f"턴 {turn}: 넣기 기록의 스냅샷 수 {from_log} 와 사용자 메시지 전에 생긴 스냅샷 수 {created_before} 가 다르다"
        )


def section_header(sections: Sequence[PromptSection], slot: str) -> str:
    """생성 채널 섹션 `slot` 본문의 첫 줄(머리글). 세트 안에서 하나로 정해지지 않거나 자리표시를 품으면 거부한다."""
    heads = {s.body.split("\n", 1)[0] for s in sections if s.channel == "generation" and s.slot == slot}
    if len(heads) != 1:
        raise SystemExit(f"생성 섹션 {slot} 의 머리글이 하나가 아니다({len(heads)}개)")
    head = heads.pop()
    if "{" in head or not head.strip():
        raise SystemExit(f"생성 섹션 {slot} 의 첫 줄이 머리글이 아니다")
    return head


def section_text(prompt: str, header: str) -> str:
    """머리글 줄로 시작하는 섹션(다음 빈 줄 앞까지). 섹션 머리는 빈 줄 바로 뒤의 한 줄이어야 한다 — 다른 섹션 본문이 이 머리글
    글자를 언급하는 자리(회상 안내문이 사실 섹션 이름을 부르는 것 등)를 섹션으로 잘못 세지 않게."""
    start = prompt.find(f"\n\n{header}\n")
    if start == -1:
        return ""
    start += 2
    end = prompt.find("\n\n", start)
    return prompt[start:] if end == -1 else prompt[start:end]


@dataclass(frozen=True)
class RoomTimeline:
    """방 전체 메시지(키 순)·턴별 사용자 메시지 인덱스·생성 순 스냅샷."""

    messages: list[ChatMessage]
    user_indices: list[int]
    snapshots: list[ChatRoomMemorySnapshot]


async def load_timeline(db: AsyncSession, ctx: RoomContext) -> RoomTimeline:
    room_id = ctx.room.id
    messages = list(
        (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            )
        ).all()
    )
    snapshots = list(
        (
            await db.scalars(
                select(ChatRoomMemorySnapshot)
                .where(ChatRoomMemorySnapshot.chat_room_id == room_id)
                .order_by(ChatRoomMemorySnapshot.created_at.asc())
            )
        ).all()
    )
    check_snapshot_order(
        [s.created_at for s in snapshots], [(s.cursor_created_at, s.cursor_message_id) for s in snapshots]
    )
    indices = turn_user_indices([m.role for m in messages])
    if len(indices) != ctx.room.turn_count:
        raise SystemExit(f"턴으로 읽힌 사용자 메시지 {len(indices)}개가 방 턴 수 {ctx.room.turn_count} 와 다르다")
    return RoomTimeline(messages=messages, user_indices=indices, snapshots=snapshots)


async def injected_persona(db: AsyncSession, ctx: RoomContext) -> InjectedPersona | None:
    if ctx.room.persona_id is None:
        return None
    persona = await db.get(UserPersona, ctx.room.persona_id)
    if persona is None:
        return None
    return InjectedPersona(name=persona.name, gender=persona.gender, description=persona.description)


async def replay_point(
    db: AsyncSession,
    ctx: RoomContext,
    timeline: RoomTimeline,
    *,
    turn: int,
    counts: Mapping[int, int],
    arm: str,
    prompt_set: tuple[PromptSet, list[PromptSection]],
    persona: InjectedPersona | None,
    recall_header: str,
    fact_header: str,
    embeddings: EmbeddingTable | None,
    missing: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], str]:
    """턴 `turn` 의 프롬프트를 그때 상태로 조립해 1차 궤적과 같은 칸의 점과 프롬프트 본문을 돌려준다. `embeddings` 는 질의
    벡터 파일이다 — 임베딩 회상을 켠 갈래는 그것 없이 거부되고, `missing` 을 주면 빠진 질의 글을 모은다(계획 모드)."""
    index = timeline.user_indices[turn - 1]
    user_message = timeline.messages[index]
    history = timeline.messages[:index]
    seen = snapshots_seen_at(turn, counts)
    created_before = sum(1 for s in timeline.snapshots if s.created_at < user_message.created_at)
    check_snapshot_count(turn, from_log=seen, created_before=created_before)
    snapshot = timeline.snapshots[seen - 1] if seen else None
    summary = (
        CurrentSummary(cursor=(snapshot.cursor_created_at, snapshot.cursor_message_id), text=snapshot.summary_text)
        if snapshot is not None
        else None
    )
    # 캐릭터 방은 스탯이 없다(스탯은 시작설정에 딸린다).
    stats = (await load_room_stats(db, ctx.room.id, ctx.setup.id))[2] if ctx.setup is not None else {}
    state = InjectedTurnState(summary=summary, memory_note="", stats=stats, persona=persona)
    set_row, sections = prompt_set
    embedding_client = client_for(arm, embeddings, missing=missing)
    with arm_settings(arm):
        started = time.perf_counter()
        generation = await build_room_prompt(
            db,
            ctx.room,
            ctx.setup,
            history,
            user_message.content,
            None,
            set_row,
            sections,
            turn_state=state,
            embedding_client=embedding_client,
        )
        build_ms = (time.perf_counter() - started) * 1000
        windowed = settings.memory_window_generation
    prompt = generation.prompt
    window = prompt_window(history, summary.cursor if summary else None) if windowed else history
    notes = (
        await db.scalars(
            select(KeywordNote)
            .where(
                KeywordNote.content_version_id == ctx.room.content_version_id,
                KeywordNote.starting_setup_id.is_(None)
                if ctx.setup is None
                else or_(KeywordNote.starting_setup_id.is_(None), KeywordNote.starting_setup_id == ctx.setup.id),
            )
            .order_by(KeywordNote.order, KeywordNote.entity_id)
        )
    ).all()
    matched = match_keyword_notes(notes, window, user_message.content, names=generation.names)
    segments = prompt.segments if isinstance(prompt, SegmentedPrompt) else (prompt,)
    recall = section_text(prompt, recall_header)
    facts = section_text(prompt, fact_header)
    if generation.memory_recall and not recall:
        raise SystemExit(f"턴 {turn} {arm}: 회상이 실렸는데 회상 머리글을 찾지 못했다")
    if generation.memory_facts and not facts:
        raise SystemExit(f"턴 {turn} {arm}: 사실이 실렸는데 사실 머리글을 찾지 못했다")
    point = {
        "turn": turn,
        "arm": arm,
        "chars": len(prompt),
        "segmentChars": [len(s) for s in segments],
        "segmentSha": [_sha(s) for s in segments[:2]],
        "noteChars": 0,
        "summaryChars": len(summary.text) if summary and summary.text in prompt else 0,
        "windowMessages": len(window),
        "windowChars": sum(len(m.content) for m in window),
        "keywordNotes": len(matched),
        "keywordNoteChars": sum(len(n.info_text) for n in matched if n.info_text in prompt),
        "recallChars": len(recall),
        "recall": list(generation.memory_recall),
        "factChars": len(facts),
        "facts": list(generation.memory_facts),
        # 질의 임베딩 결과(`ok`·`failed` 등). 부르지 않은 턴(임베딩 회상이 꺼짐·요약 없음)은 None.
        "queryOutcome": generation.memory_query["outcome"] if generation.memory_query else None,
        "historyMessages": len(history),
        "snapshotsSeen": seen,
        "buildMs": round(build_ms, 3),
    }
    return point, str(prompt)


# 넣기 때 남긴 기준 궤적과 견주는 칸(시간 칸은 뺀다).
COMPARED_FIELDS = (
    "chars",
    "segmentChars",
    "segmentSha",
    "summaryChars",
    "windowMessages",
    "windowChars",
    "keywordNotes",
    "keywordNoteChars",
    "recallChars",
    "historyMessages",
)


def point_diff(recorded: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    return {k: (recorded.get(k), rebuilt.get(k)) for k in COMPARED_FIELDS if recorded.get(k) != rebuilt.get(k)}


# ---------------------------------------------------------------- 계열 고르기
# 갈래마다 자기 계열의 체크포인트 템플릿에서 조립한다. 지금 연 작업 DB 하나에서 모든 갈래를 조립하면 B 계열 갈래도 A 요약 위에서
# 조립돼 B 갈래 이름의 궤적이 A 요약을 담는다.


def _base_arm(arm: str) -> str:
    return arm.removesuffix(BARE_SUFFIX)


def arm_series(arm: str) -> str:
    """갈래가 도는 템플릿 계열. 묶음 1 갈래가 아닌 것(2차 런 갈래·기준 갈래)은 A 계열 템플릿(투입이 커밋한 요약)에서 돈다."""
    base = _base_arm(arm)
    return template_series(base) if base in BUNDLE1_ARMS else "A"


def replay_template(cp: int, label: str, arm: str) -> str:
    """갈래가 조립할 템플릿 DB 이름 — `label` 은 A 계열 템플릿을 얼린 넣기 실행의 단계 이름이다."""
    base = _base_arm(arm)
    return checkpoint.template_db_name(cp, series_label(label, base) if base in BUNDLE1_ARMS else label)


def arms_by_series(arms: Sequence[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for arm in arms:
        out.setdefault(arm_series(arm), []).append(arm)
    return out


def bare_arm(arm: str) -> str:
    """B 계열 갈래의 자기 재렌더 갈래(대화 기록 뒤 섹션을 끈 것)."""
    if arm not in BUNDLE1_ARMS or template_series(arm) != "B":
        raise SystemExit(f"자기 재렌더는 B 계열 갈래만 만든다: {arm}")
    return arm + BARE_SUFFIX


def check_template(expected: Mapping[str, Any], actual: Mapping[str, Any], *, digest: str | None) -> None:
    """템플릿 지문 파일(`expected`)과 지금 템플릿 DB 의 지문을 견준다. B 계열이면(`digest` 를 주면) 요약 글 해시도 — 해시가 없는 B
    지문(요약을 바꾸기 전에 만든 것)도 칸 차이로 거부된다."""
    now = dict(actual) if digest is None else {**actual, checkpoint.SUMMARY_DIGEST_KEY: digest}
    diffs = checkpoint.fingerprint_diff(expected, now)
    if diffs:
        raise SystemExit("조립할 템플릿의 지문이 지문 파일과 다르다: " + "; ".join(diffs))


def self_render_checks(points: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """B 계열 갈래마다 자기 재렌더 점과 같은 턴의 앞 두 블록 해시가 같은가. 재렌더 점이 없으면 `halt`."""
    by_arm: dict[str, dict[int, Mapping[str, Any]]] = {}
    for point in points:
        by_arm.setdefault(str(point["arm"]), {})[int(point["turn"])] = point
    out: dict[str, dict[str, Any]] = {}
    for arm in sorted(a for a in by_arm if a in BUNDLE1_ARMS and template_series(a) == "B"):
        bare = by_arm.get(bare_arm(arm), {})
        turns = sorted(set(by_arm[arm]) & set(bare))
        if not turns:
            out[arm] = {"turns": 0, "mismatchedTurns": [], "status": "halt", "pass": False}
            continue
        mismatched = [t for t in turns if list(by_arm[arm][t]["segmentSha"][:2]) != list(bare[t]["segmentSha"][:2])]
        status = "fail" if mismatched else "pass"
        out[arm] = {"turns": len(turns), "mismatchedTurns": mismatched, "status": status, "pass": not mismatched}
    return out
