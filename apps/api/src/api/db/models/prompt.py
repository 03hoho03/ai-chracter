import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class PromptSet(Base):
    """프롬프트 문안 전체의 버전 헤더 + 화자 라벨.

    `status`는 Postgres enum이 아니라 Text다(`legal_documents` 선례) — draft/published
    외 값이 늘 여지가 있다. `version`은 draft일 때 null이고 게시 시점에 서버가 자동
    증가 정수 문자열을 부여한다. 부분 유니크 인덱스 2개(마이그레이션에서 생성)로
    무결성을 지킨다 — **초안은 (레인, 모델)마다 최대 1개, published 는 `(lane, model, version)` 중복 금지**다
    (`bcfbfd0cd960` 이전에는 둘 다 전역이었다 — 아래 `lane` 문단. 모델 축은 아래 `model` 문단).
    활성 세트 = 그 (레인, 모델)의 published 중 `published_at` 이 가장 최신인 것이다.

    `story_example_label`("서술자")과 `story_assistant_label`("진행자")이 둘로 갈리는
    것은 표류가 아니라 실측된 현재 동작이다 — 전개 예시에서만 다른 라벨을 쓴다.

    `relationship()`은 선언하지 않는다(리포 규약) — `prompt_sections`와의 관계는 순수
    FK로만 두고 삭제 순서는 호출부가 직접 지킨다.

    **`lane`**은 프롬프트 세트의 레인 분리 — `story`/`character`/
    `publish_filter` 3종 + 과도기 값 `legacy`(아무 코드도 읽지 않는 격리 버킷). Postgres
    enum이 아니라 Text다(같은 이유로 위 `status`와 동형). `server_default`는 모델에
    남기지 않는다 — 마이그레이션(`bcfbfd0cd960`)이 기존 행을 `'legacy'`로 백필한
    뒤 같은 리비전에서 기본값을 뗀다. 기본값을 남기면 `PromptSet(...)` 생성 지점이
    `lane`을 빠뜨려도 조용히 `'legacy'`가 되어 증상이 없다 — 떼야 NOT NULL 위반으로
    즉시 드러난다. 부분 유니크 인덱스 2개(초안 전역 1개·게시 버전 중복 금지)의 유니크
    범위가 전역에서 **레인별**로 좁혀진다(아래 `__table_args__`).

    **`model`**은 세트 체인의 모델 축(`llm/chat_models.py` 의 `PromptSetModelId`) — 글쓰기 모델의 레지스트리 id 이거나 판정
    전용 id(`haiku`)다. story·character 레인은 모델마다 초안·게시·복원·활성 판정이 따로 가는 독립 버전 체인을 갖는다.
    Gemini 세트는 모든 채널을 담는다. Claude 세트(sonnet·opus)는 생성에 쓰는 `system`·`generation` 채널과 그 레인의
    판정·요약 채널을, 판정 전용 세트는 판정·요약 채널만 갖는다(채널 집합의 소스는 `admin/prompts.py` 의 게시 검증 표다).
    판정·요약은 모델 배정 표(`PromptRoute`)의 (레인, 실효 방 모델, 단계) 칸이 고른 체인의 세트를, 그 칸의 행이 없으면 판정·요약
    모델 설정(기본 Gemini)의 세트를 읽는다. 심사·소설 묶음 경계·문단 수정은 Gemini 세트를 읽는다. 심사 레인은 Gemini 세트뿐이다.
    `lane` 과 달리
    `server_default` 를 남긴다 — 이 열을 모르는 옛 이미지로 되돌린 동안 어드민이 게시한 행도 Gemini 체인에 들어가고,
    모델을 적지 않은 생성 지점은 가장 안전한 쪽(지금까지와 같은 Gemini)으로 간다. 버전 번호는 레인·모델을 가리지 않는
    전역 자동 증가 그대로다.
    """

    __tablename__ = "prompt_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lane: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False, default="gemini", server_default="gemini")
    user_label: Mapped[str] = mapped_column(Text, nullable=False)
    story_assistant_label: Mapped[str] = mapped_column(Text, nullable=False)
    story_example_label: Mapped[str] = mapped_column(Text, nullable=False)
    character_assistant_label: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # `status == "draft"`/`published_at.desc()` 참조는 위 컬럼 정의가 먼저 실행돼 클래스
    # 바디 네임스페이스에 바인딩된 뒤라야 동작한다(`db/models/notice.py`의 `Notice` 참고).
    # bare `Mapped` 컬럼을 `postgresql_where`에 그대로 주면 autogenerate가 생성하는
    # 마이그레이션 소스에 `MappedColumn` 객체 repr이 박혀 `SyntaxError`가 난다(실측) —
    # `== "draft"`로 명시적 불리언 식을 만들어야 렌더러가 `sa.text(...)`로 정상 변환한다.
    __table_args__ = (
        Index("ix_prompt_sets_draft", "lane", "model", unique=True, postgresql_where=status == "draft"),
        Index(
            "ix_prompt_sets_lane_model_version_published",
            "lane",
            "model",
            "version",
            unique=True,
            postgresql_where=status == "published",
        ),
        Index("ix_prompt_sets_published_at", published_at.desc()),
        Index("ix_prompt_sets_lane_model_published_at", "lane", "model", published_at.desc()),
    )


