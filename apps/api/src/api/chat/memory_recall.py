"""매 턴 회상 — 방의 장면 기억(`chat_memory_episodes`)에서 이번 턴과 이어질 장면을 골라 생성 프롬프트의 회상 섹션에 싣는다.
LLM 을 부르지 않는다(DB 읽기 한두 번과 파이썬 점수).

질의: 키워드북과 같은 스캔 글(이번 턴 사용자 메시지, 그 앞의 가장 가까운 AI 응답)에서 장면 명사와 같은 규칙의 토큰
(`memory_nouns.rule_tokens` — 형태소기 없이 어절 끝 조사 하나를 뗀다)과, 방 장면의 1자 명사 중 어절 경계에 걸린 것을 뽑고
이름·불용어를 뺀다. 사용자 쪽은 그중 방 장면에 한 번이라도 나온 토큰만 남긴다 — 조사 떼기는 "그거·어디·뒀더라" 같은 어절도
토큰으로 남겨, 거르지 않으면 대명사 후속 질문의 사용자 질의가 비지 않는다.

어느 쪽으로 찾나: 사용자 질의가 남았으면 사용자 쪽. 비었고 시간 단서("그때·예전에·기억나" 등)가 있으면 직전 AI 응답 쪽에서
가장 최근 스냅샷 둘의 장면 낱말을 뺀 것("그때"는 지금 장면이 아니라 지난 일을 가리킨다). 그 밖은 회상하지 않는다. 사용자
질의가 흔한 명사로만 남았던 경우는 AI 쪽으로 가지 않고 회상 없음이다 — 사용자가 꺼낸 화제가 흔한 것일 뿐 앞 맥락을 가리킨
것이 아니다.

점수: 장면이 `MIN_EPISODES` 개 미만이면 회상하지 않는다(아래 비율 제외가 작은 N 에서 뜻을 잃는다). 명사 가중
`w = ln((N+1)/(df+1)) + 1`, 방 장면의 `COMMON_RATIO` 를 넘게 나오는 명사(인물 이름·무대처럼 대부분의 장면에 나오는 것)는
질의에서 뺀다. 주입 여부는 드문 명사(df 1) 하나를 1 로 둔 절대 척도(상한 1)에 중요도·최근성을 조금 더한 값이 `TAU` 이상인지로,
순위는 상한 없는 원점수로 정한다 — 상한 있는 값으로 순위를 매기면 드문 명사 하나와 셋을 가진 장면이 동점이 된다. 시간 단서가
있으면 최근성을 끈다. 주입은 되묻는 끝말까지 넓힌 회상 단서가 있는 턴에 셋, 그 밖의 턴에 하나다.

상수와 식은 평가 하네스의 시제품 구현을 개발 절반으로 맞춘 값이고, 이 모듈은 그 시제품과 같은 토큰·점수·순위·주입을 내야
한다 — 테스트가 하네스가 낸 기준 벡터(`tests/fixtures/memory_recall_vectors.json`)와 견준다. 이 모듈은 하네스를 import 하지
않는다.

후보는 지금 요약 커서까지 접힌 스냅샷에서 뽑혔고 커서 이하에서 끝나는 장면뿐이다 — 커서 뒤는 원문 윈도우로 이미 실린다.
읽기는 요청 세션의 SAVEPOINT 안이고, DB 오류든 그 밖의 예외든 경고·승격을 남기고 회상 없이 조립한다(생성 프롬프트 조립은
SSE 제너레이터 본문 안이라 예외가 새면 무관한 요청까지 500 이 된다)."""

import logging
import math
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Executable, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.keyword_notes import normalize_keyword_text, recent_scan_turns
from api.chat.memory_nouns import STOPWORDS, rule_tokens
from api.chat.memory_window import MessageKey, opening_message
from api.chat.prompt_builder import PromptNames
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import ChatMemoryEpisode, ChatMessage, ChatMessageRole, ChatRoomMemorySnapshot

logger = logging.getLogger(__name__)

TAU = 0.60
COMMON_RATIO = 0.2
MIN_EPISODES = 5
MAX_INJECT_RECALL_CUE = 3
MAX_INJECT_PLAIN = 1
W_NOUN = 0.7
W_IMPORTANCE = 0.05
W_RECENCY = 0.02

