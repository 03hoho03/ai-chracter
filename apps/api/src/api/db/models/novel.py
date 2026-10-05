"""대화를 소설로 옮긴 결과물. 소설 → 장 → 장 개정, 그리고 장을 만들거나 고치는 작업 행 넷이다.

소설은 원래 대화방과 떨어진 문서다. 방을 지워도 소설은 남고(`novels.chat_room_id` 만 비워진다), 원작 작품을
가리키는 칸은 FK 없는 사본이라 작품이 사라져도 영향이 없다. 탈퇴하면 네 테이블을 모두 파기한다.

`relationship()`·`ON DELETE CASCADE` 가 없으므로 지울 때는 작업 → 개정 → 장 → 소설 순서를 직접 지킨다
(`novelize/deletion.py` 의 `delete_novels` 한 곳).

종류·상태처럼 값이 정해진 칸은 native enum 이 아니라 Text + Literal 이고(값이 늘 때 타입 변경 마이그레이션이 필요
없다), DB 쪽 범위는 CHECK 가 막는다. CHECK 문의 값 목록은 아래 Literal 에서 만든다 — 두 곳에 따로 적으면 한쪽만
고쳐지기 쉽다. 🔴 `alembic check` 는 CHECK 제약을 비교하지 않으므로 Literal 을 바꾸면 마이그레이션을 손으로 더하고,
검증은 `pytest.raises(IntegrityError)` 행위 테스트가 유일하다."""

import uuid
from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

# 소설이 어느 레인(story·character)의 문안으로 고쳐지는지. 방이 사라진 뒤에도 AI 수정은 할 수 있으므로 방에서
# 읽지 않고 소설 행에 사본으로 둔다.
NovelContentType = Literal["story", "character"]
NovelRevisionSource = Literal["generate", "regenerate", "manual_edit", "ai_edit", "revert"]
NovelJobKind = Literal["chapter_generate", "chapter_regenerate", "ai_edit"]
NovelJobStatus = Literal["queued", "running", "succeeded", "failed"]
NovelJobFailureCode = Literal[
    "llm_error", "timeout", "truncated", "refused", "blocked", "empty", "source_changed", "expired", "internal"
]


def _sql_in_list(literal: Any) -> str:
    return ", ".join(f"'{value}'" for value in get_args(literal))


class Novel(Base):
    """대화방 하나에서 만든 소설 한 권. 방 하나에 소설은 한 권뿐이다(`chat_room_id` 유니크 — 방이 지워져 NULL 이 된
    소설끼리는 겹쳐도 된다).

    방을 지우면 `chat_room_id` 가 `SET NULL` 로 비고 소설은 남는다 — 이미 만든 장은 읽고 고칠 수 있고 새 장만 못
    만든다. 방 삭제 쪽(`chat/room_deletion.py`)이 이 테이블을 몰라도 되게 하려고 FK 동작에 맡긴다.

    `content_id`·`content_title`·`character_name` 은 만들 때의 원작 사본이고 FK 가 없다 — 작품이 지워지거나 바뀌어도
    소설은 그대로다. 스토리 작품은 캐릭터 한 명이 정해져 있지 않아 `character_name` 이 NULL 이다.

    `protagonist_name` 은 본문에서 사용자 쪽 인물을 부르는 이름이다. 대화 프로필 이름(없으면 작품 기본 이름)으로
    미리 채우고, 둘 다 없으면 NULL 로 두었다가 첫 장을 만들기 전에 입력받는다. 나중에 바꿔도 이미 만든 장 본문은
    그대로다."""

    __tablename__ = "novels"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_type: Mapped[NovelContentType] = mapped_column(Text, nullable=False)
    content_title: Mapped[str] = mapped_column(Text, nullable=False)
    character_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 장을 만들 때마다 프롬프트에 함께 싣는 작가 메모. 길이 상한은 요청 스키마가 정한다.
    setting_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    protagonist_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 목록은 내 소설을 최근 수정 순으로 읽는다. 방 유니크 인덱스는 방 DELETE 때 Postgres 가 이 방을 가리키는 소설을
    # 찾아 비우는 조회도 겸한다.
    __table_args__ = (
        Index("ix_novels_user_id_updated_at", "user_id", updated_at.desc()),
        Index("ux_novels_chat_room_id", "chat_room_id", unique=True),
    )


class NovelChapter(Base):
    """소설의 한 장 = 원래 대화의 연속 구간 하나. 원문 사본은 두지 않고 구간의 양 끝만 기억한다.

    시작·끝 메시지는 FK 없는 Uuid 와 그 메시지의 `created_at` 사본이다. FK 로 묶으면 방 초기화나 끝 메시지 삭제가
    장 때문에 막히거나 500 이 된다. 메시지가 사라져도 다음 장의 시작은 저장해 둔 시각으로 정할 수 있다.

    `assistant_message_count`(구간 안의 AI 응답 수, 0 이면 장이 될 수 없다)와 `source_hash`(구간의 역할·원문을
    이은 sha256 hex)는 만든 때의 구간 모양이다. 재생성할 때 지금 구간의 해시가 다르면 원문이 바뀐 것이라 거부한다.

    현재 본문을 가리키는 칸은 없다. 현재 개정 = `revision_no` 가 가장 큰 개정이다 — 장이 개정을, 개정이 장을 서로
    가리키는 순환 FK 를 피하려는 것이다."""

    __tablename__ = "novel_chapters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    start_message_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    end_message_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assistant_message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 장 번호 유니크는 같은 소설에 장 생성이 동시에 둘 들어왔을 때의 마지막 방어선이다(첫 방어선은 작업 행의 소설당
    # 진행 중 1건 인덱스). 이 인덱스가 소설 삭제 때 `novel_id` 로 장을 찾는 조회도 겸한다.
    __table_args__ = (
        CheckConstraint("assistant_message_count >= 1", name="ck_novel_chapters_assistant_message_count_positive"),
        Index("ux_novel_chapters_novel_id_ordinal", "novel_id", "ordinal", unique=True),
    )


