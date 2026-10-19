import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.moderation import ReportStatus
from api.db.models.payment import _sql_in_list
from api.db.types import HalfVec


class ChatMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatRoom(Base):
    """Pinned to the content_version it was created against
    (기획 요구: "이미 생성된 대화방은 생성 시점 버전에 고정")."""

    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    starting_setup_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    ending_reached: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    ending_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ending_reached_at_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_auto_upgraded: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 방이 고른 대화 프로필 — **참조**다(스냅샷 아님).
    # NULL이 "선택 없음"이고 그때 생성 프롬프트는 현행과 바이트까지 같다. 프로필을
    # 지우면 호출부가 이 값을 NULL로 먼저 끊는다(`ondelete` 없음).
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user_personas.id", name="fk_chat_rooms_persona_id"), nullable=True
    )
    # 사용자가 직접 쓰는 기억 노트. 요약을 만드는 코드는 이 컬럼을 쓰지 않는다 — LLM이 고쳐 쓰지
    # 못하는 칸이라는 약속이 이 분리로만 지켜진다. 방과 함께 사라지고 새 방에 승계하지 않는다.
    memory_note: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    # 요약 쪽 상태(스냅샷)가 바뀔 때마다 1씩 오르는 방 단위 카운터. 백그라운드 요약 커밋과 사용자
    # 요약 편집은 읽을 때의 값이 그대로일 때만 쓰고, 되감기·초기화·삭제는 무조건 올려 그 사이
    # 진행 중이던 요약을 무효로 만든다. 노트 저장은 올리지 않는다(노트 저장이 요약 편집을 충돌로
    # 만들지 않게).
    memory_version: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # 메시지 편집·삭제로 요약 스냅샷이 실제로 한 행 이상 지워진 마지막 시각. 기억 패널이 "요약이
    # 되돌아갔다"는 알림을 한 번 띄우는 기준이다. 초기화는 되감기 안내 대상이 아니라 NULL로 둔다.
    memory_rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 방이 고른 글쓰기 모델의 레지스트리 id(`llm/chat_models.py`). NULL 이 기본 모델(Gemini)이다. 값 제약을 두지 않는다 —
    # 레지스트리에서 내린 모델의 옛 값이 남아도 행이 살아 있어야 하고, 그 값은 턴마다 쓸 수 있는 모델로 다시 판정한다
    # (`llm/model_access.py` 의 `effective_room_model`). 바꾸는 경로는 `PUT /chat-rooms/{id}/model` 하나다.
    chat_model: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 프로필 삭제의 `UPDATE chat_rooms SET persona_id=NULL WHERE persona_id=…`가 전체
    # 스캔이 되지 않게 한다. Postgres 는 FK 열에 인덱스를 자동으로 만들지 않으므로
    # `user_id`·`content_id` 도 직접 건다. 같은 작품의 내 방들(방 응답·작품 접근 판정)은
    # 두 열을 함께 거르고 내 방 목록·탈퇴는 `user_id` 만 거르므로 앞 열이 `user_id` 인
    # 복합 하나로 둘 다 받는다. 작품 하나의 방 전부를 고치는 버전 일괄 승격은
    # `content_id` 만 거르므로 단일 인덱스를 따로 둔다.
    __table_args__ = (
        Index("ix_chat_rooms_persona_id", "persona_id"),
        Index("ix_chat_rooms_user_id_content_id", "user_id", "content_id"),
        Index("ix_chat_rooms_content_id", "content_id"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    role: Mapped[ChatMessageRole] = mapped_column(
        Enum(ChatMessageRole, name="chat_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 메시지 순서는 이 값 하나로 정한다. `now()`는 트랜잭션 시작 시각이라 한 트랜잭션에 넣은
    # 메시지들이 같은 값을 갖고 순서가 힙의 물리 위치에 맡겨진다 — 문장 실행 시각을 쓴다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
    # 이미지 판정 결과의 entity_id — 캐릭터 방이면 상황별 이미지, 스토리 방이면 미디어 북 칸의
    # entity_id 다. assistant 메시지에만 채워진다. FK 없음 — entity_id는 버전 간 복제돼 유니크가
    # 아니고, 방 종류에 따라 가리키는 테이블도 달라 형제 컬럼과 같은 다형 참조 관례를 따른다.
    image_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # 장면 헤더를 켠 스토리 방의 AI 응답에만 채우는 그 턴의 장면 `{"place": str|null, "time": str|null}` — 판정이 적은 값에
    # 언급이 없던 칸은 직전 장면을 이어받아 채운다. 장면 헤더가 꺼진 작품·켜기 전 메시지·사용자 메시지·오프닝은 null 이다.
    # 화면 표시 전용이라 생성 프롬프트에 싣지 않는다.
    scene: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # 턴마다의 히스토리 로드·방 조회·방 목록의 마지막 메시지가 전부 "한 방의 메시지를 `(created_at, id)` 순으로"
    # 찾는다. 없으면 그 조회마다 플랫폼 전체 메시지를 순차 스캔한다(FK 는 Postgres 에서 인덱스를 만들지 않는다).
    __table_args__ = (Index("ix_chat_messages_chat_room_id_created_at_id", "chat_room_id", "created_at", "id"),)


class ChatRoomMemorySnapshot(Base):
    """방의 롤링 요약 한 판. 윈도우 밖으로 접힌 대화를 요약한 텍스트와, 그 요약이 덮는 마지막
    메시지의 키(커서)를 함께 둔다. 방마다 여러 행이 쌓이고 커서가 가장 큰 행이 현재 요약이다.

    커서는 메시지 정렬과 같은 `(created_at, id)` 튜플이다 — `created_at`이 같은 메시지가 있어도
    경계가 한 메시지로 정해진다. `cursor_message_id`에 FK를 걸지 않는다: 커서 이하 메시지를
    지우는 경로(편집·삭제·재생성·초기화·방 삭제·탈퇴)는 같은 트랜잭션에서 이 행부터 지워야 하고,
    그러면 가리킬 메시지가 사라진 행은 남지 않는다.

    `previous_text`는 사용자가 이 행의 요약을 고쳤을 때 고치기 직전 값이고(되돌리기 한 단계),
    `previous_source`는 그 값의 출처다 — AI가 접은 요약을 고쳤다 되돌리면 다시 AI 요약으로 보인다.
    둘은 함께 채워지고 함께 비워진다.
    `source`는 `"auto"`(요약 호출이 만든 행)·`"user"`(사용자가 고친 행)뿐이고 Postgres ENUM이
    아니라 Text다 — 허용값은 이 행을 쓰는 코드와 응답 스키마가 강제한다.

    `relationship()`·`ondelete`는 선언하지 않는다(저장소 규약) — 위 경로들이 이 행을 직접
    지운다. 이 행을 지우면 그 접기에서 뽑은 장면 기억(`ChatMemoryEpisode`)과 추출 기록
    (`ChatMemoryExtraction`)은 그 두 테이블 쪽 `ON DELETE CASCADE`로 함께 지워진다.
    사실 기억(`ChatMemoryFact`)과 그 추출 기록(`ChatMemoryFactExtraction`)도 같은 CASCADE 로 함께 지워진다.
    """

    __tablename__ = "chat_room_memory_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    cursor_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cursor_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 현재 요약(커서 최대 행)과 되감기의 "커서 ≥ 지운 메시지 키" 삭제가 전부 이 순서로 찾는다.
    __table_args__ = (
        Index(
            "ix_chat_room_memory_snapshots_room_cursor",
            "chat_room_id",
            "cursor_created_at",
            "cursor_message_id",
        ),
    )


EpisodeAssertedBy = Literal["user", "character", "narration", "mixed"]
EpisodeExtractionStatus = Literal["running", "done", "failed"]

# 장면 기억 칸의 상한. CHECK 와 추출 결과를 자르는 쪽이 같은 상수를 쓴다 — 값이 갈리면 잘라 낸 행이 CHECK 에 막힌다.
EPISODE_TITLE_MAX = 60
EPISODE_DETAIL_MAX = 300
EPISODE_NOUNS_MAX = 30
EPISODE_KEYWORDS_MAX = 8
EPISODE_EVIDENCE_MAX = 2
# 인물 이름 하나와 아는 사람 목록의 상한. 사실 기억과 장면 기억의 `known_by` 가 같은 규칙을 쓰도록 한 상수를 함께 쓴다.
FACT_NAME_MAX = 60
FACT_KNOWN_BY_MAX = 10


class ChatMemoryEpisode(Base):
    """요약 접기 한 번이 접은 대화 구간 안의 장면 하나. 한 번 쓰면 고쳐 쓰지 않는다 — 낡은 기억은 지우지 않고 검색
    순위로만 밀린다.

    그 접기의 스냅샷이 지워지면(편집·삭제·재생성·초기화·방 삭제·탈퇴의 되감기) DB 가 이 행도 함께 지운다. 이 저장소의
    "`ON DELETE CASCADE` 없음" 규약의 예외인 이유는 둘이다.
    - 이 테이블을 모르는 옛 이미지(배포 겹침·이미지 롤백)가 스냅샷을 지울 때 FK 위반으로 실패하지 않게 한다.
    - 새 코드도 이 행을 따로 지우지 않고 CASCADE 에 맡긴다. 되감기가 이 테이블·추출 기록을 스냅샷보다 먼저 지우면,
      스냅샷을 잠근 채 추출 기록을 갱신하려는 추출 작업과 서로를 기다린다(교착). 지우는 쪽도 추출 쪽도 스냅샷을 먼저
      잡아야 한 방향으로만 줄을 선다.

    칸:
    - `start_*`·`end_*` 는 이 장면이 덮는 원문의 처음·마지막 메시지 키다. 메시지 정렬과 같은 `(created_at, id)` 모양이고,
      메시지 id 에 FK 가 없는 이유는 스냅샷 커서와 같다(그 메시지를 지우는 경로가 이 행을 먼저 없앤다).
    - `start_turn`·`end_turn` 은 추출 시점의 어시스턴트 메시지 순번이다 — 그 뒤 메시지가 지워지면 근사값이 된다.
    - `nouns` 는 검색에 쓰는 정규화된 명사, `keywords` 는 짧은 핵심 구절, `evidence` 는 원문에서 옮긴 짧은 근거다.
    - `asserted_by` 는 장면의 사실을 누가 말했는가다: 사용자 본인(`user`), 캐릭터(`character` — 캐릭터가 사용자에 대해
      지어낸 말을 사실로 회상하지 않게 구별한다), 서술(`narration`), 섞임(`mixed`).
    - `known_by` 는 이 장면을 아는 인물 이름 목록이고 뜻과 규칙은 `ChatMemoryFact` 의 같은 칸과 같다(NULL 은 공개이거나
      알 수 없음, 빈 배열은 쓰지 않는다). 장면 추출이 결과의 같은 칸을 사실 행과 같은 규칙으로 잘라 채운다.
    - `importance` 는 1~5, `ordinal` 은 그 접기 안의 장면 순서(0부터)다.
    `asserted_by` 는 native enum 이 아니라 Text 이고 위 Literal 이 값 범위다."""

    __tablename__ = "chat_memory_episodes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_room_memory_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    end_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    start_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    end_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    nouns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    evidence: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    asserted_by: Mapped[EpisodeAssertedBy] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    known_by: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 아래 CHECK 의 검증은 행위 테스트가 유일하다.
    # 유니크의 앞 열(`snapshot_id`)이 스냅샷 DELETE 의 CASCADE 가 이 테이블을 찾는 인덱스를 겸한다. 방 인덱스는 한 방의
    # 장면을 원문 순서로 읽는 검색과, 방 DELETE 의 FK 확인을 받는다.
    # `known_by` 의 두 CHECK 는 `ChatMemoryFact` 의 것과 같은 식이다(원소 검사가 제어 문자 U+001F 로 이어 붙인 문자열을
    # 보는 이유도 그쪽 주석과 같다).
    __table_args__ = (
        UniqueConstraint("snapshot_id", "ordinal", name="ux_chat_memory_episodes_snapshot_ordinal"),
        CheckConstraint(
            f"asserted_by IN ({_sql_in_list(EpisodeAssertedBy)})", name="ck_chat_memory_episodes_asserted_by"
        ),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_chat_memory_episodes_importance"),
        CheckConstraint("ordinal >= 0", name="ck_chat_memory_episodes_ordinal"),
        CheckConstraint("start_turn <= end_turn", name="ck_chat_memory_episodes_turn_order"),
        CheckConstraint(
            "(start_created_at, start_message_id) <= (end_created_at, end_message_id)",
            name="ck_chat_memory_episodes_range_order",
        ),
        CheckConstraint(
            f"char_length(title) BETWEEN 1 AND {EPISODE_TITLE_MAX}", name="ck_chat_memory_episodes_title_length"
        ),
        CheckConstraint(
            f"char_length(detail) BETWEEN 1 AND {EPISODE_DETAIL_MAX}", name="ck_chat_memory_episodes_detail_length"
        ),
        CheckConstraint(f"cardinality(nouns) <= {EPISODE_NOUNS_MAX}", name="ck_chat_memory_episodes_nouns_count"),
        CheckConstraint(
            f"cardinality(keywords) <= {EPISODE_KEYWORDS_MAX}", name="ck_chat_memory_episodes_keywords_count"
        ),
        CheckConstraint(
            f"cardinality(evidence) <= {EPISODE_EVIDENCE_MAX}", name="ck_chat_memory_episodes_evidence_count"
        ),
        CheckConstraint(
            f"cardinality(known_by) BETWEEN 1 AND {FACT_KNOWN_BY_MAX}", name="ck_chat_memory_episodes_known_by_count"
        ),
        CheckConstraint(
            "array_position(known_by, NULL) IS NULL"
            f" AND array_to_string(known_by, E'\\x1F') !~ '[^\\x1F]{{{FACT_NAME_MAX + 1}}}'",
            name="ck_chat_memory_episodes_known_by_items",
        ),
        Index("ix_chat_memory_episodes_room_end", "chat_room_id", "end_created_at", "end_message_id"),
    )


class ChatMemoryExtraction(Base):
    """스냅샷 하나의 장면 기억 추출 기록 — 한 스냅샷 = 한 행. 세 가지를 겸한다.
    - 아직 뽑지 않은 스냅샷의 표지: 행이 없으면 미추출이다.
    - 같은 스냅샷을 두 작업이 동시에 뽑지 않게 하는 선점: PK 가 `snapshot_id` 다.
    - 추출 호출 원가: 모델 id 와 토큰(`prompt_tokens` 는 캐시 포함 입력 전체 — 사용량 기록과 같은 뜻).

    스냅샷과 함께 지워진다(`ChatMemoryEpisode` 와 같은 이유 — 옛 이미지의 스냅샷 DELETE, 그리고 교착).
    `status` 는 `running`(작업이 쥠)·`done`(끝남 — 그때만 `episode_count` 가 있다)·`failed`(실패 — 재시도 대상)이고,
    native enum 이 아니라 Text 다. `attempts` 는 선점할 때마다 센다."""

    __tablename__ = "chat_memory_extractions"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_room_memory_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    status: Mapped[EpisodeExtractionStatus] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thoughts_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 아래 CHECK 의 검증은 행위 테스트가 유일하다.
    # 방 인덱스는 방 DELETE 의 FK 확인이 이 테이블을 방으로 찾기 위한 것이다(Postgres 는 FK 열에 인덱스를 만들지 않는다).
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_in_list(EpisodeExtractionStatus)})", name="ck_chat_memory_extractions_status"
        ),
        CheckConstraint("attempts >= 1", name="ck_chat_memory_extractions_attempts"),
        CheckConstraint(
            "(status = 'done') = (episode_count IS NOT NULL)", name="ck_chat_memory_extractions_done_count"
        ),
        Index("ix_chat_memory_extractions_room", "chat_room_id"),
    )