# 지난 일을 가리키는 낱말 — 직전 AI 응답으로 찾을지와 최근성을 끌지를 가른다.
TIME_CUE = re.compile(r"예전에|처음|지난번|저번|그때|옛날|전에\s|기억(나|해|하)")
# 회상을 묻는 턴 — 시간 단서에 되묻는 끝말("기억 안·뭐였·~였지?·~라고 했지·말한 적" 등)을 더했다. 이 턴만 셋까지 싣는다.
RECALL_CUE = re.compile(
    TIME_CUE.pattern
    + r"|기억\s?안|뭐였|뭐더라|(였|었)(지|더라)\s*[?？]|었더라|였더라|전에\s?말한|(라고|다고)\s?했(었)?지|(말|얘기|이야기)한\s?적"
)
# 1자 명사(빵·차·꽃)는 조사 떼기 토큰에 남지 않으므로 어절 경계 + 선택 조사로만 건다("빵집"의 빵은 걸리지 않는다).
_ONE_CHAR_PARTICLES = "이|가|을|를|은|는|도|만|에|에서|랑|이랑|하고|과|와|의"

# 장면을 말한 쪽(인물·섞임·사용자)을 밝히는 꼬리표이고 뜻은 회상 섹션 문안이 설명한다 — 서술 장면만 꼬리표가 없어서, 사용자
# 꼬리표가 없으면 사용자가 지어낸 말까지 일어난 일처럼 읽혀 생성 모델이 사실이나 인물의 말로 다룬다.
# 사실 섹션(`chat/memory_fact_section.py`)도 주장의 꼬리표로 같은 두 낱말을 쓴다 — 두 섹션 문안이 같은 꼬리표를 설명한다.
CHARACTER_ASSERTION_TAIL = " (인물의 말)"
USER_ASSERTION_TAIL = " (사용자의 말)"
_ASSERTION_TAILS = {"character": CHARACTER_ASSERTION_TAIL, "mixed": " (인물의 말 포함)", "user": USER_ASSERTION_TAIL}

RecallPath = Literal["user", "assistant"]


@dataclass(frozen=True)
class RecallQuery:
    """`user` 는 방 장면에 나온 사용자 메시지 토큰, `assistant` 는 직전 AI 응답 토큰에서 사용자 쪽을 뺀 것(방 장면에 없는
    토큰도 남는다 — 어차피 겹치지 않는다)."""

    user: frozenset[str]
    assistant: frozenset[str]
    time_cue: bool


@dataclass(frozen=True)
class RecallCandidate:
    """점수를 매길 장면 하나. `snapshot` 은 그 장면을 뽑은 스냅샷의 순번(클수록 최근)이다."""

    id: str
    nouns: frozenset[str]
    importance: int
    end_turn: int
    snapshot: int


@dataclass(frozen=True)
class ScoredEpisode:
    """`s` 는 주입 판정용(상한 있음), `r` 은 순위용(상한 없음)이다."""

    id: str
    s: float
    r: float
    overlap: frozenset[str]
    end_turn: int
    snapshot: int


@dataclass(frozen=True)
class Recall:
    """이번 턴의 회상 — 섹션에 실을 줄(없으면 `""`)과 턴 기록 칸에 남길 목록."""

    lines: str
    record: tuple[dict[str, Any], ...]


NO_RECALL = Recall("", ())


class RecallRecordMissingError(Exception):
    """턴 기록에 남은 장면이 지금 DB 에 없다(그 뒤 되감기로 지워졌다)."""


def time_cue(text: str) -> bool:
    return TIME_CUE.search(text) is not None


def recall_cue(text: str) -> bool:
    return RECALL_CUE.search(text) is not None


def _one_char_hits(nouns: Iterable[str], text: str) -> set[str]:
    return {
        noun
        for noun in nouns
        if re.search(rf"(^|\s){re.escape(noun)}({_ONE_CHAR_PARTICLES})?(\s|$|[.,!?…~])", text) is not None
    }


def query_tokens(
    user_text: str, previous_assistant: str, *, episode_nouns: frozenset[str], names: Iterable[str]
) -> RecallQuery:
    """`episode_nouns` 는 방 장면 명사 전부(1자 명사 경계 검사와 사용자 쪽 거르기에 쓴다), `names` 는 질의에서 뺄 이름이다.
    흔한 명사 제외는 점수 함수가 한다 — 흔한 명사만 꺼낸 질문은 여기서 비지 않아 AI 쪽으로 가지 않는다."""
    excluded = STOPWORDS | {normalize_keyword_text(name) for name in names}
    one_char = [noun for noun in episode_nouns if len(noun) == 1]

    def side(text: str) -> frozenset[str]:
        hits = set(rule_tokens(text)) | _one_char_hits(one_char, normalize_keyword_text(text))
        return frozenset(noun for noun in hits if noun and noun not in excluded)

    user = side(user_text) & episode_nouns
    return RecallQuery(user=user, assistant=side(previous_assistant) - user, time_cue=time_cue(user_text))


