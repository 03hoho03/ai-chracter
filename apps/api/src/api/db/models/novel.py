"""대화를 소설로 옮긴 결과물. 소설 → 묶음 → 화(장) → 화 개정, 그리고 화를 만들거나 고치는 작업 행이 뼈대이고, 그
옆에 인물 카드·화별 등장 인물·스냅샷·읽은 위치가 붙는다. 소유자가 소설을 노벨(공개 소설)로 내놓으면 공개 상태·화 공개본·
텍스트 심사 기록이 더 붙고, 독자가 읽으면 독자의 읽은 자리·좋아요·화 댓글이, 운영자가 홈에 걸면 홈 노벨 지정이 붙는다.
노벨·노벨 댓글 신고는 소설이 지워져도 남도록 소설·화·댓글 칸이 `SET NULL` 이다.

소설은 원래 대화방과 떨어진 문서다. 방을 지워도 소설은 남고(`novels.chat_room_id` 만 비워진다), 원작 작품을
가리키는 칸은 FK 없는 사본이라 작품이 사라져도 영향이 없다. 탈퇴하면 소설 아래 테이블을 모두 파기한다.

`relationship()` 이 없고 뼈대 테이블(소설·화·개정·작업)에는 `ON DELETE CASCADE` 도 없으므로, 지울 때는 작업 → 개정 →
화 → 소설 순서를 직접 지킨다(`novelize/deletion.py` 의 `delete_novels` 한 곳).

🔴 예외: 묶음·인물·등장 인물·스냅샷·읽은 위치와 노벨 공개 상태·화 공개본·텍스트 심사 기록·독자 읽은 자리·좋아요·홈 노벨
지정·화 댓글은 부모(소설·화·개정)를 지우면
함께 지워지는 `ON DELETE CASCADE` 다. 이 저장소의 "cascade 없음" 관례를 일부러 어긴 것이다 — 이미지만 옛 판으로
되돌렸을 때 옛 코드의 화 삭제·소설 삭제·탈퇴는 이 테이블들을 모르고 위 순서대로만 지우는데, cascade 가 없으면 그
DELETE 가 FK 위반으로 500 이 된다. 같은 이유로 `novel_chapters.batch_id` 는 nullable 이다(옛 코드의 화 INSERT 는 이
칸을 모른다). 새 코드는 cascade 에 기대지 않고 삭제 순서를 직접 적는다.

종류·상태처럼 값이 정해진 칸은 native enum 이 아니라 Text + Literal 이고(값이 늘 때 타입 변경 마이그레이션이 필요
없다), DB 쪽 범위는 CHECK 가 막는다. CHECK 문의 값 목록은 아래 Literal 에서 만든다 — 두 곳에 따로 적으면 한쪽만
고쳐지기 쉽다. 🔴 `alembic check` 는 CHECK 제약을 비교하지 않으므로 Literal 을 바꾸면 마이그레이션을 손으로 더하고,
검증은 `pytest.raises(IntegrityError)` 행위 테스트가 유일하다."""

import uuid
from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
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
from api.db.models.moderation import ReportReasonCategory, ReportStatus

# 소설이 어느 레인(story·character)의 문안으로 고쳐지는지. 방이 사라진 뒤에도 AI 수정은 할 수 있으므로 방에서
# 읽지 않고 소설 행에 사본으로 둔다.
NovelContentType = Literal["story", "character"]
NovelRevisionSource = Literal["generate", "regenerate", "manual_edit", "ai_edit", "revert"]
NovelJobKind = Literal["chapter_generate", "chapter_regenerate", "ai_edit", "chain_generate"]
NovelJobStatus = Literal["queued", "running", "succeeded", "failed"]
NovelJobFailureCode = Literal[
    "llm_error",
    "timeout",
    "truncated",
    "refused",
    "blocked",
    "empty",
    "source_changed",
    "expired",
    "internal",
    "malformed",
    "episode_count_mismatch",
]
NovelSnapshotKind = Literal["manual", "auto_before_restore"]


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
    # 소설 제목. 생성 출력이 채우고, 사용자가 고친 뒤(`title_edited_at` 이 찍힌 뒤)에는 AI 가 덮지 않는다. NULL 이면
    # 화면은 원작 제목으로 대신한다.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # 표지로 고른 이미지. 이미지를 지우면 표지만 비고 소설은 남는다(SET NULL). 아래 새 NOT NULL 칸들이 모두
    # server_default 를 갖는 것은 옛 코드의 소설 INSERT 가 이 칸들을 모르기 때문이다.
    cover_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assets.id", ondelete="SET NULL", name="fk_novels_cover_asset_id"), nullable=True
    )
    # 편집 보드의 노드 위치. 형식은 화면이 정하고 서버는 통째로 저장한다(노드별 행을 두지 않는다).
    board_layout: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 목록은 내 소설을 최근 수정 순으로 읽는다. 방 유니크 인덱스는 방 DELETE 때 Postgres 가 이 방을 가리키는 소설을
    # 찾아 비우는 조회도 겸한다. 표지 인덱스는 이미지 DELETE 때 SET NULL 이 이 이미지를 표지로 쓴 소설을 찾는 조회용이고,
    # 표지 없는 소설이 대부분이라 NULL 은 담지 않는다.
    __table_args__ = (
        Index("ix_novels_user_id_updated_at", "user_id", updated_at.desc()),
        Index("ux_novels_chat_room_id", "chat_room_id", unique=True),
        Index(
            "ix_novels_cover_asset_id",
            "cover_asset_id",
            postgresql_where=text("cover_asset_id IS NOT NULL"),
        ),
    )