FactKind = Literal["relation", "fact"]
FactTruthStatus = Literal["confirmed", "claimed", "disproved"]
FactAssertedBy = Literal["user", "character", "narration"]
# 사실 추출 기록은 장면 추출 기록과 같은 상태 흐름을 쓴다.
FactExtractionStatus = EpisodeExtractionStatus

# 사실 기억 칸의 DB 상한. 추출 결과를 자르는 쪽은 이 값 이하로 잘라야 한다 — 넘기면 잘라 낸 행이 CHECK 에 막힌다.
# 인물 이름 상한과 아는 사람 수 상한(`FACT_NAME_MAX`·`FACT_KNOWN_BY_MAX`)은 장면 기억 앞에 있다.
FACT_VALUE_MAX = 200
FACT_KEY_MAX = 200
# 한 접기에서 뽑는 사실 행의 상한이자 `ordinal` 의 범위(0 이상 이 값 미만)다.
FACT_PER_SNAPSHOT_MAX = 20


class ChatMemoryFact(Base):
    """요약 접기 한 번이 접은 대화 구간에서 뽑은 사실 하나 — 인물 사이의 관계 또는 인물의 속성. 한 번 쓰면 고쳐 쓰지
    않는다 — 같은 `fact_key` 의 새 행이 뒤에 쌓이고, 무엇이 지금 유효한지는 읽는 쪽이 원문 순서로 정한다.

    그 접기의 스냅샷이 지워지면 DB 가 이 행도 함께 지운다(`ON DELETE CASCADE`). 이유는 `ChatMemoryEpisode` 와 같다 — 이
    테이블을 모르는 옛 이미지의 스냅샷 DELETE 가 FK 위반으로 실패하지 않게 하고, 새 코드도 이 행을 스냅샷보다 먼저 지우지
    않아 스냅샷을 잠근 추출 작업과 교착하지 않는다.

    칸:
    - `kind` 가 `relation` 이면 `subject` 와 `object` 사이의 관계이고 `attribute` 는 비어 있다. `fact` 이면 `subject` 의
      `attribute` 이고 `object` 는 비어 있다. `value` 는 그 관계·속성의 값이다.
    - `fact_key` 는 서버가 종류·주어·대상·속성을 정규화해 만든 키다 — 같은 사실의 갱신을 같은 키로 묶는다.
    - `truth_status` 는 확인됨(`confirmed`)·주장됨(`claimed` — 말한 사람만 그렇다고 한 것)·반박됨(`disproved`)이다.
    - `asserted_by` 는 누가 이 사실을 내놨는가(사용자·캐릭터·서술), `speaker` 는 그 말을 한 인물 이름이다(없으면 NULL).
    - `known_by` 는 이 사실을 아는 인물 이름 목록이다. NULL 은 공개이거나 알 수 없다는 뜻이고, 빈 배열은 쓰지 않는다 —
      "아무도 모른다"와 "모른다"를 둘로 나누지 않고 NULL 하나로 둔다.
    - `start_*`·`end_*`·`start_turn`·`end_turn` 은 장면 기억의 같은 칸과 같은 뜻이다(근거 원문의 처음·마지막 메시지 키와
      추출 시점의 어시스턴트 메시지 순번).
    - `importance` 는 1~5, `ordinal` 은 그 접기 안의 사실 순서(0부터, 한 접기에 최대 20행)다.
    `kind`·`truth_status`·`asserted_by` 는 native enum 이 아니라 Text 이고 위 Literal 이 값 범위다."""

    __tablename__ = "chat_memory_facts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_room_memory_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[FactKind] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    object: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribute: Mapped[str | None] = mapped_column(Text, nullable=True)
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    truth_status: Mapped[FactTruthStatus] = mapped_column(Text, nullable=False)
    asserted_by: Mapped[FactAssertedBy] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(Text, nullable=True)
    known_by: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    end_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    start_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    end_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 아래 CHECK 의 검증은 행위 테스트가 유일하다.
    # 유니크의 앞 열(`snapshot_id`)이 스냅샷 DELETE 의 CASCADE 가 이 테이블을 찾는 인덱스를 겸한다. 방 인덱스는 한 방의
    # 사실을 원문 순서로 읽는 조회와, 방 DELETE 의 FK 확인을 받는다.
    # `known_by` 원소 검사는 CHECK 에 하위 질의를 쓸 수 없어서, 원소를 제어 문자 U+001F 로 이어 붙인 문자열에 구분자 없이
    # 61자가 이어지는 구간이 없는지로 본다(원소 안에 그 제어 문자가 들어 있으면 이 검사를 빠져나간다).
    __table_args__ = (
        UniqueConstraint("snapshot_id", "ordinal", name="ux_chat_memory_facts_snapshot_ordinal"),
        CheckConstraint(f"kind IN ({_sql_in_list(FactKind)})", name="ck_chat_memory_facts_kind"),
        CheckConstraint(
            "(kind = 'relation' AND object IS NOT NULL AND attribute IS NULL)"
            " OR (kind = 'fact' AND object IS NULL AND attribute IS NOT NULL)",
            name="ck_chat_memory_facts_kind_columns",
        ),
        CheckConstraint(
            f"truth_status IN ({_sql_in_list(FactTruthStatus)})", name="ck_chat_memory_facts_truth_status"
        ),
        CheckConstraint(f"asserted_by IN ({_sql_in_list(FactAssertedBy)})", name="ck_chat_memory_facts_asserted_by"),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_chat_memory_facts_importance"),
        CheckConstraint(
            f"ordinal >= 0 AND ordinal < {FACT_PER_SNAPSHOT_MAX}", name="ck_chat_memory_facts_ordinal"
        ),
        CheckConstraint("start_turn <= end_turn", name="ck_chat_memory_facts_turn_order"),
        CheckConstraint(
            "(start_created_at, start_message_id) <= (end_created_at, end_message_id)",
            name="ck_chat_memory_facts_range_order",
        ),
        CheckConstraint(
            f"char_length(subject) BETWEEN 1 AND {FACT_NAME_MAX}", name="ck_chat_memory_facts_subject_length"
        ),
        CheckConstraint(
            f"char_length(object) BETWEEN 1 AND {FACT_NAME_MAX}", name="ck_chat_memory_facts_object_length"
        ),
        CheckConstraint(
            f"char_length(attribute) BETWEEN 1 AND {FACT_NAME_MAX}", name="ck_chat_memory_facts_attribute_length"
        ),
        CheckConstraint(
            f"char_length(speaker) BETWEEN 1 AND {FACT_NAME_MAX}", name="ck_chat_memory_facts_speaker_length"
        ),
        CheckConstraint(
            f"char_length(value) BETWEEN 1 AND {FACT_VALUE_MAX}", name="ck_chat_memory_facts_value_length"
        ),
        CheckConstraint(
            f"char_length(fact_key) BETWEEN 1 AND {FACT_KEY_MAX}", name="ck_chat_memory_facts_fact_key_length"
        ),
        CheckConstraint(
            f"cardinality(known_by) BETWEEN 1 AND {FACT_KNOWN_BY_MAX}", name="ck_chat_memory_facts_known_by_count"
        ),
        CheckConstraint(
            "array_position(known_by, NULL) IS NULL"
            f" AND array_to_string(known_by, E'\\x1F') !~ '[^\\x1F]{{{FACT_NAME_MAX + 1}}}'",
            name="ck_chat_memory_facts_known_by_items",
        ),
        Index("ix_chat_memory_facts_room_end", "chat_room_id", "end_created_at", "end_message_id"),
    )