def query_path(query: RecallQuery) -> RecallPath | None:
    if query.user:
        return "user"
    return "assistant" if query.time_cue else None


def score_episodes(rows: Sequence[RecallCandidate], query: RecallQuery, *, current_turn: int) -> list[ScoredEpisode]:
    """모든 장면에 점수를 매겨 순위 순으로(원점수 내림차순, 같으면 끝 턴·스냅샷이 나중인 것) 돌려준다. 회상하지 않는 턴은
    빈 목록이다(장면 부족, 질의 없음, 흔한 명사를 빼고 나니 질의가 빔)."""
    n = len(rows)
    if n < MIN_EPISODES:
        return []
    df: dict[str, int] = {}
    for row in rows:
        for noun in row.nouns:
            df[noun] = df.get(noun, 0) + 1

    def kept(nouns: frozenset[str]) -> frozenset[str]:
        return frozenset(noun for noun in nouns if 0 < df.get(noun, 0) and df[noun] / n <= COMMON_RATIO)

    path = query_path(query)
    if path == "user":
        query_nouns = kept(query.user)
    elif path == "assistant":
        recent = sorted({row.snapshot for row in rows}, reverse=True)[:2]
        recent_nouns = frozenset(noun for row in rows if row.snapshot in recent for noun in row.nouns)
        query_nouns = kept(query.assistant - recent_nouns)
    else:
        return []
    if not query_nouns:
        return []

    w_rare = math.log((n + 1) / 2) + 1
    scored = []
    for row in rows:
        overlap = query_nouns & row.nouns
        weight = sum(math.log((n + 1) / (df[noun] + 1)) + 1 for noun in overlap)
        extra = W_IMPORTANCE * (min(max(row.importance, 1), 5) - 1) / 4
        if not query.time_cue:
            extra += W_RECENCY * row.end_turn / max(current_turn, 1)
        s = W_NOUN * min(1.0, weight / w_rare) + extra
        r = weight + w_rare * extra / W_NOUN
        scored.append(ScoredEpisode(row.id, s, r, overlap, row.end_turn, row.snapshot))
    scored.sort(key=lambda x: (-x.r, -x.end_turn, -x.snapshot, x.id))
    return scored


def select_injected(scored: Sequence[ScoredEpisode], *, recall_cue: bool) -> list[ScoredEpisode]:
    cap = MAX_INJECT_RECALL_CUE if recall_cue else MAX_INJECT_PLAIN
    return [row for row in scored if row.s >= TAU][:cap]


def recall_line(title: str, detail: str, asserted_by: str) -> str:
    return f"- {title}: {detail}{_ASSERTION_TAILS.get(asserted_by, '')}"


def _candidate_statement(room_id: uuid.UUID, cursor: MessageKey) -> Executable:
    """그 방에서 지금 커서까지 접힌 스냅샷이 뽑았고 커서 이하에서 끝나는 장면(점수에 필요한 칸만)과 그 스냅샷의 커서. 방
    조건 인덱스(`ix_chat_memory_episodes_room_end`)를 탄다. 이 읽기는 대화 길이에 따라 선형으로 는다."""
    episode, snapshot = ChatMemoryEpisode, ChatRoomMemorySnapshot
    return (
        select(
            episode.id,
            episode.nouns,
            episode.importance,
            episode.end_turn,
            snapshot.cursor_created_at,
            snapshot.cursor_message_id,
        )
        .join(snapshot, snapshot.id == episode.snapshot_id)
        .where(
            episode.chat_room_id == room_id,
            tuple_(episode.end_created_at, episode.end_message_id) <= cursor,
            tuple_(snapshot.cursor_created_at, snapshot.cursor_message_id) <= cursor,
        )
        .order_by(episode.end_created_at, episode.end_message_id)
    )


async def _render(db: AsyncSession, ids: Sequence[uuid.UUID]) -> list[tuple[uuid.UUID, str]]:
    """장면 id 들의 줄을 일어난 순서(끝 키 오름차순)로. 없는 id 는 결과에서 빠진다."""
    rows = (
        await db.execute(
            select(
                ChatMemoryEpisode.id, ChatMemoryEpisode.title, ChatMemoryEpisode.detail, ChatMemoryEpisode.asserted_by
            )
            .where(ChatMemoryEpisode.id.in_(ids))
            .order_by(ChatMemoryEpisode.end_created_at, ChatMemoryEpisode.end_message_id)
        )
    ).all()
    return [(row.id, recall_line(row.title, row.detail, row.asserted_by)) for row in rows]