class NovelBatch(Base):
    """한 번의 생성이 만든 화 묶음 = 원래 대화의 연속 구간 하나. 생성 한 번이 구간을 여러 화로 나눠 쓸 수 있어, 원문
    구간의 주인은 화가 아니라 이 행이다. 다시 만들기도 묶음 단위다(구간 전체를 다시 써 화들을 갈아 끼운다).

    구간 칸(시작·끝 메시지와 그 시각, AI 응답 수, 원문 해시)의 뜻은 `NovelChapter` 와 같고, 같은 묶음의 화 행에도 같은
    값의 사본이 있다 — 옛 코드는 화 행의 구간 칸만 읽기 때문이다. `target_episode_count` 는 생성할 때 정한 화 수 목표다.
    처음 생성에서는 모델이 그보다 적게 쓰면 모자란 화만큼 환불하고 많이 쓰면 추가 과금 없이 받아들이므로, 실제 화 수와
    다를 수 있다.

    어느 모델로 썼는지는 이 행에 두지 않는다 — 다시 만들기가 다른 모델일 수 있어 묶음 하나의 모델이 정해지지 않고, 그
    기록은 작업 행(`NovelJob.model`)에 있다."""

    __tablename__ = "novel_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    start_message_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    end_message_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assistant_message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    target_episode_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 묶음 번호 유니크는 같은 소설에 묶음 생성이 동시에 둘 들어왔을 때의 마지막 방어선이고, 소설 삭제 때 `novel_id` 로
    # 묶음을 찾는 조회도 겸한다.
    __table_args__ = (
        CheckConstraint("target_episode_count >= 1", name="ck_novel_batches_target_episode_count_positive"),
        Index("ux_novel_batches_novel_id_ordinal", "novel_id", "ordinal", unique=True),
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
    # 이 화가 속한 묶음과 묶음 안 순번(0부터). 묶음을 지워도 화가 조용히 사라지지 않게 cascade 를 걸지 않는다 — 새
    # 코드는 화를 먼저 지운다. nullable 인 것은 옛 코드가 이 칸 없이 화를 INSERT 하기 때문이고(모듈 docstring), 그렇게
    # 생긴 화는 묶음 이관이 다시 채운다.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("novel_batches.id"), nullable=True)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 사용자가 화 제목을 고친 시각. 찍혀 있으면 다시 만들기가 그 화의 제목만 그대로 두고 본문·요약·등장 인물은 새로
    # 쓴다(소설 제목의 `title_edited_at` 과 같은 규칙). 제목을 비우면 다시 NULL 이 되어 AI 가 쓸 수 있다.
    title_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 다음 화 머리의 "이전 줄거리"와 다음 묶음 생성 입력에 쓰는 이 화 요약.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 장 번호 유니크는 같은 소설에 장 생성이 동시에 둘 들어왔을 때의 마지막 방어선이다(첫 방어선은 작업 행의 소설당
    # 진행 중 1건 인덱스). 이 인덱스가 소설 삭제 때 `novel_id` 로 장을 찾는 조회도 겸한다. 묶음 인덱스는 묶음의 화를
    # 읽는 조회와 묶음 DELETE 때 FK 검사용이다.
    __table_args__ = (
        CheckConstraint("assistant_message_count >= 1", name="ck_novel_chapters_assistant_message_count_positive"),
        Index("ux_novel_chapters_novel_id_ordinal", "novel_id", "ordinal", unique=True),
        Index("ix_novel_chapters_batch_id", "batch_id"),
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
        # 개정 DELETE 때 그 개정을 되돌리기 원본으로 가리키는 행을 찾는 FK 검사용.
        Index("ix_novel_chapter_revisions_reverted_from_revision_id", "reverted_from_revision_id"),
    )


class NovelJob(Base):
    """장 생성·재생성·AI 수정 한 번 = 한 행. 요청은 행을 만들고 곧바로 돌아가며, 실제 LLM 호출은 백그라운드에서 돌고
    클라이언트는 이 행을 폴링한다.

    클로버는 행을 만들 때 미리 차감해 `charged_amount` 에 적는다. 실패로 확정되면 환불하고 `refunded_at` 과 환불액
    `refunded_amount` 를 찍는다 — 상태 전이를 조건부 UPDATE 로 하므로 정리 경로와 정상 종료가 겹쳐도 환불은 한 번이다.
    성공한 작업도 목표보다 적은 화를 냈으면 모자란 몫만큼 부분 환불할 수 있다. 환불액 0 은 환불이 아니라서 `refunded_at`
    을 찍지 않는다. 금액·상태 조합은 `ck_novel_jobs_refund_amount` 가 막는다. `heartbeat_at` 이 오래 멈춘 진행 중 작업은
    죽은 것으로 보고 실패 처리한다.

    "남은 대화 한 번에"(연쇄 생성)는 부모 행 하나(`chain_generate`)가 전체 금액을 미리 차감하고, 묶음마다 자식 장 생성
    행(`parent_job_id`, 차감 0)을 하나씩 만든다. 부모는 차감 시점 화 단가(`unit_price`)를 고정해 두고, 성공한 자식이 쓴
    몫을 `consumed_amount` 에 쌓는다 — 실패하면 쓰지 않은 몫(`charged_amount - consumed_amount`)만 돌려준다.

    장 생성·재생성은 입력 구간(`start_*`·`end_*`, 장 행과 같은 이유로 FK 없음)을 갖고, 재시도 상한은 같은 시작
    메시지의 오늘 작업 수로 센다. AI 수정은 `chapter_id`·`base_revision_id`·문단 범위·지시문을 갖고, 결과를 곧바로
    개정으로 만들지 않고 `result_text` 에 두었다가 사용자가 적용할 때 새 개정이 된다. 적용하지 않고 버리면
    `dismissed_at` 을 찍는다(환불은 없다).

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
    # 사용자가 AI 수정 미리보기를 적용하지 않고 버린 시각. 버린 미리보기는 상세의 미적용 목록에 다시 나오지 않는다.
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 장 생성·재생성에 쓴 글쓰기 모델의 레지스트리 id(`llm/chat_models.py`). 과금할 때 정해 적고, 실행은 이 값을 그대로
    # 쓴다 — 그 사이 허용이 회수돼도 값을 낸 모델로 생성한다. NULL 은 이 칸이 생기기 전의 장 작업(전부 Gemini)과 모델을
    # 고르지 않는 AI 수정이다. 값 제약을 두지 않는다 — 레지스트리에서 내린 모델의 옛 값이 남아도 행이 살아 있어야 한다.
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    charged_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # 선차감의 원장 행. 환급이 이 차감의 로트 배분을 그대로 되돌리려고 들고 있다. 차감 0 인 연쇄 자식과 이 칸이 생기기
    # 전의 작업은 NULL 이고, 그 환급은 무기한 새 로트로 돌려준다.
    spend_ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clover_ledger.id", name="fk_novel_jobs_spend_ledger_id"), nullable=True
    )
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 돌려준 클로버. NULL 인데 `refunded_at` 이 찍힌 실패 행은 이 칸을 모르는 옛 코드가 환불한 것이라 전액 환불로 읽는다.
    refunded_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 연쇄 생성의 부모 작업. 자기 참조 FK 를 두지 않는다 — 부모와 자식은 같은 소설의 작업 행이라 늘 함께 남고 소설을
    # 지울 때 함께 지워져, FK 가 막아 줄 상황이 없다.
    parent_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # 묶음 생성·다시 만들기·연쇄 자식이 대상으로 삼은 묶음. FK 를 두지 않는다 — 작업 행은 차감 기록이라 묶음을 지운
    # 뒤에도 남는데, FK 면 묶음을 지울 때마다 이 칸을 먼저 비워야 한다. 여러 화를 내는 작업은 화 하나를 가리킬 수 없어
    # `chapter_id`·`result_revision_id` 를 비운다.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    episode_count_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consumed_amount: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # 연쇄 부모가 차감할 때 정한 묶음 수와 묶음 하나의 화 수 상한. 진행 표시(끝낸 묶음 / 계획한 묶음)와 자식의 화 수
    # 상한이 이 값을 읽는다 — 그 사이 설정이 바뀌어도 낸 금액의 근거(묶음 수 × 화 수 상한 × 단가)대로 가야 쓴 몫이 낸
    # 돈을 넘지 않는다. 연쇄 부모가 아니면 비어 있다.
    planned_batches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_k_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # 두 번째 INSERT 가 여기에 걸린다. 끝난 작업(succeeded·failed)은 몇 개든 쌓인다. 연쇄 자식은 이 제약에서 빠진다 —
    # 부모가 running 인 채로 자식을 돌리므로 둘이 동시에 진행 중이다. 자식은 부모가 하나씩만 만든다.
    # 장·개정을 가리키는 세 인덱스는 장·개정 DELETE 때 FK 검사용이다.
    __table_args__ = (
        CheckConstraint(f"kind IN ({_sql_in_list(NovelJobKind)})", name="ck_novel_jobs_kind"),
        CheckConstraint(f"status IN ({_sql_in_list(NovelJobStatus)})", name="ck_novel_jobs_status"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({_sql_in_list(NovelJobFailureCode)})",
            name="ck_novel_jobs_failure_code",
        ),
        CheckConstraint("charged_amount >= 0", name="ck_novel_jobs_charged_amount_non_negative"),
        # 환불이 있으면 금액도 있다. 실패는 쓰지 않은 몫 전부(연쇄 부모가 아니면 `consumed_amount` 가 0 이라 전액), 성공은
        # 0 과 전액 사이의 부분 환불만 된다. 마지막 갈래는 금액 칸을 모르는 옛 코드가 실패 작업에 `refunded_at` 만 찍는
        # 경우다 — 막으면 이미지만 되돌렸을 때 옛 코드의 환불이 500 이 된다.
        CheckConstraint(
            "(refunded_at IS NULL AND refunded_amount IS NULL)"
            " OR (refunded_at IS NOT NULL AND refunded_amount IS NOT NULL AND ("
            "(status = 'failed' AND refunded_amount = charged_amount - consumed_amount AND refunded_amount > 0)"
            " OR (status = 'succeeded' AND refunded_amount > 0 AND refunded_amount < charged_amount)))"
            " OR (status = 'failed' AND refunded_at IS NOT NULL AND refunded_amount IS NULL)",
            name="ck_novel_jobs_refund_amount",
        ),
        # 연쇄 부모가 쓴 몫은 낸 돈 안에 있다. 넘으면 실패 환불액이 음수가 되므로 누적하는 자리에서 거절한다.
        CheckConstraint(
            "consumed_amount >= 0 AND consumed_amount <= charged_amount", name="ck_novel_jobs_consumed_amount"
        ),
        # 연쇄 부모는 계획 세 값을 모두 갖는다. 비교만 쓰면 빈 칸에서 식이 NULL 이 되어 통과하므로 `IS NOT NULL` 을 건다.
        CheckConstraint(
            "kind <> 'chain_generate' OR (planned_batches IS NOT NULL AND batch_k_max IS NOT NULL"
            " AND unit_price IS NOT NULL AND planned_batches >= 1 AND batch_k_max >= 1 AND unit_price >= 1)",
            name="ck_novel_jobs_chain_plan",
        ),
        Index("ix_novel_jobs_user_id_created_at", "user_id", "created_at"),
        Index("ix_novel_jobs_novel_id_start_message_id_created_at", "novel_id", "start_message_id", "created_at"),
        Index(
            "ux_novel_jobs_novel_id_active",
            "novel_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND parent_job_id IS NULL"),
        ),
        Index("ix_novel_jobs_chapter_id", "chapter_id"),
        Index("ix_novel_jobs_base_revision_id", "base_revision_id"),
        Index("ix_novel_jobs_result_revision_id", "result_revision_id"),
        # 연쇄 부모의 자식 목록 조회용.
        Index("ix_novel_jobs_parent_job_id", "parent_job_id"),
    )


class NovelCharacter(Base):
    """소설 속 인물 카드 하나. 생성 출력이 화마다 등장 인물 이름을 내면 그 이름의 카드에 붙인다(없으면 새로 만든다).

    소설 안에서 이름과 별칭을 모은 공간은 겹치지 않는다 — AI 가 낸 이름 하나가 카드 둘에 붙으면 안 되기 때문이다. DB 는
    `(novel_id, name)` 유니크만 막고, 별칭까지 포함한 유일성은 코드가 사용자 행 잠금 아래에서 지킨다. 합치기는 흡수되는
    카드의 이름·별칭을 남는 카드의 `aliases` 로 옮기고 흡수되는 카드를 지운다 — 그 뒤 AI 가 같은 이름을 내면 남는 카드에
    붙는다."""

    __tablename__ = "novel_characters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    memo: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 이름 유니크가 소설의 인물 목록 조회와 소설 삭제 때 FK 검사도 겸한다.
    __table_args__ = (Index("ux_novel_characters_novel_id_name", "novel_id", "name", unique=True),)


class NovelChapterCharacter(Base):
    """어느 화에 어느 인물이 나왔는지. 생성 출력에서 나온 사실이라 스냅샷 복원 대상이 아니다.

    🔴 `(chapter_id, character_id)` 복합 PK 는 `alembic check` 가 비교하지 않는다 — 검증은 `IntegrityError` 행위
    테스트뿐이다."""

    __tablename__ = "novel_chapter_characters"

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), primary_key=True
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_characters.id", ondelete="CASCADE"), primary_key=True
    )

    # 인물 쪽에서 등장 화를 찾는 조회와 인물 DELETE 때 FK 검사용(화 쪽은 PK 앞자리가 겸한다).
    __table_args__ = (Index("ix_novel_chapter_characters_character_id", "character_id"),)


class NovelSnapshot(Base):
    """소설의 편집 가능한 상태(제목·소개·노트·인물·화마다 개정 id·제목·요약·작가의 말)를 한 시점에 떠 둔 것. `payload`
    한 덩어리로 두고 항목 테이블을 두지 않는다 — 복원·비교는 payload 를 읽어 처리하고, 개정은 FK 없이 id 로만 가리켜
    개정이 지워져도 스냅샷이 남는다.

    `manual` 은 사용자가 이름 붙여 저장한 것, `auto_before_restore` 는 복원 직전에 지금 상태를 자동으로 떠 둔 것이다."""

    __tablename__ = "novel_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[NovelSnapshotKind] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 목록은 최근 것부터 읽는다. 이 인덱스가 소설 삭제 때 FK 검사도 겸한다.
    __table_args__ = (
        CheckConstraint(f"kind IN ({_sql_in_list(NovelSnapshotKind)})", name="ck_novel_snapshots_kind"),
        Index("ix_novel_snapshots_novel_id_created_at", "novel_id", created_at.desc()),
    )


class NovelReadingPosition(Base):
    """화마다 마지막으로 읽은 문단. 소설은 한 사용자 것이라 사용자 칸이 없고, 화 하나에 행 하나다.

    `paragraph_count` 는 저장할 때의 문단 수다 — 그 뒤 개정이 바뀌어 문단 수가 달라지면 옛 위치를 새 문단 수에 비례해
    옮기는 데 쓴다. `revision_id` 는 그때 읽던 개정이고 FK 를 두지 않는다(개정이 지워져도 위치는 남는다). 마지막 읽은
    화는 소설 안에서 `updated_at` 이 가장 큰 행이다. `finished_at` 은 끝까지 읽은 시각이고 한 번 찍히면 되돌리지 않는다."""

    __tablename__ = "novel_reading_positions"

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_count: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 소설의 마지막 읽은 화 조회용이고, 소설 삭제 때 FK 검사도 겸한다.
    __table_args__ = (
        Index("ix_novel_reading_positions_novel_id_updated_at", "novel_id", updated_at.desc()),
    )


# 노벨(공개 소설) — 소설 소유자가 자기 소설을 로그인 회원 누구나 읽게 내놓은 상태와, 그때 얼린 공개 화면 글.
NovelPublicationVisibility = Literal["public", "withdrawn"]
NovelPublicationModerationStatus = Literal["normal", "restricted"]
NovelScreeningOutcome = Literal["passed", "rejected"]
# 텍스트 심사가 문제로 짚을 수 있는 공개 화면 글의 자리.
NovelScreeningPart = Literal["novel_title", "synopsis", "chapter_title", "author_note", "chapter_body"]


class NovelPublication(Base):
    """소설 한 권의 공개 상태와 소설 단위 공개 화면 글(제목·소개)의 공개 시점 사본. 행이 없으면 공개한 적이 없다.

    상태는 두 축이다 — 게시자가 정하는 공개 범위(`visibility`: 공개 중·거둠)와 운영자가 정하는 이용제한
    (`moderation_status`). 작품의 공개 범위·이용제한을 따로 두는 것과 같은 이유로, 게시자가 거뒀다 다시 여는 일과 운영 조치가
    서로를 덮어쓰지 않게 한다. 거두기는 행을 지우지 않고 값만 바꾼다 — 다시 공개하면 공개 화 사본이 그대로 살아난다.

    `title`·`synopsis` 는 소유자가 나중에 고쳐도 바뀌지 않는다. 고친 내용은 다시 공개해 텍스트 심사를 거쳐야 이 행에
    들어온다(심사를 거치지 않은 글이 공개 화면에 나가지 않게). `title` 이 NULL 이면 화면은 원작 제목(`novels.content_title`)
    으로 대신한다 — 소유자 화면과 같은 규칙이다. 표지는 사본을 두지 않는다. 공개 화면은 이미 발행 심사를 거친 원작 썸네일만
    쓰고, 소설 생성 표지는 심사를 거친 적이 없어서다.

    공개한 화 수는 칸으로 두지 않고 화 공개본 행(`NovelChapterPublication`) 수로 센다 — 마지막 묶음을 지우면 그 화의
    공개본도 함께 지워지므로 칸을 두면 두 곳을 맞춰야 한다.

    소설을 지우면 함께 지워지는 `ON DELETE CASCADE` 다(모듈 docstring 의 예외와 같은 이유 — 이 테이블을 모르는 옛 판 코드의
    소설 삭제·탈퇴가 FK 위반으로 500 이 되지 않게). 새 코드는 `novelize/deletion.py` 에서 직접 지운다."""

    __tablename__ = "novel_publications"

    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    visibility: Mapped[NovelPublicationVisibility] = mapped_column(Text, nullable=False)
    moderation_status: Mapped[NovelPublicationModerationStatus] = mapped_column(
        Text, nullable=False, server_default="normal"
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    synopsis: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # 좋아요 수(`novel_likes` 행 수)와 조회 수. 둘 다 SQL 상대 UPDATE 로만 바꾼다 — 읽고 더해 쓰면 동시 요청이 서로를
    # 덮어 수가 빠진다. 좋아요 수를 행 수로 그때그때 세지 않는 것은 인기순 목록이 이 칸으로 정렬하고 커서를 만들기 때문이다.
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 공개 화면 글이 마지막으로 바뀐 시각(처음 공개·화 추가·다시 공개). 거두기·다시 열기는 글이 바뀌지 않아 그대로다.
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 최신순 목록은 마지막 공개 시각으로, 인기순 목록은 좋아요 수 → 마지막 공개 시각으로 줄 세운다.
    __table_args__ = (
        CheckConstraint(
            f"visibility IN ({_sql_in_list(NovelPublicationVisibility)})", name="ck_novel_publications_visibility"
        ),
        CheckConstraint("like_count >= 0 AND view_count >= 0", name="ck_novel_publications_counts_nonnegative"),
        Index("ix_novel_publications_published_at", published_at.desc(), novel_id.desc()),
        Index("ix_novel_publications_like_count", like_count.desc(), published_at.desc(), novel_id.desc()),
        CheckConstraint(
            f"moderation_status IN ({_sql_in_list(NovelPublicationModerationStatus)})",
            name="ck_novel_publications_moderation_status",
        ),
    )


class NovelChapterPublication(Base):
    """화 하나의 공개본 — 공개 시점에 얼린 개정과 그 화의 공개 화면 글(제목·작가의 말) 사본. 행이 있는 화가 공개된 화다.

    공개는 1화부터 이어진 앞부분만 된다(띄엄띄엄 공개하면 무료 화·구매 화의 경계가 흐려진다). 이어짐은 코드가 지키고, DB 는
    `(novel_id, ordinal)` 유니크로 같은 번호가 둘 생기는 경합만 막는다. `ordinal` 은 화 번호 사본이다(화 번호는 바뀌지 않는다).

    소유자가 화를 고치거나 스냅샷으로 되돌려도 이 행은 그대로다. 다시 공개해 심사를 통과해야 `revision_id`·사본이 바뀌고
    `edition` 이 하나 오른다 — 구매 기록이 "어느 판을 보고 샀는가"를 가리킬 수 있게 판 번호를 둔다.

    소설·화·개정을 지우면 함께 지워지는 `ON DELETE CASCADE` 다. 옛 판 코드는 개정 → 화 → 소설 순서로 지우므로 개정 FK 도
    cascade 여야 그 첫 문장이 FK 위반이 되지 않는다."""

    __tablename__ = "novel_chapter_publications"

    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapter_revisions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    edition: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 번호 유니크가 소설의 공개 화 목록 조회와 소설 DELETE 때 FK 검사도 겸한다. 개정 인덱스는 개정 DELETE 때 FK 검사용이다.
    __table_args__ = (
        CheckConstraint("ordinal >= 1", name="ck_novel_chapter_publications_ordinal_positive"),
        CheckConstraint("edition >= 1", name="ck_novel_chapter_publications_edition_positive"),
        Index("ux_novel_chapter_publications_novel_id_ordinal", "novel_id", "ordinal", unique=True),
        Index("ix_novel_chapter_publications_revision_id", "revision_id"),
    )


class NovelScreening(Base):
    """공개 전 텍스트 심사 한 번의 판정. 통과·거부만 남는다 — 심사 호출이 실패해(장애) 판정이 없으면 행이 없다.

    게시자 화면의 "확인 실패" 안내(어느 화의 어느 글이 걸렸는지)와 운영자의 심사 결과 확인이 읽는다. `reason` 은 심사
    모델이 쓴 사유로 운영자만 본다 — 게시자에게는 정해진 문구만 보인다. 사유가 소설 글을 옮겨 적을 수 있으므로 소설·화를
    지우면 함께 지운다(`ON DELETE CASCADE`, 다른 소설 자식 테이블과 같은 이유). `chapter_id` 가 NULL 이면 소설 제목·소개만
    심사한 것이다. `chapter_ordinal` 은 화가 지워지기 전까지의 안내용 사본이다."""

    __tablename__ = "novel_screenings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), nullable=True
    )
    chapter_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    outcome: Mapped[NovelScreeningOutcome] = mapped_column(Text, nullable=False)
    flagged_parts: Mapped[list[NovelScreeningPart]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 소설의 최근 심사 조회용이고 소설 DELETE 때 FK 검사도 겸한다. 화 인덱스는 화 DELETE 때 FK 검사용이다.
    __table_args__ = (
        CheckConstraint(f"outcome IN ({_sql_in_list(NovelScreeningOutcome)})", name="ck_novel_screenings_outcome"),
        CheckConstraint(
            f"flagged_parts <@ ARRAY[{_sql_in_list(NovelScreeningPart)}]::text[]",
            name="ck_novel_screenings_flagged_parts",
        ),
        CheckConstraint("outcome = 'rejected' OR flagged_parts = '{}'", name="ck_novel_screenings_passed_flags_none"),
        Index("ix_novel_screenings_novel_id_created_at", "novel_id", created_at.desc()),
        Index("ix_novel_screenings_chapter_id", "chapter_id"),
    )


class NovelPurchase(Base):
    """노벨 화 하나의 소장 구매. 구매자가 클로버로 산 화마다 한 행이고, 같은 화는 다시 사지 않는다(`(chapter_id,
    buyer_user_id)` 유니크 — 다시 공개로 본문이 바뀌어도 같은 화다). 무료 화와 게시자 본인의 열람은 행을 만들지 않는다.

    소설·화를 가리키는 칸은 **FK 없는 사본**이다. 게시자가 소설이나 마지막 묶음을 지우거나 탈퇴해도 이 행은 남아, 구매자에게
    "지워져 환급했다"·"게시자가 탈퇴했다"를 알려 줄 근거가 된다. 그래서 화 제목 같은 게시자 글의 사본은 두지 않는다 — 지운
    글이 여기 남으면 안 된다. 철회·운영 조치·원작 숨김은 이 행을 건드리지 않고 공개 상태로 판정하므로, 다시 공개되면 소장이
    그대로 살아난다.

    - `edition`: 산 시점의 화 공개본 판 번호(어느 판을 보고 샀는가).
    - `spend_ledger_id`: 이 구매의 차감 원장 행. 삭제 환급이 이 id 로 차감 배분을 찾아 깎은 로트로 되돌리고, 정산이 붙을 키다.
    - `price`: 산 시점의 가격 사본 — 가격 설정이 바뀌어도 환급액은 낸 값이다.
    - `refunded_at`·`refunded_amount`: 게시자 삭제로 환급한 시각과 실제로 돌려준 양. 결제가 전액 취소된 구매분에서 나간 몫은
      돌려주지 않으므로 `price` 보다 작을 수 있다. `refund_notification_id` 는 그때 구매자에게 보낸 알림이다(알림 문구의 화
      수·클로버 수가 이 행들에서 나온다).

    구매자가 탈퇴하면 행을 지우지 않고 `buyer_user_id` 만 비운다(`auth/withdrawal.py`). 화·가격·차감 원장·판·시각은 거래
    기록으로 남고 누가 샀는지만 사라진다. 구매자 칸이 빈 행은 삭제 환급에서 빠지고(탈퇴로 잔액이 이미 소멸했다) 독자 화면에는
    나타나지 않으며, 어드민의 구매 수·합계에는 들어간다(산 사람 수에는 들지 않는다). 유니크 `(chapter_id, buyer_user_id)` 는
    NULL 끼리 겹치지 않으므로 같은 화를 산 탈퇴 구매자가 여럿이어도 행이 함께 남는다.

    CHECK 는 `alembic check` 가 비교하지 않아 `pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다."""

    __tablename__ = "novel_purchases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    buyer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_purchases_buyer_user_id"), nullable=True
    )
    publisher_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_purchases_publisher_user_id"), nullable=False
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    chapter_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    edition: Mapped[int] = mapped_column(Integer, nullable=False)
    spend_ledger_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clover_ledger.id", name="fk_novel_purchases_spend_ledger_id"), nullable=False
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_notification_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("notifications.id", name="fk_novel_purchases_refund_notification_id"), nullable=True
    )

    # 화 단위 조회(구매했는가·삭제 환급)는 유니크 인덱스가, 소설 삭제 환급은 소설 인덱스가, 탈퇴 정리와 내 구매 목록은 구매자
    # 인덱스가 맡는다. 원장 유니크는 차감 하나가 구매 둘로 쓰이지 않게 하는 그물이다.
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_novel_purchases_price_positive"),
        CheckConstraint("chapter_ordinal >= 1 AND edition >= 1", name="ck_novel_purchases_ordinal_edition_positive"),
        CheckConstraint(
            "(refunded_at IS NULL) = (refunded_amount IS NULL)", name="ck_novel_purchases_refund_pair"
        ),
        CheckConstraint(
            "refunded_amount IS NULL OR (refunded_amount >= 0 AND refunded_amount <= price)",
            name="ck_novel_purchases_refunded_amount_range",
        ),
        CheckConstraint(
            "refund_notification_id IS NULL OR refunded_at IS NOT NULL",
            name="ck_novel_purchases_notification_after_refund",
        ),
        Index("ux_novel_purchases_chapter_id_buyer_user_id", "chapter_id", "buyer_user_id", unique=True),
        Index("ix_novel_purchases_novel_id", "novel_id"),
        Index("ix_novel_purchases_buyer_user_id", "buyer_user_id"),
        Index("ux_novel_purchases_spend_ledger_id", "spend_ledger_id", unique=True),
        Index("ix_novel_purchases_refund_notification_id", "refund_notification_id"),
    )


class NovelReaderPosition(Base):
    """노벨 독자가 화마다 마지막으로 읽은 문단. 소유자의 읽은 위치(`NovelReadingPosition` — 소설 주인 한 사람 것이라 사용자
    칸이 없다)와 따로 둔다. 독자는 여럿이라 (사용자, 화) 하나에 행 하나다. 게시자 본인이 노벨 화면으로 읽어도 이 테이블이다.

    `edition` 은 저장할 때 읽던 화 공개본의 판이다. 다시 공개로 판이 오르면 문단 수가 달라질 수 있어, 화면은 옛 위치를 새
    문단 수에 비례해 옮긴다(`paragraph_count` 는 그때의 문단 수). `finished_at` 은 끝까지 읽은 시각이고 한 번 찍히면 되돌리지
    않는다. 소설의 이어 읽기 자리는 그 사람의 그 소설 행 가운데 `updated_at` 이 가장 큰 것이다.

    소설·화를 지우면 함께 지워지는 `ON DELETE CASCADE` 다(모듈 docstring 의 예외). 새 코드는 삭제 함수가 직접 지우고,
    독자가 탈퇴하면 그 사람의 행을 지운다(`auth/withdrawal.py`). 복합 PK 는 `alembic check` 가 비교하지 않아
    `pytest.raises(IntegrityError)` 행위 테스트가 검증한다."""

    __tablename__ = "novel_reader_positions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_reader_positions_user_id"), primary_key=True
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    paragraph_index: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edition: Mapped[int] = mapped_column(Integer, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 이어 읽기 자리 조회용. 소설·화 인덱스는 소설·화 DELETE 때 FK 검사용이다(PK 가 사용자 칸으로 시작해 화 칸만으로는 못
    # 찾는다).
    __table_args__ = (
        CheckConstraint(
            "paragraph_index >= 0 AND paragraph_index < paragraph_count AND edition >= 1",
            name="ck_novel_reader_positions_range",
        ),
        Index("ix_novel_reader_positions_user_id_novel_id_updated_at", "user_id", "novel_id", updated_at.desc()),
        Index("ix_novel_reader_positions_novel_id", "novel_id"),
        Index("ix_novel_reader_positions_chapter_id", "chapter_id"),
    )


class NovelLike(Base):
    """노벨 좋아요. 소설 단위이고 (사용자, 소설) 하나에 행 하나다. 수는 `novel_publications.like_count` 에 따로 센다 — 행을
    넣은 요청만 수를 올리고 행을 지운 요청만 내린다.

    좋아요한 회원이 탈퇴해도 행을 지우지 않는다 — 작품 좋아요와 같다(지우면 탈퇴가 남의 소설 순위를 움직인다). 소설을
    지우면 함께 지워지는 `ON DELETE CASCADE` 다(모듈 docstring 의 예외)."""

    __tablename__ = "novel_likes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_likes_user_id"), primary_key=True
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 소설 DELETE 때 FK 검사용(PK 가 사용자 칸으로 시작한다).
    __table_args__ = (Index("ix_novel_likes_novel_id", "novel_id"),)


# 홈 노벨 섹션에 거는 자리 수. 자리 번호가 곧 홈의 순서다.
HOME_NOVEL_CURATION_SLOTS = 10


class HomeNovelCuration(Base):
    """홈 첫 화면의 노벨 섹션에 운영자가 거는 노벨. 자리(`position`, 1부터)마다 한 편이고, 한 노벨은 한 자리에만 걸린다.

    작품 홈 지정(`home_curations`)과 표를 나눈 것은 그 표의 PK 가 작품 유형 native enum 이라서다 — 노벨 칸을 더하려고
    enum 을 넓히면 그 값을 모르는 옛 코드가 행을 읽다 500 이 된다.

    걸린 노벨이 나중에 거둬지거나 이용제한돼도 행은 그대로 둔다 — 홈은 읽을 때 노벨 목록과 같은 조건으로 걸러 안 보이게
    하고, 다시 보일 수 있게 되면 그대로 다시 나온다(작품 지정과 같은 원칙). 작품 지정과 달리 소설은 게시자 삭제·탈퇴로
    실제로 지워지므로 소설 FK 는 `ON DELETE CASCADE` 이고, 새 코드는 삭제 함수가 직접 지운다.

    자리 범위 CHECK 는 `alembic check` 가 비교하지 않아 `pytest.raises(IntegrityError)` 행위 테스트가 검증한다."""

    __tablename__ = "home_novel_curations"

    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            f"position BETWEEN 1 AND {HOME_NOVEL_CURATION_SLOTS}", name="ck_home_novel_curations_position_range"
        ),
        Index("ux_home_novel_curations_novel_id", "novel_id", unique=True),
    )


# 댓글을 지운 사람. 운영자 삭제는 숨김과 달리 되돌리지 않는다.
NovelCommentDeletedBy = Literal["author", "publisher", "moderator"]


class NovelComment(Base):
    """노벨 화 하나에 달린 댓글. 답글·멘션·스티커·좋아요는 없다 — 화마다 최신순으로 쌓이는 글뿐이다.

    지우면(작성자 본인·게시자·운영자) 행은 남기고 본문을 비운 뒤 지운 사람과 시각을 적는다. 신고된 댓글이면 신고 행이 이
    댓글을 계속 가리켜 어느 댓글을 처리했는지 운영자가 찾아갈 수 있게 하려는 것이다. 원문은 신고 행의 증거 사본에만 남고 그
    보유 기간을 따른다. 운영자 숨김(`moderator_hidden`)은 본문을 남긴 채 독자에게만 감추는 것이라 되돌릴 수 있다.

    소설·화를 지우면 함께 지워지는 `ON DELETE CASCADE` 다(모듈 docstring 의 예외와 같은 이유). 새 코드는 삭제 함수가 직접
    지운다. 작성자가 탈퇴하면 그 사람의 댓글 행을 지운다(`auth/withdrawal.py`) — 답글이 없어 남겨 둘 까닭이 없다.

    CHECK 는 `alembic check` 가 비교하지 않아 `pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다."""

    __tablename__ = "novel_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_comments_author_user_id"), nullable=False
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderator_hidden: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    deleted_by: Mapped[NovelCommentDeletedBy | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 화의 최신순 목록과 화 DELETE 때 FK 검사는 화 인덱스가, 소설 DELETE 와 운영자의 소설별 댓글 목록은 소설 인덱스가,
    # 탈퇴 정리는 작성자 인덱스가 맡는다.
    __table_args__ = (
        CheckConstraint(
            f"deleted_by IS NULL OR deleted_by IN ({_sql_in_list(NovelCommentDeletedBy)})",
            name="ck_novel_comments_deleted_by",
        ),
        CheckConstraint("(deleted_at IS NULL) = (deleted_by IS NULL)", name="ck_novel_comments_deleted_pair"),
        CheckConstraint("(deleted_at IS NULL) = (body IS NOT NULL)", name="ck_novel_comments_body_until_deleted"),
        Index("ix_novel_comments_chapter_id_created_at", "chapter_id", created_at.desc(), id.desc()),
        Index("ix_novel_comments_novel_id_created_at", "novel_id", created_at.desc()),
        Index("ix_novel_comments_author_user_id", "author_user_id"),
    )


class NovelReport(Base):
    """노벨(공개 소설) 신고 — 소설 전체(`chapter_id` 없음) 또는 공개 화 하나. 신고 처리 기록과 신고 시점 공개본 사본(증거)의
    수명을 나눈 댓글 신고·채팅 응답 신고와 같은 구조다. 증거는 접수 때 복사해 두고 90일이 지나면 조회에서 빠지며 파기 작업이
    칸을 비운다(`scripts/ops/purge_novel_report_evidence.py`).

    소설·화 칸은 `SET NULL` 이다. 게시자는 소설이나 마지막 묶음을 지우고 탈퇴로 소설을 파기할 수 있는데, 그래도 신고와 증거
    사본은 보유 기간 동안 남아야 하고 지우는 쪽이 이 표를 몰라도 FK 위반으로 실패하지 않아야 한다. 그래서 무엇이 신고됐는지는
    증거 칸과 `publisher_user_id`·`chapter_ordinal` 로 읽힌다. `chapter_ordinal` 이 있으면 화 신고다(화가 지워져 `chapter_id`
    가 비어도 그렇다).

    같은 회원이 같은 화를 두 번 신고하는 것은 접수 코드가 신고자 행을 잠근 채 확인해 막고, 유니크 제약은 그물이다. 이 제약은
    NULLS DISTINCT 여야 한다 — 화·소설이 지워져 칸이 NULL 이 된 행끼리 겹쳐 그 DELETE 가 실패하면 안 된다(채팅 응답 신고와 같은
    이유). 소설 전체 신고는 `chapter_id` 가 NULL 이라 이 제약이 막지 못하고 접수 코드만 막는다.

    사유·상태는 작품·댓글 신고와 같은 native enum 타입을 값 추가 없이 그대로 쓴다. CHECK 는 `alembic check` 가 비교하지 않아
    `pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다."""

    __tablename__ = "novel_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_reports_reporter_user_id"), nullable=False
    )
    publisher_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_reports_publisher_user_id"), nullable=False
    )
    novel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novels.id", ondelete="SET NULL"), nullable=True
    )
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_chapters.id", ondelete="SET NULL"), nullable=True
    )
    chapter_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_category: Mapped[ReportReasonCategory] = mapped_column(
        Enum(ReportReasonCategory, name="report_reason_category"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus, name="report_status"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_novel_reports_resolved_by_admin_id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 신고 시점의 공개본 사본 — 소설 제목·소개, 화 신고면 그 화 제목과 본문 앞부분(`NOVEL_REPORT_EVIDENCE_BODY_CHARS`).
    evidence_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_chapter_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '90 days'"), nullable=False
    )
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 유니크의 첫 열이 소설인 것은 이 인덱스가 소설 DELETE 의 `SET NULL` 조회도 받게 하려는 것이다. 화 DELETE 의 조회는
    # 화 인덱스가 받는다.
    __table_args__ = (
        CheckConstraint("chapter_id IS NULL OR chapter_ordinal IS NOT NULL", name="ck_novel_reports_chapter_ordinal"),
        UniqueConstraint("novel_id", "chapter_id", "reporter_user_id", name="ux_novel_reports_novel_chapter_reporter"),
        Index("ix_novel_reports_chapter_id", "chapter_id", postgresql_where=text("chapter_id IS NOT NULL")),
        Index("ix_novel_reports_status_created", "status", "created_at", "id"),
        Index("ix_novel_reports_evidence_expires", "evidence_expires_at"),
    )


class NovelCommentReport(Base):
    """노벨 댓글 신고. `NovelReport` 와 같은 구조다 — 신고 시점의 댓글 본문을 증거로 복사해 두고 90일이 지나면 조회에서 빠지며
    파기 작업이 칸을 비운다.

    댓글·소설 칸은 `SET NULL` 이다. 작성자 탈퇴와 소설·묶음 삭제는 댓글 행을 지우는데, 신고와 증거 사본은 보유 기간 동안
    남아야 한다. 그래서 누가 쓴 댓글이었는지는 `comment_author_user_id` 가 따로 들고 있다. 유니크 제약(댓글, 신고자)은
    `NovelReport` 와 같은 이유로 NULLS DISTINCT 이고, 첫 열이 댓글인 것은 댓글 DELETE 의 `SET NULL` 조회를 받게 하려는 것이다."""

    __tablename__ = "novel_comment_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_comment_reports_reporter_user_id"), nullable=False
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_comments.id", ondelete="SET NULL"), nullable=True
    )
    novel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novels.id", ondelete="SET NULL"), nullable=True
    )
    comment_author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_novel_comment_reports_comment_author_user_id"), nullable=False
    )
    reason_category: Mapped[ReportReasonCategory] = mapped_column(
        Enum(ReportReasonCategory, name="report_reason_category"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus, name="report_status"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", name="fk_novel_comment_reports_resolved_by_admin_id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '90 days'"), nullable=False
    )
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("comment_id", "reporter_user_id", name="ux_novel_comment_reports_comment_reporter"),
        Index("ix_novel_comment_reports_novel_id", "novel_id", postgresql_where=text("novel_id IS NOT NULL")),
        Index("ix_novel_comment_reports_status_created", "status", "created_at", "id"),
        Index("ix_novel_comment_reports_evidence_expires", "evidence_expires_at"),
    )