class ChatMemoryFactExtraction(Base):
    """스냅샷 하나의 사실 기억 추출 기록 — 한 스냅샷 = 한 행. `ChatMemoryExtraction` 과 같은 모양이고 같은 세 가지(미추출
    표지·선점·호출 원가)를 겸한다. 장면 추출과 따로 두어 한쪽이 실패해도 다른 쪽의 완료 표지가 흔들리지 않는다.

    스냅샷과 함께 지워진다(`ChatMemoryEpisode` 와 같은 이유 — 옛 이미지의 스냅샷 DELETE, 그리고 교착).
    `status` 는 `running`·`done`(그때만 `fact_count` 가 있다)·`failed` 이고, native enum 이 아니라 Text 다.
    `attempts` 는 선점할 때마다 센다."""

    __tablename__ = "chat_memory_fact_extractions"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_room_memory_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    status: Mapped[FactExtractionStatus] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thoughts_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fact_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 아래 CHECK 의 검증은 행위 테스트가 유일하다.
    # 방 인덱스는 방 DELETE 의 FK 확인이 이 테이블을 방으로 찾기 위한 것이다(Postgres 는 FK 열에 인덱스를 만들지 않는다).
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_in_list(FactExtractionStatus)})", name="ck_chat_memory_fact_extractions_status"
        ),
        CheckConstraint("attempts >= 1", name="ck_chat_memory_fact_extractions_attempts"),
        CheckConstraint(
            "(status = 'done') = (fact_count IS NOT NULL)", name="ck_chat_memory_fact_extractions_done_count"
        ),
        Index("ix_chat_memory_fact_extractions_room", "chat_room_id"),
    )


