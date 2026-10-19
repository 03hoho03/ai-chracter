"""묶음 1 문안 시제품 — 요약 비밀 표기 슬롯과 사실 추출 지시문의 후보를, 얼린 개발 투입 템플릿을 복제한 작업 DB 에서 다시 돌린다.

요약: 작업 DB 의 그 방 스냅샷을 지우고(장면·사실 행과 추출 기록은 스냅샷 FK 의 CASCADE 로 함께 빠진다) 운영 `fold_memory` 를
원래 스냅샷 수만큼 다시 부른다. 접기는 언제나 커서 뒤 가장 오래된 10턴을 접으므로 같은 메시지 위에서 같은 구간이 나온다 —
접기마다 새 커서가 원래 스냅샷 커서와 같은지 단언한다. 후보 슬롯은 DB 를 고치지 않고 그 호출에 넘기는 섹션 목록에만 요약
지시문 바로 뒤 섹션으로 끼운다. 슬롯의 `{room_people}` 값은 그 방의 이름 출처(캐릭터 = 작품 이름, 스토리 = 미디어 북 인물)와,
원래 투입에서 그 접기 때 이미 있던 사실 행(이번 접기보다 앞 스냅샷의 행 — 지우기 전에 읽어 둔다)의 이름이다. 이름이 0개면
후보 파일의 고정 문구가 값이 된다(스위치가 켜진 방에서 슬롯이 늘 실리는 운영 설계와 같다).

사실: 스냅샷·요약은 그대로 두고 그 방의 사실 행과 사실 추출 기록만 지운 뒤, 운영 `extract_pending_facts` 를 스냅샷 수만큼
(가장 오래된 미추출 스냅샷 하나씩) 다시 부른다. 후보 지시문은 그 호출의 섹션 목록에서만 사실 채널 지시문을 바꾼다.

두 실행 모두 결과를 JSONL 로 남긴다(머리 한 줄 + 접기·행마다 한 줄). 결과 파일에는 요약 본문·사실 값이 들어 있다 — 문안을
고치는 다음 단계에는 이 파일이 아니라 지표 명령(`wording_metrics`)의 숫자만 건넨다. 표준출력에는 개수만 나간다.

유료 호출 전 멈춤: 접기·추출 함수는 안의 예외를 모두 삼키므로 원장 상한 예외도 그 안에서는 실패로 바뀐다 — 호출마다 그 전에
`before_call` 로 상한을 본다."""

import hashlib
import json
import string
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_facts, memory_fold
from api.chat.memory_facts import normalize_part
from api.chat.prompt_builder import PromptNames
from api.content.author_macros import resolve_user_name
from api.db.models import PromptSection
from api.db.models.character import CharacterVersionDetail
from api.db.models.story import MediaBookPerson
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMClient

from memory_eval.checkpoint import EVAL_DB_PREFIX, ensure_eval_db_name
from memory_eval.ledger import price_for
from memory_eval.runtime import Lane, RoomContext, judgment_sets, load_room

SUMMARY_CHANNEL = "memory_summary"
FACT_CHANNEL = "memory_fact"
INSTRUCTION_SLOT = "instruction"
# 시제품이 요약 채널에 끼우는 슬롯 이름(운영 슬롯 이름은 그 데이터 변경이 정한다).
SUMMARY_SLOT = "secret_marking"
ROOM_PEOPLE = "room_people"
# 사실 추출이 프로필 이름 없는 방의 사용자를 `known_by` 에 적는 표기(개발 투입 행에서 본 값).
FACT_USER_LABEL = "사용자"
MIN_NAME_CHARS = 2
MAX_FOLD_ATTEMPTS = 3
MAX_FACT_STALLS = 3
TEMPLATE_SUFFIX = "_frozen"
# 덧붙는 글의 토큰 수를 글자 수로 넉넉히 센다(한국어는 글자당 1토큰 아래로 잘린다).
TOKENS_PER_CHAR = 1.0
SUMMARY_CALL_SITE = "chat_memory_summary"
FACT_CALL_SITE = "chat_memory_fact"