class NovelChapterRevision(Base):
    """장 본문의 한 판. 생성·재생성·직접 편집·AI 수정 적용·되돌리기가 모두 새 행을 쌓고 기존 행은 고치지 않는다.

    되돌리기는 옛 개정의 본문을 복제한 새 개정이고, `reverted_from_revision_id` 가 그 옛 개정을 가리킨다.

    `(chapter_id, revision_no)` 유니크가 낙관적 충돌 검사다 — 두 탭이 같은 개정을 기준으로 동시에 저장하면 같은 다음
    번호를 쓰려다 두 번째가 위반되고, 라우트는 그것을 409 로 돌려준다. 이 인덱스는 장의 현재 개정(최대 번호) 조회와
    장 삭제 때 개정을 찾는 조회도 겸한다."""

    __tablename__ = "novel_chapter_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chapter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novel_chapters.id"), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[NovelRevisionSource] = mapped_column(Text, nullable=False)
    reverted_from_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapter_revisions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"source IN ({_sql_in_list(NovelRevisionSource)})", name="ck_novel_chapter_revisions_source"
        ),
        Index("ux_novel_chapter_revisions_chapter_id_revision_no", "chapter_id", "revision_no", unique=True),
    )


class NovelJob(Base):
    """장 생성·재생성·AI 수정 한 번 = 한 행. 요청은 행을 만들고 곧바로 돌아가며, 실제 LLM 호출은 백그라운드에서 돌고
    클라이언트는 이 행을 폴링한다.

    클로버는 행을 만들 때 미리 차감해 `charged_amount` 에 적는다. 실패로 확정되면 환불하고 `refunded_at` 을 찍는다 —
    상태 전이를 조건부 UPDATE 로 하므로 정리 경로와 정상 종료가 겹쳐도 환불은 한 번이다. 환불은 실패한 작업에만
    있을 수 있다(CHECK). `heartbeat_at` 이 오래 멈춘 진행 중 작업은 죽은 것으로 보고 실패 처리한다.

    장 생성·재생성은 입력 구간(`start_*`·`end_*`, 장 행과 같은 이유로 FK 없음)을 갖고, 재시도 상한은 같은 시작
    메시지의 오늘 작업 수로 센다. AI 수정은 `chapter_id`·`base_revision_id`·문단 범위·지시문을 갖고, 결과를 곧바로
    개정으로 만들지 않고 `result_text` 에 두었다가 사용자가 적용할 때 새 개정이 된다.

    대화방을 가리키는 칸은 두지 않는다 — 두면 방 삭제가 이 테이블을 알아야 하고, 모르면 방 DELETE 가 FK 위반으로
    실패한다. 개정이 작업을 가리키지도 않는다 — 작업 → 개정(`base_revision_id`·`result_revision_id`) 참조와 순환이
    된다."""

    __tablename__ = "novel_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    kind: Mapped[NovelJobKind] = mapped_column(Text, nullable=False)
    status: Mapped[NovelJobStatus] = mapped_column(Text, nullable=False)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("novel_chapters.id"), nullable=True)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapter_revisions.id"), nullable=True
    )
    # 이 작업이 만든 개정. 장의 현재 개정(번호 최대)으로는 대신할 수 없다 — 재생성이 끝난 뒤 직접 수정·되돌리기가
    # 쌓이면 최대 번호 개정은 더 이상 이 작업의 결과가 아니다. FK 가 즉시 검사되므로 개정을 INSERT 한 뒤 두 번째
    # UPDATE 로 채우고, 개정을 만들지 않은 작업은 NULL 로 남는다.
    result_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapter_revisions.id"), nullable=True
    )
    start_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    start_message_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    end_message_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paragraph_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    charged_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[NovelJobFailureCode | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `(user_id, created_at)` 는 KST 하루 단위 집계, `(novel_id, start_message_id, created_at)` 는 같은 시작
    # 메시지의 재시도 수 집계용이고, 뒤의 것이 소설 삭제 때 `novel_id` 로 작업을 찾는 조회도 겸한다.
    # 진행 중 부분 유니크는 소설 하나에 queued·running 작업이 동시에 둘 생기지 않게 한다 — 같은 소설의 동시 요청은
    # 두 번째 INSERT 가 여기에 걸린다. 끝난 작업(succeeded·failed)은 몇 개든 쌓인다.
    __table_args__ = (
        CheckConstraint(f"kind IN ({_sql_in_list(NovelJobKind)})", name="ck_novel_jobs_kind"),
        CheckConstraint(f"status IN ({_sql_in_list(NovelJobStatus)})", name="ck_novel_jobs_status"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({_sql_in_list(NovelJobFailureCode)})",
            name="ck_novel_jobs_failure_code",
        ),
        CheckConstraint("charged_amount >= 0", name="ck_novel_jobs_charged_amount_non_negative"),
        CheckConstraint(
            "refunded_at IS NULL OR status = 'failed'", name="ck_novel_jobs_refund_only_when_failed"
        ),
        Index("ix_novel_jobs_user_id_created_at", "user_id", "created_at"),
        Index("ix_novel_jobs_novel_id_start_message_id_created_at", "novel_id", "start_message_id", "created_at"),
        Index(
            "ux_novel_jobs_novel_id_active",
            "novel_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