# pgvector 의 halfvec 이 담을 수 있는 최대 차원.
EMBEDDING_DIMS_MAX = 16000


class ChatMemoryEmbedding(Base):
    """장면 기억 한 행 또는 사실 기억 한 행의 임베딩 하나 — (대상 행, 모델, 차원)마다 한 행. INSERT 만 하고 고쳐 쓰지
    않는다. 모델이나 차원을 바꿔 다시 임베딩하면 새 행이 쌓이고, 읽는 쪽은 늘 지금 모델·차원으로 거른다.

    장면·사실 행에 칸을 두지 않고 따로 둔 이유: 두 테이블의 행은 한 번 쓰면 고쳐 쓰지 않는다. 같은 행에 임베딩 칸을 두고
    나중에 채우거나 모델을 바꿔 다시 채우면 그 행의 UPDATE 가 생긴다. 이 표는 INSERT 만으로 채우고, 장면·사실 행의 렌더
    줄은 그대로다.

    대상 행이 지워지면 DB 가 이 행도 함께 지운다(두 FK 모두 `ON DELETE CASCADE`). 되감기·초기화·방 삭제·탈퇴는 요약
    스냅샷을 지우고, 스냅샷 DELETE 의 CASCADE 가 장면·사실 행을, 그 CASCADE 가 다시 이 행을 지운다 — 새 삭제 문장이 없다.
    이 표를 모르는 옛 이미지(배포 겹침·이미지 롤백)의 스냅샷 DELETE 도 FK 위반 없이 끝난다. 방 FK 는 CASCADE 가 아니다 —
    방 DELETE 앞에 스냅샷 DELETE 가 이 행을 이미 지웠다.

    칸:
    - `episode_id`·`fact_id` 는 대상 행이고 정확히 하나만 채운다.
    - `model` 은 임베딩 모델 id, `dims` 는 벡터 차원이다.
    - `embedding` 은 차원을 적지 않은 `halfvec` 이다 — 모델·차원을 바꿔도 마이그레이션이 다시 필요 없다. 대신 차원이 섞인
      행에 거리 연산을 걸면 질의째 실패하므로 읽는 쪽은 늘 `model = 지금 모델 AND dims = 지금 차원` 으로 거르고, `dims`
      칸이 실제 벡터 차원과 같다는 것은 CHECK 가 지킨다.
    인덱스를 쓰지 않는 방 단위 정확 탐색을 전제로 한다(차원 없는 칸에는 HNSW 를 바로 만들 수 없다)."""

    __tablename__ = "chat_memory_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_memory_episodes.id", ondelete="CASCADE"), nullable=True
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_memory_facts.id", ondelete="CASCADE"), nullable=True
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    dims: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(HalfVec(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 아래 CHECK 의 검증은 행위 테스트가 유일하다.
    # 두 유니크는 대상 칸이 NULL 인 행끼리는 겹치지 않으므로 장면·사실 각각의 (대상 행, 모델, 차원)을 지키고, 앞 열이 대상
    # 행 DELETE 의 CASCADE 가 이 표를 찾는 인덱스를 겸한다. 방 인덱스는 방 단위 탐색과 방 DELETE 의 FK 확인을 받는다.
    __table_args__ = (
        UniqueConstraint("episode_id", "model", "dims", name="ux_chat_memory_embeddings_episode_model_dims"),
        UniqueConstraint("fact_id", "model", "dims", name="ux_chat_memory_embeddings_fact_model_dims"),
        CheckConstraint("num_nonnulls(episode_id, fact_id) = 1", name="ck_chat_memory_embeddings_one_target"),
        CheckConstraint(f"dims BETWEEN 1 AND {EMBEDDING_DIMS_MAX}", name="ck_chat_memory_embeddings_dims"),
        CheckConstraint("vector_dims(embedding) = dims", name="ck_chat_memory_embeddings_dims_match"),
        Index("ix_chat_memory_embeddings_room_model_dims", "chat_room_id", "model", "dims"),
    )


class ChatRoomStat(Base):
    """The chat room's current value for a stat_defs entity_id
    (referenced by entity_id, not id, so it keeps matching across a version switch)."""

    __tablename__ = "chat_room_stats"

    chat_room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id"), primary_key=True
    )
    stat_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class StoryEndingUnlock(Base):
    """엔딩 컬렉션: accumulates per user+starting_setup,
    never deleted/replaced once a row exists for a given ending."""

    __tablename__ = "story_ending_unlocks"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    starting_setup_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    ending_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_reached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CharacterImageExposure(Base):
    """이미지 보관함: accumulates per user+character,
    never revoked — not when the message that exposed the image is regenerated, edited or
    deleted, and not on room reset or deletion. No code path deletes these rows; the
    room-scoped state that IS torn down is ChatRoomStat."""

    __tablename__ = "character_image_exposures"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    image_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_exposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StoryMediaExposure(Base):
    """스토리 미디어 북 보관함: 사용자 + 스토리별로 대화에 나온 칸을 쌓는다. `CharacterImageExposure`
    와 같은 규칙 — 그 칸을 노출한 메시지를 재생성·편집·삭제해도, 방을 초기화하거나 지워도 행을
    지우지 않는다.

    `cell_entity_id` 는 칸의 entity_id 이고 FK 가 없다 — 칸 행은 버전마다 복제돼 entity_id 가
    유일하지 않고, 버전이 바뀌어도 같은 칸으로 쌓여야 한다."""

    __tablename__ = "story_media_exposures"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    cell_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_exposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


ChatTurnKind = Literal["send", "edit", "regenerate"]
ChatTurnChargeSource = Literal["free", "clover", "skipped"]


class ChatTurn(Base):
    """턴이 남긴 응답 하나 = 한 행. 그 응답을 만든 글쓰기 모델, 그 턴의 차감, LLM 호출별 토큰 사용량, 그 응답에 귀속된
    스탯 변화·도달한 엔딩을 숫자와 id 로만 남긴다 — 프롬프트·응답 글은 싣지 않는다. 방 턴의 쓰기
    구간이 응답과 같은 커밋에 행을 넣는다(`chat/turn_store.py` 의 `RoomTurnStore` — 어느 경로가 어떤 값을 쓰는지도 거기 있다).

    미리보기 턴은 방 행이 없어 `chat_room_id` 를 채울 수 없으므로 기록하지 않는다.

    - `assistant_message_id` 는 유니크지만 FK 가 없다 — 재생성·편집·메시지 삭제·초기화가 메시지 행을 실제로 지우고,
      배포 겹침 구간의 옛 이미지도 그 경로를 그대로 돈다.
    - `spend_ledger_id` 는 클로버 원장 행 id 의 사본이고 FK 가 없다 — 턴 쓰기가 원장 행에 FK 확인 잠금을 걸지 않게 하고,
      차감의 사용처는 `clover_spend_usages` 가 맡으므로 여기서는 그와 잇는 조인 키로만 쓴다.
    - `turn_number` 는 이 응답이 속한 턴이다. 재생성 행은 대체한 응답 기록의 값을 이어받는다.
    - `llm_calls` 는 `[{callSite, model, promptTokens, cachedTokens, cacheWriteTokens, outputTokens, thoughtsTokens}]`,
      `stat_changes` 는 `{statEntityId: [before, after]}` 다. 임베딩 회상을 켠 턴은 맨 앞에 질의 임베딩 한 칸
      `{callSite, model, dims, promptTokens, latencyMs, outcome}` 이 붙는다(`chat/memory_vector.py`).
      생성 칸에는 처음으로 글이 든 델타가 오기까지의 지연 둘(정수 ms)이 더해진다 — `firstTokenMs` 는 턴 시작(생성 프롬프트
      조립 직전)부터라 기억 기능의 조립·질의 임베딩 지연까지 품고, `streamFirstTokenMs` 는 생성 스트림을 연 때부터라 생성
      호출(공급자 왕복 — 네트워크 왕복과 백엔드 클라이언트 첫 생성을 포함) 쪽 지연이다. 글 없이 끝난 생성과 이 키를 쓰기
      전 이미지가 넣은 행에는 없다. 판정·질의 임베딩 칸에는 붙지 않는다.
    - `memory_recall` 은 그 턴 프롬프트에 실은 장면 기억 목록 `[{episodeId, score, rank, chars}]` 이다(글은 싣지 않는다).
      회상을 쓰지 않은 턴과 이 칸을 모르는 옛 이미지가 넣은 행은 DB 기본값 `[]` 이다. 벡터 순위와 합쳐 고른 턴은 칸마다 벡터
      순위 `vectorRank` 가 더해지고, 명사 쪽에 없던 장면은 `score`·`rank` 가 null 이다.
    - `memory_facts` 는 그 턴 프롬프트에 실은 사실 기억 목록이다(글은 싣지 않는다). 기본값은 `memory_recall` 과 같은 이유로
      `[]` 다.

    응답이 재생성·수정·메시지 삭제로 지워져도 그 행은 방이 지워지거나 초기화될 때까지 남는다. 그래서 한 방 안에서
    `(chat_room_id, turn_number)` 는 유일하지 않고(수정 뒤 같은 턴 번호가 둘, 재생성 체인은 같은 턴의 스탯 효과를
    행마다 다시 적는다), `stat_changes` 를 방 단위로 합치면 이중 계산이 된다 — 기록은 메시지 id 로 찾는다.

    방 삭제·탈퇴는 `delete_chat_rooms` 가 방 행보다 먼저 이 행을 지운다(`ON DELETE CASCADE` 가 없다). 초기화도 그 방의
    행을 지운다 — 방 행은 남아 FK 와는 무관하고, 지운 대화의 기록을 남기지 않으려는 것이다. `kind`·`charge_source` 는
    native enum 이 아니라 Text 이고 위 Literal 이 값 범위다."""

    __tablename__ = "chat_turns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[ChatTurnKind] = mapped_column(Text, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 영수증에 찍히는 와이어 id(`gemini`·`sonnet`·`opus` 등) — 방의 `chat_model` 과 달리 그 턴에 실제로 쓴 모델이다.
    chat_model: Mapped[str] = mapped_column(Text, nullable=False)
    charge_source: Mapped[ChatTurnChargeSource] = mapped_column(Text, nullable=False)
    clover_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    spend_ledger_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    shortcut_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    llm_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    stat_changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    memory_recall: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    memory_facts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    ending_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 두 CHECK 의 검증은 행위 테스트가 유일하다.
    # 인덱스의 앞 열은 방 삭제·초기화의 DELETE 와 방 DELETE 의 FK 확인이 이 테이블을 방으로 찾기 위한 것이다(Postgres 는
    # FK 열에 인덱스를 만들지 않는다). 뒤 열은 한 방의 기록을 턴 순서로 읽는 조회(턴당 원가 측정)를 받는다.
    __table_args__ = (
        UniqueConstraint("assistant_message_id", name="ux_chat_turns_assistant_message_id"),
        CheckConstraint(f"kind IN ({_sql_in_list(ChatTurnKind)})", name="ck_chat_turns_kind"),
        CheckConstraint(
            f"charge_source IN ({_sql_in_list(ChatTurnChargeSource)})", name="ck_chat_turns_charge_source"
        ),
        Index("ix_chat_turns_chat_room_id_turn_number", "chat_room_id", "turn_number"),
    )


class ChatPreviousResponse(Base):
    """재생성이 밀어낸 직전 AI 응답 하나 — 방당 한 행이고, 사용자가 그 응답으로 되돌릴 수 있게 둔다.

    재생성의 쓰기 구간이 옛 응답을 지우는 같은 트랜잭션에서 그 응답의 원래 id·시각·본문·그림을 여기 옮겨 적는다(이미 있으면
    덮는다 — 늘 바로 직전 응답 하나만 남는다). 생성·정책·렌더 실패로 끝난 재생성은 그 구간에 오지 않으므로 이 행이 바뀌지
    않는다. 되돌리기는 이 행을 원래 id·시각으로 메시지에 다시 넣고, 그때 지운 지금 응답을 이 행에 옮겨 적는다(맞바꾸기 — 한 번
    더 되돌리면 원래대로다). `replaced_by_message_id` 는 이 행을 밀어낸 응답이고, 그 응답이 지금도 방의 마지막 메시지일
    때만 되돌릴 수 있다 — 이 테이블을 모르는 옛 이미지가 대화를 바꿔도 이 비교 하나로 낡은 행이 쓰이지 않는다.

    대화를 바꾸는 경로(보내기·수정·메시지 삭제·초기화)는 같은 커밋에서 이 행을 지운다. 방 FK 가 `ON DELETE CASCADE` 인 것은
    장면 기억과 같은 이유다 — 방 삭제·탈퇴는 이 행을 따로 지우지 않고, 이 테이블을 모르는 옛 이미지가 방을 지워도 FK 위반으로
    실패하지 않는다. 메시지 id·그림 id 칸에 FK 가 없는 이유는 가리키는 메시지가 이미 지워졌거나(되살릴 응답) 곧 지워질 수
    있고(밀어낸 응답), 그림은 메시지의 `image_id` 와 같은 다형 참조이기 때문이다."""

    __tablename__ = "chat_previous_responses"

    chat_room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="CASCADE"), primary_key=True
    )
    replaced_by_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    message_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # 밀려난 응답의 장면(메시지의 `scene` 과 같은 꼴). 맞바꾸기가 본문·그림과 함께 옮긴다.
    scene: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