# ---------------------------------------------------------------- 후보 파일


@dataclass(frozen=True)
class SummaryCandidate:
    version: str
    slot: str
    no_names: str
    sha256: str


@dataclass(frozen=True)
class FactCandidate:
    version: str
    instruction: str
    sha256: str


def _fields(body: str, what: str) -> set[str]:
    try:
        return {name for _, name, _, _ in string.Formatter().parse(body) if name is not None}
    except ValueError as exc:
        raise SystemExit(f"{what} 의 중괄호가 짝이 맞지 않는다(글자 중괄호는 두 번 쓴다): {exc}") from exc


def _read_candidate(path: Path) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    raw = json.loads(data.decode("utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit(f"후보 파일은 JSON 객체다: {path}")
    version = raw.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit(f"후보 파일에 판 이름(version)이 없다: {path}")
    return raw, hashlib.sha256(data).hexdigest()


def _text(raw: Mapping[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"후보 파일의 {key} 칸이 비었다: {path}")
    return value


def load_summary_candidate(path: Path) -> SummaryCandidate:
    """`{"version", "slot", "noNames"}`. 슬롯은 `{room_people}` 하나만 받는다 — 운영 렌더러가 그 슬롯에 넘길 값이 그것뿐이다.
    고정 문구는 플레이스홀더 없는 글이다(그 자체가 `{room_people}` 의 값이 된다)."""
    raw, sha = _read_candidate(path)
    slot = _text(raw, "slot", path)
    no_names = _text(raw, "noNames", path)
    fields = _fields(slot, "slot")
    if fields != {ROOM_PEOPLE}:
        raise SystemExit(f"요약 슬롯은 {{{ROOM_PEOPLE}}} 하나만 받는다 — 지금 {sorted(fields)}")
    if _fields(no_names, "noNames"):
        raise SystemExit("noNames 는 플레이스홀더 없는 글이다")
    return SummaryCandidate(version=str(raw["version"]), slot=slot, no_names=no_names, sha256=sha)


def load_fact_candidate(path: Path) -> FactCandidate:
    """`{"version", "instruction"}`. 사실 채널 지시문은 플레이스홀더를 받지 않는다(운영 렌더러가 그 슬롯에 값을 넘기지 않는다)."""
    raw, sha = _read_candidate(path)
    instruction = _text(raw, "instruction", path)
    fields = _fields(instruction, "instruction")
    if fields:
        raise SystemExit(f"사실 지시문은 플레이스홀더를 받지 않는다 — 지금 {sorted(fields)}")
    return FactCandidate(version=str(raw["version"]), instruction=instruction, sha256=sha)


# ---------------------------------------------------------------- 방 이름 목록


def excluded_user_names(names: PromptNames) -> list[str]:
    """방 이름 목록에서 뺄 사용자 이름 — 대화 프로필 이름, 없으면 기본 호칭, 그리고 사실 추출이 사용자를 적는 표기."""
    return [n for n in (names.persona_name, resolve_user_name(names.persona_name), FACT_USER_LABEL) if n]


def room_people(
    *,
    char_name: str | None,
    media_book_names: Sequence[str],
    fact_rows: Sequence[Mapping[str, Any]],
    user_names: Sequence[str],
) -> list[str]:
    """작품 이름 → 미디어 북 인물 → 사실 행(주어, 관계의 대상, 화자, 아는 사람 원소) 순으로, 처음 나온 표기를 지킨다. 같은지는
    사실 키와 같은 정규화로 보고, 사용자 이름과 정규화 뒤 2자 미만은 뺀다. 사실의 속성은 이름이 아니라 넣지 않는다."""
    excluded = {normalize_part(n) for n in user_names}
    out: list[str] = []
    seen: set[str] = set()

    def add(name: Any) -> None:
        if not isinstance(name, str):
            return
        key = normalize_part(name)
        if len(key) < MIN_NAME_CHARS or key in excluded or key in seen:
            return
        seen.add(key)
        out.append(name.strip())

    add(char_name)
    for name in media_book_names:
        add(name)
    for row in fact_rows:
        add(row.get("subject"))
        if row.get("kind") == "relation":
            add(row.get("object"))
        add(row.get("speaker"))
        for name in row.get("known_by") or []:
            add(name)
    return out


def summary_slot_text(candidate: SummaryCandidate, people: Sequence[str]) -> str:
    value = ", ".join(people) if people else candidate.no_names
    return candidate.slot.format(**{ROOM_PEOPLE: value})


# ---------------------------------------------------------------- 섹션(호출에 넘기는 목록만 바꾼다)


def _copy(section: PromptSection, **changes: Any) -> PromptSection:
    fields = {
        "prompt_set_id": section.prompt_set_id,
        "channel": section.channel,
        "scope": section.scope,
        "slot": section.slot,
        "variant": section.variant,
        "body": section.body,
        "conditional": section.conditional,
        "order": section.order,
    }
    return PromptSection(**{**fields, **changes})


def _escape(text_value: str) -> str:
    return text_value.replace("{", "{{").replace("}", "}}")


def with_summary_slot(sections: Sequence[PromptSection], slot_text: str) -> list[PromptSection]:
    """요약 지시문 행마다 바로 뒤에 같은 범위·순서 값의 슬롯 행을 끼운 새 목록. 렌더러는 슬롯을 처음 나온 순서로 묶고 순서
    값으로 안정 정렬하므로 슬롯이 지시문 바로 뒤에 온다. 값은 이미 채운 글이라 글자 중괄호는 두 번 쓴다. 원본 행은 그대로다.

    운영 슬롯(운영 마이그레이션이 conditional 로 심은 같은 이름의 행)이 든 세트에서는 그 행을 뺀다 — 남기면 운영 문안과 시제품
    문안이 함께 실려 시제품만 잰 프롬프트가 아니다. 시제품 슬롯(conditional 아님)이 이미 있으면 두 번 끼우는 것이라 거부한다."""
    if any(s.channel == SUMMARY_CHANNEL and s.slot == SUMMARY_SLOT and not s.conditional for s in sections):
        raise SystemExit(f"요약 채널에 시제품 {SUMMARY_SLOT} 슬롯이 이미 있다 — 두 번 끼우지 않는다")
    out: list[PromptSection] = []
    inserted = 0
    for section in sections:
        if section.channel == SUMMARY_CHANNEL and section.slot == SUMMARY_SLOT:
            continue
        out.append(section)
        if section.channel == SUMMARY_CHANNEL and section.slot == INSTRUCTION_SLOT:
            out.append(_copy(section, slot=SUMMARY_SLOT, body=_escape(slot_text), conditional=False))
            inserted += 1
    if not inserted:
        raise SystemExit("요약 채널에 지시문 슬롯이 없다 — 끼울 자리가 없다")
    return out


def with_fact_instruction(sections: Sequence[PromptSection], instruction: str) -> list[PromptSection]:
    """사실 채널 지시문 행의 본문만 후보로 바꾼 새 목록(다른 행·원본은 그대로)."""
    out = [
        _copy(s, body=instruction) if s.channel == FACT_CHANNEL and s.slot == INSTRUCTION_SLOT else s for s in sections
    ]
    if not any(s.channel == FACT_CHANNEL and s.slot == INSTRUCTION_SLOT for s in sections):
        raise SystemExit("사실 채널에 지시문 슬롯이 없다 — 바꿀 자리가 없다")
    return out


# ---------------------------------------------------------------- 작업 DB


def require_work_db(work_db: str, template: str) -> None:
    """작업 DB 는 평가 DB 이름이어야 하고, 템플릿(얼린 DB) 자신이거나 얼린 DB 이름이면 거부한다 — 지우고 다시 쓰는 대상이다."""
    ensure_eval_db_name(work_db)
    if work_db == template or work_db.endswith(TEMPLATE_SUFFIX):
        raise SystemExit(f"작업 DB 로 얼린 템플릿을 쓰지 않는다: {work_db} (템플릿 {template})")
    if not template.startswith(EVAL_DB_PREFIX):
        raise SystemExit(f"템플릿 이름이 평가 DB 가 아니다: {template}")


SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class RoomState:
    ctx: RoomContext
    char_name: str | None
    media_book_names: list[str]
    snapshots: list[tuple[uuid.UUID, datetime, uuid.UUID]]


async def _room_state(db: AsyncSession, room_id: uuid.UUID, lane: Lane) -> RoomState:
    ctx = await load_room(db, room_id, lane=lane)
    char_name: str | None = None
    media: list[str] = []
    if ctx.lane == "character":
        detail = await db.get(CharacterVersionDetail, ctx.room.content_version_id)
        char_name = detail.name if detail is not None else None
    else:
        media = list(
            await db.scalars(
                select(MediaBookPerson.name)
                .where(MediaBookPerson.content_version_id == ctx.room.content_version_id)
                .order_by(MediaBookPerson.order)
            )
        )
    rows = await db.execute(
        text(
            "SELECT id, cursor_created_at, cursor_message_id FROM chat_room_memory_snapshots WHERE chat_room_id = :room "
            "ORDER BY cursor_created_at, cursor_message_id"
        ),
        {"room": room_id},
    )
    snapshots = [(r.id, r.cursor_created_at, r.cursor_message_id) for r in rows]
    return RoomState(ctx=ctx, char_name=char_name, media_book_names=media, snapshots=snapshots)


async def room_fact_rows(db: AsyncSession, room_id: uuid.UUID) -> list[dict[str, Any]]:
    """그 방 사실 행 — 그 방 스냅샷 전체의 커서 순 번호(1부터, 행이 없는 스냅샷도 센다)와 함께, 스냅샷 순·행 순서로."""
    rows = await db.execute(
        text(
            "SELECT f.snapshot_id, f.ordinal, f.kind, f.subject, f.object, f.attribute, f.fact_key, f.value, "
            "f.truth_status, f.asserted_by, f.speaker, f.known_by, s.snapshot_index "
            "FROM chat_memory_facts f JOIN ("
            "SELECT id, row_number() OVER (ORDER BY cursor_created_at, cursor_message_id) AS snapshot_index "
            "FROM chat_room_memory_snapshots WHERE chat_room_id = :room) s ON s.id = f.snapshot_id "
            "WHERE f.chat_room_id = :room ORDER BY s.snapshot_index, f.ordinal"
        ),
        {"room": room_id},
    )
    return [
        {
            "snapshotIndex": int(r.snapshot_index),
            "ordinal": int(r.ordinal),
            "kind": r.kind,
            "subject": r.subject,
            "object": r.object,
            "attribute": r.attribute,
            "factKey": r.fact_key,
            "value": r.value,
            "truthStatus": r.truth_status,
            "assertedBy": r.asserted_by,
            "speaker": r.speaker,
            "known_by": list(r.known_by) if r.known_by else None,
        }
        for r in rows
    ]


def _refuse_existing(out_path: Path) -> None:
    if out_path.exists():
        raise SystemExit(f"결과 파일이 이미 있다(덮어쓰지 않는다): {out_path}")


def _start_output(out_path: Path, header: Mapping[str, Any]) -> None:
    _refuse_existing(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dict(header), ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _append(out_path: Path, record: Mapping[str, Any]) -> None:
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False, default=str) + "\n")


def _check_count(state: RoomState, expect_snapshots: int | None) -> None:
    if not state.snapshots:
        raise SystemExit("방에 스냅샷이 없다 — 다시 돌릴 접기가 없다")
    if expect_snapshots is not None and len(state.snapshots) != expect_snapshots:
        raise SystemExit(f"방 스냅샷 {len(state.snapshots)}개가 체크포인트 지문의 {expect_snapshots}개와 다르다")


async def replay_summaries(
    session_factory: SessionFactory,
    llm: LLMClient,
    *,
    room_id: uuid.UUID,
    lane: Lane,
    candidate: SummaryCandidate,
    out_path: Path,
    header: Mapping[str, Any],
    writing_model: ChatModelId,
    expect_snapshots: int | None = None,
    before_call: Callable[[], None] | None = None,
) -> dict[str, Any]:
    _refuse_existing(out_path)
    async with session_factory() as db:
        state = await _room_state(db, room_id, lane)
        sets = await judgment_sets(db, lane=state.ctx.lane)
        facts = await room_fact_rows(db, room_id)
    _check_count(state, expect_snapshots)
    _start_output(out_path, {**header, "userNames": excluded_user_names(state.ctx.names)})
    async with session_factory() as db:
        await db.execute(text("DELETE FROM chat_room_memory_snapshots WHERE chat_room_id = :room"), {"room": room_id})
        await db.commit()
    summary_set, summary_sections = sets.summary
    excluded = excluded_user_names(state.ctx.names)
    for index, (_, cursor_at, cursor_id) in enumerate(state.snapshots, start=1):
        people = room_people(
            char_name=state.char_name,
            media_book_names=state.media_book_names,
            fact_rows=[r for r in facts if r["snapshotIndex"] < index],
            user_names=excluded,
        )
        sections = with_summary_slot(summary_sections, summary_slot_text(candidate, people))
        latest = None
        for _ in range(MAX_FOLD_ATTEMPTS):
            if before_call is not None:
                before_call()
            await memory_fold.fold_memory(
                session_factory,
                llm,
                room_id=room_id,
                user_id=state.ctx.room.user_id,
                prompt_set=summary_set,
                sections=sections,
                is_story_chat=state.ctx.lane == "story",
                names=state.ctx.names,
                # 접기는 그 구간 응답을 쓴 모델이 기억 사용 범위 안일 때만 요약 비밀 표기 칸을 쓴다 — 템플릿 투입의 생성 모델을 준다.
                writing_model=writing_model,
            )
            async with session_factory() as db:
                count = int(
                    await db.scalar(
                        text("SELECT count(*) FROM chat_room_memory_snapshots WHERE chat_room_id = :room"),
                        {"room": room_id},
                    )
                    or 0
                )
                latest = (
                    await db.execute(
                        text(
                            "SELECT cursor_created_at, cursor_message_id, summary_text FROM chat_room_memory_snapshots "
                            "WHERE chat_room_id = :room ORDER BY cursor_created_at DESC, cursor_message_id DESC LIMIT 1"
                        ),
                        {"room": room_id},
                    )
                ).first()
            if count == index:
                break
        else:
            raise SystemExit(f"접기 {index} 가 {MAX_FOLD_ATTEMPTS}번 모두 스냅샷을 만들지 못했다 — 멈춘다")
        assert latest is not None
        if (latest.cursor_created_at, latest.cursor_message_id) != (cursor_at, cursor_id):
            raise SystemExit(f"접기 {index} 가 원래 스냅샷과 다른 구간을 접었다 — 같은 입력이 아니라 멈춘다")
        _append(
            out_path,
            {
                "kind": "fold",
                "index": index,
                "cursor": [cursor_at.isoformat(), str(cursor_id)],
                "roomPeopleCount": len(people),
                "noNames": not people,
                "summary": latest.summary_text,
            },
        )
    return {"folds": len(state.snapshots)}


_DONE_FACTS_SQL = (
    "SELECT count(*) FROM chat_memory_fact_extractions x JOIN chat_room_memory_snapshots s ON s.id = x.snapshot_id "
    "WHERE s.chat_room_id = :room AND x.status = 'done'"
)


async def replay_facts(
    session_factory: SessionFactory,
    llm: LLMClient,
    *,
    room_id: uuid.UUID,
    lane: Lane,
    candidate: FactCandidate,
    out_path: Path,
    header: Mapping[str, Any],
    expect_snapshots: int | None = None,
    before_call: Callable[[], None] | None = None,
) -> dict[str, Any]:
    _refuse_existing(out_path)
    async with session_factory() as db:
        state = await _room_state(db, room_id, lane)
        sets = await judgment_sets(db, lane=state.ctx.lane)
    _check_count(state, expect_snapshots)
    _start_output(out_path, {**header, "userNames": excluded_user_names(state.ctx.names)})
    async with session_factory() as db:
        await db.execute(text("DELETE FROM chat_memory_facts WHERE chat_room_id = :room"), {"room": room_id})
        await db.execute(text("DELETE FROM chat_memory_fact_extractions WHERE chat_room_id = :room"), {"room": room_id})
        await db.commit()
    fact_set, fact_sections = sets.fact
    sections = with_fact_instruction(fact_sections, candidate.instruction)
    done, stalls = 0, 0
    while done < len(state.snapshots):
        if before_call is not None:
            before_call()
        await memory_facts.extract_pending_facts(
            session_factory,
            llm,
            room_id=room_id,
            user_id=state.ctx.room.user_id,
            prompt_set=fact_set,
            sections=sections,
            is_story_chat=state.ctx.lane == "story",
            names=state.ctx.names,
        )
        async with session_factory() as db:
            after = int(await db.scalar(text(_DONE_FACTS_SQL), {"room": room_id}) or 0)
        stalls = 0 if after > done else stalls + 1
        done = after
        if stalls >= MAX_FACT_STALLS:
            raise SystemExit(
                f"사실 추출이 {MAX_FACT_STALLS}번 연속 진전 없음(완료 {done}/{len(state.snapshots)}) — 일부만 뽑힌 결과는 쓰지 않는다"
            )
    async with session_factory() as db:
        rows = await room_fact_rows(db, room_id)
    for row in rows:
        record = {**row, "factKind": row["kind"], "knownBy": row["known_by"], "kind": "fact"}
        del record["known_by"]
        _append(out_path, record)
    # 끝까지 돈 실행만 이 줄을 남긴다 — 지표는 이 줄이 없는 결과(상한·진전 없음으로 멈춘 것)를 거부한다.
    _append(out_path, {"kind": "done", "rows": len(rows)})
    return {"snapshots": len(state.snapshots), "extracted": done, "rows": len(rows)}


def read_result(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines or lines[0].get("kind") != "header":
        raise SystemExit(f"결과 파일 첫 줄이 머리 줄이 아니다: {path}")
    return lines[0], lines[1:]


# ---------------------------------------------------------------- 견적


def ledger_usage(rows: Sequence[Mapping[str, Any]], *, stage: str, call_site: str) -> dict[str, Any]:
    """투입 원장에서 그 단계·호출 위치의 호출 수와 평균 입력·출력 토큰(같은 접기 구간을 같은 모델로 부른 실측)."""
    picked = [r for r in rows if r.get("stage") == stage and r.get("callSite") == call_site]
    if not picked:
        raise SystemExit(f"투입 원장에 {stage} · {call_site} 줄이 없다 — 견적의 바탕이 없다")
    models = {str(r["model"]) for r in picked}
    if len(models) != 1:
        raise SystemExit(f"투입 원장의 {stage} · {call_site} 모델이 하나가 아니다: {sorted(models)}")
    n = len(picked)
    return {
        "calls": n,
        "meanInputTokens": sum(int(r["inputTokens"]) for r in picked) / n,
        "meanOutputTokens": sum(int(r["outputTokens"]) for r in picked) / n,
        "model": models.pop(),
    }


def dry_run_estimate(*, calls: int, usage: Mapping[str, Any], extra_input_chars: int, margin: float) -> dict[str, Any]:
    """호출 수 × (투입 실측 평균 입력 + 후보로 늘어나는 글자) · 평균 출력 → 단가표 USD × 여유 배수. 캐시는 없다고 본다."""
    price = price_for(str(usage["model"]))
    input_tokens = float(usage["meanInputTokens"]) + extra_input_chars * TOKENS_PER_CHAR
    output_tokens = float(usage["meanOutputTokens"])
    per_call = (
        (input_tokens * price.input_usd_per_million + output_tokens * price.output_usd_per_million) / 1_000_000 * margin
    )
    return {
        "calls": calls,
        "model": usage["model"],
        "inputTokensPerCall": input_tokens,
        "outputTokensPerCall": output_tokens,
        "margin": margin,
        "perCallUsd": per_call,
        "totalUsd": per_call * calls,
    }