class PromptSection(Base):
    """순서 있는 문안 조각.

    `channel`/`scope`/`slot`/`variant`는 전부 Text다 — 값이 늘 여지가 있다. `variant`는
    nullable 금지, 기본값 `''`다 — Postgres UNIQUE는 NULL끼리 중복으로 보지 않으므로
    nullable이면 `(set, channel, slot, NULL)` 행이 무한히 들어가 유니크가 무력화된다.

    `order` 유니크는 여기 두지 않는다 — 같은 자리에 들어가는 `variant` 여러 행(템플릿
    4종 등)이 같은 `order`를 공유해 단순 유니크가 성립하지 않는다. 그 검사는 게시
    검증(`(channel, variant)` 안에서)이 맡는다 — 복합 유니크로 우회하면
    `alembic check`가 비교하지 않는 사각지대에 들어간다.

    **유니크 키에 `scope`를 넣는다.** 처음 설계안의 키는
    `UNIQUE(prompt_set_id, channel, slot, variant)`(scope 미포함)였지만, 확정된
    시드 표를 `(channel, slot, variant)`만으로 묶어 보면 **충돌 그룹이
    둘**이다 — `('system', 'self_definition', '')`가 `scope=story`/`character` 두 행,
    `('publish_filter', 'intro_instruction', '')`가 `scope=character`/`story` 두 행(실제
    시드로 재현 확인). scope를 빼면 이 네 행이 유니크 위반으로 삽입 불가능하다(dev
    Postgres에서 실측: `duplicate key value violates unique constraint`). scope를
    포함한 5열 키로는 충돌이 없다. 그래서 설계안의 키 대신 시드 표 쪽을 따랐다.

    `relationship()`은 선언하지 않는다(리포 규약) — 세트 삭제 시 이 테이블 →
    `prompt_sets` 순서를 호출부가 직접 지킨다.
    """

    __tablename__ = "prompt_sections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prompt_sets.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    conditional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "ix_prompt_sections_set_channel_scope_slot_variant",
            "prompt_set_id",
            "channel",
            "scope",
            "slot",
            "variant",
            unique=True,
        ),
        Index("ix_prompt_sections_set_channel_order", "prompt_set_id", "channel", "order"),
    )