DiscardedResponseKind = Literal["regenerate", "edit", "undo"]


class DiscardedResponse(Base):
    """재생성·편집·되돌리기로 AI 응답이 실제로 지워진 한 번 = 한 행. 응답 품질 불만의 암묵 신호를 SQL로
    세기 위한 기록이라 응답 원문은 저장하지 않는다. 되돌리기(`undo`)는 지금 응답을 지우는 동시에 재생성이 밀어낸 직전 응답을
    되살린다 — 재생성 수를 셀 때 이 행을 섞지 않는다.

    `discarded_count`는 그 행동이 지운 AI 응답 수다 — 재생성·되돌리기는 항상 1, 편집은 편집한 메시지 뒤에서
    지워진 AI 응답 수. 0개를 지운 행동은 행을 만들지 않으므로 CHECK가 1 이상을 강제한다.

    방 삭제·탈퇴는 이 행을 지우지 않는다(`delete_chat_rooms`의 자식 목록에 없는 것이 의도다).
    방이 사라지면 `chat_room_id`만 `SET NULL`로 비고 행과 `user_id`는 남는다 — 지표가 방 삭제로
    줄면 안 되기 때문이다. `kind`는 native enum이 아니라 Text이고 위 Literal이 값 범위다(값이 늘
    때 마이그레이션 없이 넓히기 위해서다)."""

    __tablename__ = "discarded_responses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[DiscardedResponseKind] = mapped_column(Text, nullable=False)
    discarded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 검증은 행위 테스트가 유일하다.
    # 집계(일별 재생성 수·사용자별 재생성률)는 테이블 전체를 읽으므로 집계용 인덱스는 두지 않는다.
    # `chat_room_id` 인덱스는 방 DELETE마다 Postgres가 이 테이블에서 그 방을 가리키는 행을 찾아
    # 비우는 조회를 위한 것이다 — 없으면 재생성할 때마다 늘어나는 이 테이블을 방 하나 지울 때마다
    # 처음부터 훑는다.
    __table_args__ = (
        CheckConstraint("discarded_count >= 1", name="ck_discarded_responses_count_positive"),
        Index("ix_discarded_responses_chat_room_id", "chat_room_id"),
    )