async def _recall(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    history: Sequence[ChatMessage],
    window: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
) -> Recall:
    rows = (await db.execute(_candidate_statement(room_id, cursor))).all()
    if len(rows) < MIN_EPISODES:
        return NO_RECALL
    snapshot_order = {key: rank for rank, key in enumerate(sorted({(row[4], row[5]) for row in rows}))}
    candidates = [
        RecallCandidate(
            id=str(row[0]),
            nouns=frozenset(row[1]),
            importance=row[2],
            end_turn=row[3],
            snapshot=snapshot_order[(row[4], row[5])],
        )
        for row in rows
    ]
    scan = recent_scan_turns(window, user_content, 0, names=names)[0]
    user_text = "\n".join(scan.user_texts)
    query = query_tokens(
        user_text,
        scan.assistant_text,
        episode_nouns=frozenset(noun for candidate in candidates for noun in candidate.nouns),
        names=[name for name in (names.persona_name, names.char_name) if name],
    )
    # 이번 턴 번호 — 오프닝을 뺀 어시스턴트 메시지 수 + 1. 장면의 끝 턴과 같은 셈이다.
    opening = opening_message(history)
    current_turn = 1 + sum(1 for m in history if m.role == ChatMessageRole.ASSISTANT and m is not opening)
    scored = score_episodes(candidates, query, current_turn=current_turn)
    injected = select_injected(scored, recall_cue=recall_cue(user_text))
    if not injected:
        return NO_RECALL
    lines = dict(await _render(db, [uuid.UUID(row.id) for row in injected]))
    # 두 읽기 사이에 되감기가 커밋돼 사라진 장면은 싣지 않는다.
    injected = [row for row in injected if uuid.UUID(row.id) in lines]
    if not injected:
        return NO_RECALL
    path = query_path(query)
    ranks = {row.id: rank for rank, row in enumerate(scored, start=1)}
    record = tuple(
        {
            "episodeId": row.id,
            "score": row.s,
            "rank": ranks[row.id],
            "chars": len(lines[uuid.UUID(row.id)]),
            "path": path,
        }
        for row in injected
    )
    return Recall("\n".join(lines.values()), record)


async def recall_for_turn(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    cursor: MessageKey,
    history: Sequence[ChatMessage],
    window: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
) -> Recall:
    """이번 턴의 회상. `history` 는 방의 전체 대화(턴 번호를 센다), `window` 는 이번 생성 프롬프트에 실리는 대화(스캔 글을
    뽑는다), `cursor` 는 지금 요약 커서다. 무엇이 실패하든 회상 없음이다 — 이 함수는 SSE 제너레이터 본문 안에서 불려 예외가
    새면 무관한 요청까지 500 이 된다. 읽기를 SAVEPOINT 로 감싸 실패한 문장이 요청 세션의 트랜잭션을 망가뜨리지 않게 하고(DB
    실패), 토큰화·점수에서 난 예외도 같은 자리에서 받는다(커밋 뒤 조회를 흡수하는 `turn_store.present` 와 같은 규칙). 경고에
    스택을 싣는다. 취소(`CancelledError`)는 `Exception` 이 아니라 그대로 올라간다."""
    try:
        async with db.begin_nested():
            return await _recall(
                db,
                room_id=room_id,
                cursor=cursor,
                history=history,
                window=window,
                user_content=user_content,
                names=names,
            )
    except Exception as exc:
        logger.warning(
            "대화방 %s 장면 기억 회상을 읽지 못해 이번 턴은 회상 없이 조립한다: %s", room_id, exc, exc_info=True
        )
        capture_dependency_failure(exc, dependency="db" if isinstance(exc, SQLAlchemyError) else "memory_recall")
        return NO_RECALL


async def recall_lines_from_record(db: AsyncSession, record: Sequence[dict[str, Any]]) -> str:
    """턴 기록(`chat_turns.memory_recall`)의 장면을 그 턴과 같은 줄로 다시 렌더한다 — 지금 장면으로 다시 찾으면 그 사이 늘어난
    장면 때문에 다른 글이 된다. 기록한 장면 중 하나라도 없으면 `RecallRecordMissingError`."""
    if not record:
        return ""
    ids = [uuid.UUID(str(entry["episodeId"])) for entry in record]
    rendered = await _render(db, ids)
    missing = sorted(set(ids) - {episode_id for episode_id, _ in rendered})
    if missing:
        raise RecallRecordMissingError(f"턴 기록의 장면이 지금 없다: {[str(episode_id) for episode_id in missing]}")
    return "\n".join(line for _, line in rendered)