class PublishFilterTextSectionBackup(Base):
    """발행 심사가 작가 글을 싣던 시절의 publish_filter 텍스트 슬롯 행 보관함 — 코드가 읽지 않는 되돌리기 전용 테이블이다.

    발행 심사를 이미지 전용으로 바꾼 마이그레이션이 publish_filter 레인 세트마다 작가 글 슬롯 행을
    `prompt_sections` 에서 이 테이블로 옮기고, 그 마이그레이션의 downgrade 가 원래 id·순서·본문 그대로 되돌린다.
    컬럼은 `prompt_sections` 와 같다. 모델로 선언하는 이유는 `alembic check` 가 DB 에만 있는 테이블을 "제거할
    테이블"로 잡기 때문이다.
    """

    __tablename__ = "publish_filter_text_section_backups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prompt_sets.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    conditional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class PromptRoute(Base):
    """단계 배정 — (레인, 실효 방 모델, 단계)마다 어느 프롬프트 체인을 읽고 어느 모델을 부를지 한 행.

    표가 비어 있거나 그 키의 행이 없으면 지금까지의 환경 변수 규칙을 따른다. 어드민 배정 화면 말고도 채팅 방 턴과 요약 다시
    만들기의 판정·요약·추출 세트 고르기가 이 표를 읽는다(`chat/turn_prompt.py` 의 `judgment_prompt_sets`). 소설 레인은
    `room_model` 칸이 생성 단계에서 작업 모델이고, 작업 모델과 무관한 구조화 단계에서 표지 `any` 다.
    `lane`·`room_model`·`stage`·`chain_model`·`call_model`·`backend` 는 모두 enum 없는 Text 이고 값 목록 CHECK 도 두지
    않는다 — 단계나 모델이 늘 때마다 CHECK 를 DROP→ADD 하는 마이그레이션이 필요해지므로 값 범위는 앱의 저장 검사가 맡는다.

    CHECK 둘은 값 목록이 아니라 행의 모양을 지킨다. 생성 단계는 채팅 생성(`chat_generate`)과 소설 생성 셋(`novel_chapter`·
    `novel_outline`·`novel_episode_outline`)이다.
    - 생성 단계는 `chain_model` 이 NULL 이고 나머지 단계는 반드시 둔다 — 생성은 늘 방 모델(소설은 작업 모델)의 체인을 읽으므로
      따로 적을 체인이 없고, 판정·요약·추출·소설 구조화 호출은 어느 체인을 읽을지가 그 행의 뜻이다.
    - 생성 단계의 `call_model` 은 `room_model` 과 같다 — 대화 차감은 방 모델, 소설 차감은 작업 모델 단가로 매겨지므로 다른
      모델을 부르면 값과 원가가 어긋난다.

    다른 표를 가리키지 않아 FK 가 없다. 저장 이력은 `PromptRouteRevision` 이 표 전체 스냅샷으로 남긴다.
    """

    __tablename__ = "prompt_routes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lane: Mapped[str] = mapped_column(Text, nullable=False)
    room_model: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    chain_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_model: Mapped[str] = mapped_column(Text, nullable=False)
    backend: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_prompt_routes_lane_room_model_stage", "lane", "room_model", "stage", unique=True),
        CheckConstraint(
            "(stage IN ('chat_generate', 'novel_chapter', 'novel_outline', 'novel_episode_outline'))"
            " = (chain_model IS NULL)",
            name="ck_prompt_routes_generation_has_no_chain",
        ),
        CheckConstraint(
            "stage NOT IN ('chat_generate', 'novel_chapter', 'novel_outline', 'novel_episode_outline')"
            " OR call_model = room_model",
            name="ck_prompt_routes_generation_calls_room_model",
        ),
    )


class PromptRouteRevision(Base):
    """단계 배정 저장 한 번 = 한 행. 저장한 뒤의 `prompt_routes` 전체를 `rows` 에 스냅샷으로 남기고 쌓기만 한다.

    `rows` 는 `[{lane, roomModel, stage, chainModel, callModel, backend}]` 이고, 빈 배열은 표를 비워 전부 환경 변수 규칙으로
    돌린 저장이다 — 그래서 표가 비어 있어도 어드민이 쓴 적이 있는지는 이 표만 안다. `number` 는 저장 순번이고 유니크 인덱스가
    동시 저장 둘이 같은 번호를 계산했을 때 뒤 커밋을 막는다. `restored_from_id` 는 되돌리기로 만든 행이면 그 원본 행이다.

    `lanes` 는 그 저장이 어느 경로의 저장인지다 — NULL 은 표 전체를 갈아 끼운 옛 저장이거나 채팅 두 레인을 바꾸는 기존 경로의
    저장, `["novel"]` 은 소설 레인 경로의 저장이다. 어느 경로든 `rows` 는 저장한 뒤의 표 전체다. 서버 기본값을 두지 않고 NULL 을
    받는다 — 이 칸을 모르는 옛 이미지의 INSERT 가 칸을 빼고 들어와도 성공해야 한다.

    `relationship()` 은 선언하지 않는다(리포 규약) — FK 만 둔다.
    """

    __tablename__ = "prompt_route_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    restored_from_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("prompt_route_revisions.id"), nullable=True
    )
    lanes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_prompt_route_revisions_number", "number", unique=True),
        CheckConstraint("number > 0", name="ck_prompt_route_revisions_number_positive"),
    )