ChatMessageReportReason = Literal[
    "inappropriate",
    "minor_safety",
    "hateful",
    "out_of_character",
    "repetitive",
    "broken",
    "other",
]


class ChatMessageReport(Base):
    """AI 응답 신고. 신고 metadata와 대화 사본(증거)의 수명을 분리한 댓글 신고(`CommentReport`)와 같은
    구조다 — 증거는 접수 시 복사해 두고 90일이 지나면 조회에서 빠지며 파기 작업이 칸을 비운다.

    `chat_room_id`·`chat_message_id`는 `SET NULL`이다. 재생성·메시지 삭제·편집·방 초기화·방 삭제가
    신고된 메시지를 지워도 신고와 증거 사본은 남아야 하고, 지우는 쪽이 이 테이블을 몰라도 FK
    위반으로 실패하지 않아야 한다. 그래서 대상 메시지를 가리키는 칸이 NULL일 수 있고, 증거
    칸만으로 무엇이 신고됐는지 읽혀야 한다.

    같은 회원이 같은 메시지를 두 번 신고하면 유니크 제약이 막는다. 이 제약은 Postgres 기본값인
    NULLS DISTINCT여야 한다 — NULLS NOT DISTINCT면 한 회원이 신고한 메시지 둘이 지워져
    `chat_message_id`가 둘 다 NULL이 되는 순간 그 DELETE가 유니크 위반으로 실패한다.

    `reason`은 native enum이 아니라 Text이고 위 Literal이 값 범위다(베타 피드백으로 사유가 바뀌어도
    마이그레이션 없이 넓히기 위해서다). `status`는 작품·댓글 신고와 같은 `report_status` 타입을
    쓴다. 메모 길이 제한은 요청 스키마가 강제한다."""

    __tablename__ = "chat_message_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[ChatMessageReportReason] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 신고된 AI 응답 본문과, 그보다 앞선 가장 최근 사용자 메시지(없으면 NULL — 오프닝 신고).
    evidence_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '90 days'"), nullable=False
    )
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 유니크의 열 순서가 (메시지, 신고자)인 것은 이 인덱스가 메시지 DELETE의 `SET NULL` 조회도
    # 받게 하기 위해서다 — 재생성은 매번 메시지를 지우므로, 메시지가 앞 열이 아니면 그때마다 이
    # 테이블을 처음부터 훑는다. 유일성의 뜻은 열 순서와 무관하다.
    __table_args__ = (
        UniqueConstraint(
            "chat_message_id", "reporter_user_id", name="ux_chat_message_reports_message_reporter"
        ),
        Index("ix_chat_message_reports_status_created", "status", "created_at", "id"),
        Index("ix_chat_message_reports_evidence_expires", "evidence_expires_at"),
    )