class PromptSetSemver(Base):
    """게시 세트 하나의 체인 판(`major.minor.patch`) — 세트당 최대 한 행.

    체인은 (레인, 모델) 세트 줄기다. 판을 `prompt_sets` 의 칸으로 두지 않고 따로 둔다 — 세트 칸이 늘면 활성 세트 캐시 직렬화·
    생성 리플레이 기록·측정 하네스의 내보내기가 그 칸을 다뤄야 하고, 이 표로 두면 서빙 경로가 판을 볼 길이 없다. 행이 없는 게시
    세트는 "번호 없는 옛 게시"다(이 표가 생기기 전의 게시, 이 표를 모르는 옛 이미지가 게시한 세트).

    `lane`·`model` 은 체인 안 번호 유니크를 걸려고 세트 칸을 복사한 값이다(게시 세트의 레인·모델은 바뀌지 않는다).
    `base_set_id` 는 이 판을 매길 때 견준 기준판(그 체인에서 판이 가장 큰 세트)이고 `level` 은 이번에 올린 단계다 — 기준판이
    없어 1.0.0 으로 시작한 판은 둘 다 NULL 이다. `base_set_id` 유니크는 "한 판은 다음 판의 기준이 한 번만 된다"를 지켜, 같은
    기준판을 읽은 동시 게시 둘이 서로 다른 단계로 올려 번호가 갈려도 뒤 커밋을 막는다.

    세트 FK 는 `ON DELETE CASCADE` 다 — 판은 세트의 부속 기록이라 세트가 지워지면 함께 지워진다. 기준판 FK 는 `ondelete` 를
    두지 않아 Postgres 기본값 `NO ACTION` 이다 — 다음 판의 기준이 된 세트를 지우면 판 사슬이 끊기므로 막는다. 막히는 쪽은 판이
    쌓인 세트를 지우려는 쪽이다: 판 매기기 블록을 쓰는 앞으로의 문안 마이그레이션의 downgrade, 체인을 지우는 테스트·코드. 그
    세트 위에 쌓인 나중 게시가 활성이라 그 세트를 지워도 서빙 문안이 실제로 되돌아가지 않으므로, 조용히 지우지 않고 멈추는 것이
    맞는 신호다. (이 표를 만든 리비전보다 앞선 리비전의 downgrade 는 여기 걸리지 않는다 — 이 표를 만든 리비전의 downgrade 가
    먼저 돌아 표를 지운 뒤에만 돌 수 있다.) 게시가 쌓인 체인은 한 문장으로 통째로 지워도 막힐 수 있다(지우는 행 순서에 따라
    기준판 FK 검사가 같은 문장의 다른 행이 일으킨 CASCADE 보다 먼저 돈다) — 나중 판부터 지운다.

    `relationship()` 은 선언하지 않는다(리포 규약).
    """

    __tablename__ = "prompt_set_semvers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prompt_sets.id", ondelete="CASCADE"), nullable=False
    )
    lane: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    major: Mapped[int] = mapped_column(Integer, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, nullable=False)
    patch: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("prompt_sets.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_prompt_set_semvers_prompt_set_id", "prompt_set_id", unique=True),
        Index("ix_prompt_set_semvers_chain_semver", "lane", "model", "major", "minor", "patch", unique=True),
        Index("ix_prompt_set_semvers_base_set_id", "base_set_id", unique=True),
        CheckConstraint("major >= 1 AND minor >= 0 AND patch >= 0", name="ck_prompt_set_semvers_parts_range"),
        CheckConstraint(
            "level IS NULL OR level IN ('major', 'minor', 'patch')", name="ck_prompt_set_semvers_level_values"
        ),
        CheckConstraint("(level IS NULL) = (base_set_id IS NULL)", name="ck_prompt_set_semvers_level_iff_base"),
        CheckConstraint(
            "base_set_id IS NULL OR base_set_id <> prompt_set_id", name="ck_prompt_set_semvers_not_own_base"
        ),
    )


class PromptSectionSemver(Base):
    """게시 세트의 섹션 하나의 판 — (세트, 섹션)마다 한 행.

    섹션은 `prompt_sections.channel` 값 하나(그 채널의 모든 행 묶음)이거나, 세트의 화자 라벨 넷을 묶은 예약 이름
    `speaker_labels` 다. 라벨은 생성 프롬프트의 대화 줄·예시 라벨과 정지 시퀀스로 실리므로 바뀌면 판이 바뀌어야 한다.
    `level` 은 이 게시에서 바뀌었으면 고른 단계, 안 바뀌었거나(기준판의 번호를 그대로 물려받음) 시작판이면 NULL 이다.
    같은 체인 안에서 같은 (섹션, 번호)는 늘 같은 내용을 가리킨다 — 그래서 번호를 매긴 게시본은 제자리에서 고치지 않는다.

    세트 FK 가 `ON DELETE CASCADE` 인 이유는 `PromptSetSemver` 와 같다. `relationship()` 은 선언하지 않는다(리포 규약).
    """

    __tablename__ = "prompt_section_semvers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prompt_sets.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    major: Mapped[int] = mapped_column(Integer, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, nullable=False)
    patch: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_prompt_section_semvers_set_channel", "prompt_set_id", "channel", unique=True),
        CheckConstraint("major >= 1 AND minor >= 0 AND patch >= 0", name="ck_prompt_section_semvers_parts_range"),
        CheckConstraint(
            "level IS NULL OR level IN ('major', 'minor', 'patch')", name="ck_prompt_section_semvers_level_values"
        ),
    )
