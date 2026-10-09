"""소설 라우트. 소설 삭제 하나를 뺀 모든 라우트(읽기 포함)가 라우터 수준에서 소설화 접근 게이트를 거친다.

소설 삭제는 게이트 밖의 세 번째 라우터(`owner_router`)에 있고 로그인·소유권만 본다. 자기 데이터를 지울 권리는 기능
허용과 무관하다 — 운영자가 허용을 거두거나 기능을 끄면 게이트가 닫히는데, 그때도 이용자가 자기 소설을 지울 수
있어야 한다(화면 진입점이 없어도 같은 라우트를 쓴다).

의존성은 이 순서로 돈다: 로그인(`get_current_user_id`) → 라우터 수준 소설화 게이트 → 쓰기 라우트만 재동의 게이트
(데코레이터) → 소유권(소설 또는 방) → 본문. 라우터 수준 의존성이 데코레이터 의존성보다 먼저 풀리므로, 허용이 없는
사용자는 재동의가 필요해도 기능 게이트의 403 을 받는다.

자기 데이터를 지우는 라우트(소설 삭제·마지막 묶음 삭제와 그 옛 이름인 마지막 장 삭제·스냅샷 삭제)는 재동의 게이트를 걸지
않는다 — 새 문안에 동의하지 않은 사용자도 자기가 만든 것을 지울 수 있어야 한다. 읽기와 작업 폴링도 막지 않는다. 읽은 위치
저장은 쓰기라 막는다(동의 전에는 위치가 남지 않을 뿐 읽기는 된다).

**잠금 순서는 사용자 → 작업 → 화 → 소설이다.** 작업 생성·환불·탈퇴·묶음 삭제가 사용자 행을 먼저 잡고(`billing.py`),
묶음 생성·다시 만들기의 성공 저장도 사용자 행 → 작업 행 → 화 → 소설 순서다(모자란 화를 그 자리에서 돌려주므로 사용자
행을 먼저 잡는다). 인물 카드를 고치는 경로(추가·수정·합치기)와 스냅샷 저장·복원도 사용자 행을 먼저 잡는다(복원은 사용자 →
화 → 소설). 사용자 행을 잡지 않는 것은 AI 수정의 성공 저장(작업 행 → 화), 읽은 위치 저장(화 키 공유 잠금과 자기 행만),
보드 배치 저장(소설 행만)이다. 그래서 여기서도 소설
행을 먼저 잠그지 않고, 화를 잠근 뒤 작업 행을 고치지 않는다(거꾸로 잡으면 겹치는 경로와 서로를 기다려 한쪽이 교착
오류로 끊긴다)."""

import base64
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.router import _ensure_content_playable, _get_owned_room
from api.content.access import is_open_to
from api.content.media_tags import strip_media_tags
from api.core.config import settings
from api.core.rate_limit import check_rate_limit
from api.core.rate_limit_gate import _too_many_requests
from api.core.s3 import build_display_key, build_thumbnail_key, generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.content import Content, ContentType
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.novel import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelReadingPosition,
    NovelSnapshot,
)
from api.db.models.persona import UserPersona
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session, get_session_factory
from api.legal.dependencies import require_legal_consent
from api.llm.chat_models import (
    CHAT_MODELS,
    DEFAULT_CHAT_MODEL,
    ChatModelId,
)
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.llm.model_access import effective_model, has_novel_premium_access
from api.novelize.access import require_novelize_access
from api.novelize.batches import ensure_batches
from api.novelize.billing import (
    ACTIVE_JOB_STATUSES,
    _lock_user,
    chain_price,
    create_charged_job,
    job_price,
    refund_active_jobs,
)
from api.novelize.deletion import delete_batch, delete_novels, erase_stale_ai_edit_previews
from api.novelize.boundary import episode_counts, suggest_end_turn
from api.novelize.characters import (
    CharacterNameTakenError,
    add_character,
    load_cards,
    merge_characters,
    update_character,
)
from api.novelize.episodes import chapter_max_turns, k_max, regenerate_ineligibility
from api.novelize.inputs import current_revision, load_novel_prompt_source
from api.novelize.runner import enqueue_chain_job, enqueue_job, expire_stale_jobs
from api.novelize.snapshots import SnapshotLimitError, restore_snapshot, save_snapshot
from api.novelize.schemas import (
    AI_EDIT_INSTRUCTION_MAX_LENGTH,
    AUTHOR_NOTE_MAX_LENGTH,
    BOARD_LAYOUT_MAX_BYTES,
    CHAPTER_BODY_MAX_LENGTH,
    CHAPTER_TITLE_MAX_LENGTH,
    CHARACTER_ALIASES_MAX_COUNT,
    CHARACTER_MEMO_MAX_LENGTH,
    CHARACTER_NAME_MAX_LENGTH,
    NOVEL_TITLE_MAX_LENGTH,
    SETTING_NOTES_MAX_LENGTH,
    SNAPSHOT_NAME_MAX_LENGTH,
    SYNOPSIS_MAX_LENGTH,
    NovelActiveJob,
    NovelAiEditPreview,
    NovelAiEditRequest,
    NovelBatchRegenerateRequest,
    NovelBatchSummary,
    NovelChainCreateRequest,
    NovelChainEstimate,
    NovelBoardLayout,
    NovelBoardLayoutResponse,
    NovelChainEstimateResponse,
    NovelChapterCandidate,
    NovelChapterCreateRequest,
    NovelChapterModel,
    NovelChapterProposalRequest,
    NovelChapterProposalResponse,
    NovelChapterRegenerateRequest,
    NovelChapterReadingPosition,
    NovelChapterResponse,
    NovelChapterSuggestion,
    NovelChapterSummary,
    NovelChapterUpdateRequest,
    NovelCharacterAddRequest,
    NovelCharacterListResponse,
    NovelCharacterMergeRequest,
    NovelCharacterResponse,
    NovelCharacterUpdateRequest,
    NovelCover,
    NovelDetailResponse,
    NovelJobResponse,
    NovelLastRead,
    NovelLimits,
    NovelListItem,
    NovelListResponse,
    NovelPendingAiEdit,
    NovelPrices,
    NovelProtagonistNameRequest,
    NovelReadingPositionRequest,
    NovelRevisionCreateRequest,
    NovelRevisionListResponse,
    NovelRevisionResponse,
    NovelRevisionRestoreRequest,
    NovelRegenerateOption,
    NovelRevisionSummary,
    NovelSettingNotesRequest,
    NovelSnapshotChapter,
    NovelSnapshotCharacter,
    NovelSnapshotCreateRequest,
    NovelSnapshotDetail,
    NovelSnapshotListResponse,
    NovelSnapshotRestoreResponse,
    NovelSnapshotSummary,
    NovelSource,
    NovelUpdateRequest,
    chapter_model_option,
)
from api.novelize.source import (
    SourceTurn,
    group_turns,
    load_candidates,
    load_segment,
    message_key,
    next_chapter_start,
    novel_prompt_names,
    segment_hash,
)
from api.novelize.text import split_paragraphs
from api.persona.schemas import PERSONA_NAME_MAX_LENGTH
from api.session.dependencies import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/novels", tags=["novels"], dependencies=[Depends(require_novelize_access)])
# 방에서 소설로 들어가는 두 라우트. prefix 가 달라 두 번째 라우터로 두고, `main.py` 는 별칭으로 import 한다.
room_router = APIRouter(prefix="/chat-rooms", tags=["novels"], dependencies=[Depends(require_novelize_access)])
# 소설화 게이트 밖의 라우트(소설 삭제). 게이트를 라우터 수준에 걸었으므로 라우트 하나만 빼려면 라우터를 나눠야 한다.
owner_router = APIRouter(prefix="/novels", tags=["novels"])

# 내 소설 목록 한 페이지. 테스트가 바꿔 끼울 수 있게 부를 때 모듈 전역으로 읽는다.
NOVEL_PAGE_SIZE = 20


def _novel_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})


# ── 소유권 ──────────────────────────────────────────────────────────────────
async def _get_owned_novel(db: AsyncSession, novel_id: uuid.UUID, user_id: uuid.UUID) -> Novel:
    """없으면 404, 남의 것이면 403(방 소유권 검사와 같은 모양). 행을 잠그지 않는다 — 소설 행을 먼저 잠그면 성공
    저장(작업 행 → 소설 행)과 교착한다."""
    novel = await db.get(Novel, novel_id, populate_existing=True)
    if novel is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    if novel.user_id != user_id:
        raise _novel_error(status.HTTP_403_FORBIDDEN, "NOVEL_FORBIDDEN")
    return novel


async def _owned_novel_dependency(
    novel_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> Novel:
    return await _get_owned_novel(db, novel_id, user_id)


async def _owned_room_dependency(
    room_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ChatRoom:
    return await _get_owned_room(db, room_id, user_id)


# ── 응답 조립 ───────────────────────────────────────────────────────────────
async def _chapter_models(db: AsyncSession, user_id: uuid.UUID) -> tuple[list[NovelChapterModel], bool]:
    """장 확인 화면에서 고를 수 있는 모델과 그 가격, 그리고 상위 모델 허용 여부. 기본 모델은 늘 맨 앞에 있고, 상위 모델은
    장 요청 게이트(`_require_chapter_model`)와 같은 판정이 참일 때만 싣는다 — 화면이 고를 수 있게 보여 준 모델을 요청이
    막는 어긋남이 없게."""
    allowed = await has_novel_premium_access(db, user_id)
    models = [chapter_model_option(spec.id) for spec in CHAT_MODELS if spec.id == DEFAULT_CHAT_MODEL or allowed]
    return models, allowed


async def _last_chapter_model(db: AsyncSession, novel_id: uuid.UUID, *, allowed: bool) -> ChatModelId:
    """이 소설에서 가장 최근에 성공한 장 작업의 모델을 지금 쓸 모델로 읽는다. 실패한 장은 환불돼 사용자가 그 모델로 글을
    받은 적이 없으므로 세지 않는다."""
    stored = await db.scalar(
        select(NovelJob.model)
        .where(
            NovelJob.novel_id == novel_id,
            NovelJob.kind.in_(("chapter_generate", "chapter_regenerate")),
            NovelJob.status == "succeeded",
        )
        .order_by(NovelJob.created_at.desc(), NovelJob.id.desc())
        .limit(1)
    )
    return effective_model(stored, allowed=allowed)


def _prices() -> NovelPrices:
    return NovelPrices(
        chapter_generate=job_price("chapter_generate"),
        chapter_regenerate=job_price("chapter_regenerate"),
        ai_edit=job_price("ai_edit"),
    )


_LIMITS = NovelLimits(
    setting_notes_max_length=SETTING_NOTES_MAX_LENGTH,
    chapter_body_max_length=CHAPTER_BODY_MAX_LENGTH,
    ai_edit_instruction_max_length=AI_EDIT_INSTRUCTION_MAX_LENGTH,
    protagonist_name_max_length=PERSONA_NAME_MAX_LENGTH,
    title_max_length=NOVEL_TITLE_MAX_LENGTH,
    synopsis_max_length=SYNOPSIS_MAX_LENGTH,
    chapter_title_max_length=CHAPTER_TITLE_MAX_LENGTH,
    author_note_max_length=AUTHOR_NOTE_MAX_LENGTH,
    character_name_max_length=CHARACTER_NAME_MAX_LENGTH,
    character_aliases_max_count=CHARACTER_ALIASES_MAX_COUNT,
    character_memo_max_length=CHARACTER_MEMO_MAX_LENGTH,
    snapshot_name_max_length=SNAPSHOT_NAME_MAX_LENGTH,
    board_layout_max_bytes=BOARD_LAYOUT_MAX_BYTES,
)


async def _chapter_summaries(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelChapterSummary]:
    """화마다 현재 개정(번호 최대) 하나를 붙인 목차. 개정은 화마다 `revision_no` 내림차순 첫 행이다. 묶음 없는 화는
    빼고 싣는다 — 상세는 답하기 전에 묶음을 채우므로(`ensure_batches`) 그런 화는 그 사이 옛 판 코드가 넣은 것뿐이고,
    다음 조회 때 묶음을 받아 나타난다."""
    latest = (
        select(NovelChapterRevision)
        .distinct(NovelChapterRevision.chapter_id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapterRevision.chapter_id, NovelChapterRevision.revision_no.desc())
    )
    revisions = {revision.chapter_id: revision for revision in (await db.scalars(latest)).all()}
    # 읽은 위치는 소설 단위로 한 번에 읽어 화마다 나눠 준다 — 화마다 따로 읽으면 화 수만큼 쿼리가 는다.
    positions = {
        position.chapter_id: position
        for position in (
            await db.scalars(select(NovelReadingPosition).where(NovelReadingPosition.novel_id == novel_id))
        ).all()
    }
    chapters = (
        await db.scalars(
            select(NovelChapter)
            .where(NovelChapter.novel_id == novel_id)
            .order_by(NovelChapter.ordinal)
            .execution_options(populate_existing=True)
        )
    ).all()
    summaries: list[NovelChapterSummary] = []
    for chapter in chapters:
        revision = revisions.get(chapter.id)
        if revision is None or chapter.batch_id is None:
            # 화 행과 첫 개정은 한 트랜잭션에서 함께 들어가므로 개정 없는 화는 없다.
            continue
        position = positions.get(chapter.id)
        summaries.append(
            NovelChapterSummary(
                id=chapter.id,
                ordinal=chapter.ordinal,
                assistant_message_count=chapter.assistant_message_count,
                current_revision_id=revision.id,
                current_revision_no=revision.revision_no,
                current_revision_source=revision.source,
                updated_at=revision.created_at,
                created_at=chapter.created_at,
                batch_id=chapter.batch_id,
                episode_index=chapter.episode_index,
                title=chapter.title,
                title_edited=chapter.title_edited_at is not None,
                summary=chapter.summary,
                author_note=chapter.author_note,
                char_count=len(revision.body),
                finished_reading=position is not None and position.finished_at is not None,
                reading_position=None
                if position is None
                else NovelChapterReadingPosition(
                    paragraph_index=position.paragraph_index,
                    paragraph_count=position.paragraph_count,
                    revision_id=position.revision_id,
                    finished=position.finished_at is not None,
                ),
            )
        )
    return summaries


def _regenerate_options(
    chapter_models: list[NovelChapterModel], *, episodes: int, turns: int
) -> list[NovelRegenerateOption]:
    options: list[NovelRegenerateOption] = []
    for option in chapter_models:
        reason = regenerate_ineligibility(option.id, episode_count=episodes, turn_count=turns)
        options.append(
            NovelRegenerateOption(
                model=option.id,
                name=option.name,
                cost=job_price("chapter_regenerate", option.id, episodes),
                eligible=reason is None,
                ineligible_reason=reason,
            )
        )
    return options


async def _batch_summaries(
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapters: list[NovelChapterSummary],
    chapter_models: list[NovelChapterModel],
) -> list[NovelBatchSummary]:
    """묶음 번호 순 묶음 목록과 묶음마다 다시 만들기 금액. 화 수는 목차의 화에서 센다(다시 만들기가 지키는 화 수)."""
    chapter_ids: dict[uuid.UUID, list[uuid.UUID]] = {}
    for chapter in sorted(chapters, key=lambda c: (c.episode_index, c.ordinal)):
        chapter_ids.setdefault(chapter.batch_id, []).append(chapter.id)
    batches = (
        await db.scalars(select(NovelBatch).where(NovelBatch.novel_id == novel_id).order_by(NovelBatch.ordinal))
    ).all()
    return [
        NovelBatchSummary(
            id=batch.id,
            ordinal=batch.ordinal,
            chapter_ids=chapter_ids[batch.id],
            assistant_message_count=batch.assistant_message_count,
            regenerate_options=_regenerate_options(
                chapter_models, episodes=len(chapter_ids[batch.id]), turns=batch.assistant_message_count
            ),
        )
        for batch in batches
        if batch.id in chapter_ids
    ]


async def _last_read(db: AsyncSession, novel_id: uuid.UUID) -> NovelLastRead | None:
    position = await db.scalar(
        select(NovelReadingPosition)
        .where(NovelReadingPosition.novel_id == novel_id)
        .order_by(NovelReadingPosition.updated_at.desc())
        .limit(1)
    )
    if position is None:
        return None
    return NovelLastRead(
        chapter_id=position.chapter_id,
        paragraph_index=position.paragraph_index,
        paragraph_count=position.paragraph_count,
        revision_id=position.revision_id,
        updated_at=position.updated_at,
    )


async def _work_thumbnail_asset_ids(db: AsyncSession, content_ids: set[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """원작마다 지금 게시본의 썸네일 자산. 게시본이 없거나 썸네일이 없는 원작, 지워진 원작은 빠진다."""
    rows = await db.execute(
        select(Content.id, StoryVersionDetail.thumbnail_asset_id, CharacterVersionDetail.thumbnail_asset_id)
        .outerjoin(StoryVersionDetail, StoryVersionDetail.content_version_id == Content.current_published_version_id)
        .outerjoin(
            CharacterVersionDetail, CharacterVersionDetail.content_version_id == Content.current_published_version_id
        )
        .where(Content.id.in_(content_ids))
    )
    found: dict[uuid.UUID, uuid.UUID] = {}
    for content_id, story_thumbnail, character_thumbnail in rows.tuples():
        thumbnail = story_thumbnail or character_thumbnail
        if thumbnail is not None:
            found[content_id] = thumbnail
    return found


async def _covers(db: AsyncSession, novels: list[Novel]) -> dict[uuid.UUID, tuple[NovelCover, str | None]]:
    """소설마다 표지와 원작 썸네일 주소. 고른 표지가 있으면 그 이미지를 크게 그리는 변형으로, 없으면 원작 썸네일이다.
    목록 한 페이지를 쿼리 두 번으로 읽는다(원작 썸네일 자산, 자산 행). 서명은 네트워크 없이 로컬에서 한다."""
    work_thumbnails = await _work_thumbnail_asset_ids(db, {novel.content_id for novel in novels})
    asset_ids = {novel.cover_asset_id for novel in novels if novel.cover_asset_id is not None}
    asset_ids |= set(work_thumbnails.values())
    storage_keys = (
        dict((await db.execute(select(Asset.id, Asset.storage_key).where(Asset.id.in_(asset_ids)))).tuples().all())
        if asset_ids
        else {}
    )
    covers: dict[uuid.UUID, tuple[NovelCover, str | None]] = {}
    for novel in novels:
        work_asset_id = work_thumbnails.get(novel.content_id)
        work_key = storage_keys.get(work_asset_id) if work_asset_id is not None else None
        work_url = generate_presigned_get_url(build_thumbnail_key(work_key)) if work_key is not None else None
        cover_key = storage_keys.get(novel.cover_asset_id) if novel.cover_asset_id is not None else None
        if cover_key is not None:
            cover_url = generate_presigned_get_url(build_display_key(cover_key))
            cover = NovelCover(asset_id=novel.cover_asset_id, url=cover_url, source="generated")
        else:
            cover = NovelCover(asset_id=None, url=work_url, source="work")
        covers[novel.id] = (cover, work_url)
    return covers


async def _source(db: AsyncSession, novel: Novel, thumbnail_url: str | None) -> NovelSource:
    """원작 상세로 가는 링크는 지금 이 사용자가 그 작품을 볼 수 있을 때만 건다 — 게시본이 있고 이용 제한·삭제가 아니며
    남의 비공개 작품이 아닐 때(작품 상세가 본문을 보여 주는 조건과 같다)."""
    content = await db.get(Content, novel.content_id, populate_existing=True)
    linkable = (
        content is not None
        and content.current_published_version_id is not None
        and is_open_to(content, novel.user_id)
    )
    return NovelSource(thumbnail_url=thumbnail_url, linkable=linkable)


async def _chain_progress(db: AsyncSession, job: NovelJob) -> tuple[int | None, int | None]:
    """연쇄 생성 부모의 (끝낸 묶음 수, 계획한 묶음 수). 연쇄가 아니면 둘 다 None. 계획한 묶음 수는 차감할 때 부모 행에
    적어 둔 값이다 — 차감액에서 지금 설정으로 되읽으면 그 사이 화 수 상한이 바뀐 배포 뒤에 틀린 수가 나온다."""
    if job.kind != "chain_generate":
        return None, None
    completed = await db.scalar(
        select(func.count())
        .select_from(NovelJob)
        .where(NovelJob.parent_job_id == job.id, NovelJob.status == "succeeded")
    )
    return int(completed or 0), job.planned_batches


async def _active_job(db: AsyncSession, novel_id: uuid.UUID) -> NovelActiveJob | None:
    """진행 중 작업. 연쇄 생성 중에는 부모와 묶음 하나를 맡은 자식이 함께 진행 중이라, 부모(`parent_job_id` 가 빈 행)를
    고른다 — 화면은 이 작업을 폴링해 끝을 판단한다."""
    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.novel_id == novel_id, NovelJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(NovelJob.parent_job_id.is_not(None), NovelJob.created_at)
        .execution_options(populate_existing=True)
        .limit(1)
    )
    if job is None:
        return None
    completed, planned = await _chain_progress(db, job)
    return NovelActiveJob(
        id=job.id,
        kind=job.kind,
        status=job.status,
        chapter_id=job.chapter_id,
        batch_id=job.batch_id,
        completed_batches=completed,
        planned_batches=planned,
    )


async def _pending_ai_edits(
    db: AsyncSession, novel_id: uuid.UUID, chapters: list[NovelChapterSummary]
) -> list[NovelPendingAiEdit]:
    """성공했고 적용·버리기 전이며 기준 개정이 그 장의 현재 개정인 AI 수정. 현재 개정은 목차가 이미 읽은 값을 쓴다.

    결과 본문이 비워진 행은 뺀다. 목차와 이 조회는 다른 문장이라, 그 사이 새 개정이 커밋되고 낡은 미리보기가
    비워지면 기준 개정은 아직 목차의 현재 개정인데 본문이 없는 행을 보게 된다."""
    current_revision_ids = [chapter.current_revision_id for chapter in chapters]
    if not current_revision_ids:
        return []
    jobs = await db.scalars(
        select(NovelJob)
        .where(
            NovelJob.novel_id == novel_id,
            NovelJob.kind == "ai_edit",
            NovelJob.status == "succeeded",
            NovelJob.result_revision_id.is_(None),
            NovelJob.dismissed_at.is_(None),
            NovelJob.base_revision_id.in_(current_revision_ids),
            NovelJob.instruction.is_not(None),
            NovelJob.result_text.is_not(None),
        )
        .order_by(NovelJob.created_at.desc(), NovelJob.id.desc())
        .execution_options(populate_existing=True)
    )
    pending: list[NovelPendingAiEdit] = []
    for job in jobs.all():
        # 성공한 AI 수정은 만들 때 장·범위를 반드시 채운다. 지시·결과 본문은 위 조건으로 걸렀다.
        assert (
            job.chapter_id is not None
            and job.paragraph_start is not None
            and job.paragraph_end is not None
            and job.instruction is not None
            and job.result_text is not None
        )
        pending.append(
            NovelPendingAiEdit(
                id=job.id,
                chapter_id=job.chapter_id,
                paragraph_start=job.paragraph_start,
                paragraph_end=job.paragraph_end,
                instruction=job.instruction,
                result_text=job.result_text,
                created_at=job.created_at,
            )
        )
    return pending


async def _detail(db: AsyncSession, novel_id: uuid.UUID) -> NovelDetailResponse:
    """상세. 묶음 없는 화나 빈 묶음이 있으면 먼저 고쳐 커밋한다 — 고치지 않으면 그 화가 목차와 묶음 목록에서 빠진다."""
    if await ensure_batches(db, novel_id):
        await db.commit()
    novel = await db.get_one(Novel, novel_id, populate_existing=True)
    chapters = await _chapter_summaries(db, novel.id)
    chapter_models, premium_allowed = await _chapter_models(db, novel.user_id)
    cover, work_thumbnail = (await _covers(db, [novel]))[novel.id]
    return NovelDetailResponse(
        id=novel.id,
        chat_room_id=novel.chat_room_id,
        content_id=novel.content_id,
        content_type=novel.content_type,
        content_title=novel.content_title,
        character_name=novel.character_name,
        protagonist_name=novel.protagonist_name,
        setting_notes=novel.setting_notes,
        title=novel.title,
        title_edited=novel.title_edited_at is not None,
        synopsis=novel.synopsis,
        cover=cover,
        source=await _source(db, novel, work_thumbnail),
        batches=await _batch_summaries(db, novel.id, chapters, chapter_models),
        chapters=chapters,
        last_read=await _last_read(db, novel.id),
        active_job=await _active_job(db, novel.id),
        pending_ai_edits=await _pending_ai_edits(db, novel.id, chapters),
        prices=_prices(),
        limits=_LIMITS,
        created_at=novel.created_at,
        updated_at=novel.updated_at,
        chapter_models=chapter_models,
        last_chapter_model=await _last_chapter_model(db, novel.id, allowed=premium_allowed),
    )


async def _expire_and_detail(db: AsyncSession, novel_id: uuid.UUID) -> NovelDetailResponse:
    """지연 정리 — 서버 재기동으로 사라진 작업이 진행 중으로 남아 있으면 실패·환불로 끝낸 뒤 상세를 답한다. 그래야
    화면이 죽은 작업을 폴링하지 않고, 다음 작업 요청이 그 작업 때문에 409 를 받지 않는다."""
    await expire_stale_jobs(db, novel_id=novel_id)
    await db.commit()
    return await _detail(db, novel_id)


def _refunded_amount(job: NovelJob) -> int:
    """돌려준 클로버. 금액 칸이 비었는데 환불 시각이 찍힌 행은 금액 칸을 모르는 옛 코드가 실패를 전액 환불한 것이다."""
    if job.refunded_amount is not None:
        return job.refunded_amount
    return job.charged_amount if job.refunded_at is not None else 0


async def _job_response(db: AsyncSession, job: NovelJob) -> NovelJobResponse:
    ai_edit = (
        NovelAiEditPreview(
            base_revision_id=job.base_revision_id,
            paragraph_start=job.paragraph_start,
            paragraph_end=job.paragraph_end,
            instruction=job.instruction,
            result_text=job.result_text,
        )
        if job.kind == "ai_edit"
        else None
    )
    completed, planned = await _chain_progress(db, job)
    return NovelJobResponse(
        id=job.id,
        kind=job.kind,
        status=job.status,
        charged_amount=job.charged_amount,
        refunded=job.refunded_at is not None,
        failure_reason=job.failure_code,
        chapter_id=job.chapter_id,
        revision_id=job.result_revision_id,
        ai_edit=ai_edit,
        created_at=job.created_at,
        model=None if job.kind == "ai_edit" else job.model or DEFAULT_CHAT_MODEL,
        refunded_amount=_refunded_amount(job),
        batch_id=job.batch_id,
        completed_batches=completed,
        planned_batches=planned,
    )


# ── 방의 소설 ───────────────────────────────────────────────────────────────
async def _room_novel_id(db: AsyncSession, room_id: uuid.UUID) -> uuid.UUID | None:
    novel_id: uuid.UUID | None = await db.scalar(select(Novel.id).where(Novel.chat_room_id == room_id))
    return novel_id


@room_router.get("/{room_id}/novel")
async def get_room_novel(
    room: ChatRoom = Depends(_owned_room_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """방에서 만든 소설. 아직 없으면 404 `NOVEL_NOT_FOUND`."""
    novel_id = await _room_novel_id(db, room.id)
    if novel_id is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_NOT_FOUND")
    return await _expire_and_detail(db, novel_id)


@room_router.post("/{room_id}/novel", dependencies=[Depends(require_legal_consent)])
async def create_room_novel(
    response: Response,
    room: ChatRoom = Depends(_owned_room_dependency),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """방의 소설을 만들거나, 이미 있으면 그대로 돌려준다(201 / 200). 무과금이다.

    원작 제목·캐릭터 이름·레인은 방이 고정한 버전에서 사본으로 떠 둔다 — 방이 지워지거나 작품이 바뀌어도 소설은
    그대로 읽혀야 한다. 주인공 이름은 방에 건 대화 프로필 이름, 없으면 그 버전의 작품 기본 이름이고, 둘 다 없으면
    비워 두었다가 첫 장을 만들기 전에 받는다. 이용 제한 작품이어도 만들 수 있다(모델을 부르지 않는다)."""
    existing = await _room_novel_id(db, room.id)
    if existing is not None:
        return await _expire_and_detail(db, existing)

    content = await db.get_one(Content, room.content_id)
    persona = await db.get(UserPersona, room.persona_id) if room.persona_id is not None else None
    character_name: str | None
    if content.type == ContentType.STORY:
        story = await db.get_one(StoryVersionDetail, room.content_version_id)
        title, character_name, default_user_name = story.name, None, story.default_user_name
    else:
        character = await db.get_one(CharacterVersionDetail, room.content_version_id)
        title, character_name, default_user_name = character.name, character.name, character.default_user_name
    protagonist = (persona.name if persona is not None else "") or default_user_name.strip()

    # 같은 방에 두 요청이 겹치면 방 유니크 인덱스에서 하나만 들어가고 다른 쪽은 아무것도 하지 않는다.
    inserted = await db.scalar(
        insert(Novel)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            chat_room_id=room.id,
            content_id=content.id,
            content_type=content.type.value,
            content_title=title,
            character_name=character_name,
            protagonist_name=protagonist or None,
        )
        .on_conflict_do_nothing(index_elements=[Novel.chat_room_id])
        .returning(Novel.id)
    )
    await db.commit()
    if inserted is None:
        novel_id = await _room_novel_id(db, room.id)
        assert novel_id is not None  # 충돌한 상대가 커밋한 행이다
        return await _detail(db, novel_id)
    response.status_code = status.HTTP_201_CREATED
    return await _detail(db, inserted)


# ── 목록·상세 ───────────────────────────────────────────────────────────────
def _encode_cursor(updated_at: datetime, novel_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([updated_at.isoformat(), str(novel_id)]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        updated_at, novel_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(updated_at), uuid.UUID(novel_id)
    except (ValueError, TypeError) as exc:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_CURSOR_INVALID") from exc


@router.get("")
async def list_novels(
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelListResponse:
    """내 소설을 최근 수정 순으로. 원래 방이 지워진 소설도 나온다(`chatRoomId` null)."""
    chapter_count = (
        select(func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == Novel.id).scalar_subquery()
    )
    query = (
        select(Novel, chapter_count)
        .where(Novel.user_id == user_id)
        .order_by(Novel.updated_at.desc(), Novel.id.desc())
    )
    if cursor is not None:
        # 오른쪽은 평범한 튜플이다 — `tuple_` 끼리 비교하면 mypy 가 결과를 bool 로 본다.
        query = query.where(tuple_(Novel.updated_at, Novel.id) < _decode_cursor(cursor))
    page_size = NOVEL_PAGE_SIZE
    rows = (await db.execute(query.limit(page_size + 1))).all()
    page = rows[:page_size]
    next_cursor = _encode_cursor(page[-1][0].updated_at, page[-1][0].id) if len(rows) > page_size else None
    covers = await _covers(db, [novel for novel, _count in page])
    return NovelListResponse(
        items=[
            NovelListItem(
                id=novel.id,
                chat_room_id=novel.chat_room_id,
                content_type=novel.content_type,
                content_title=novel.content_title,
                character_name=novel.character_name,
                chapter_count=count,
                created_at=novel.created_at,
                updated_at=novel.updated_at,
                title=novel.title,
                cover=covers[novel.id][0],
            )
            for novel, count in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/{novel_id}")
async def get_novel(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """소설 머리·설정 노트·목차(장마다 현재 개정)·진행 중 작업·지금 단가. 답하기 전에 죽은 작업을 정리한다."""
    return await _expire_and_detail(db, novel.id)


@owner_router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_novel(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """소설과 그 아래 행을 지운다. 진행 중 작업은 같은 트랜잭션에서 먼저 환불한다 — 지우고 나면 실행 경로가 실패해도
    환불할 행이 없다. 원래 방은 그대로다. 소설화 허용이 없어도(기능 꺼짐·허용 회수) 자기 소설이면 지운다.

    사용자 행을 먼저 잠근다. 같은 사용자의 작업 생성이 이 사이에 끼어들면 지울 소설에 새 작업 행이 붙어 소설 DELETE
    가 FK 위반이 되는데, 작업 생성도 사용자 행을 먼저 잡으므로 둘이 줄을 선다. 소설 행은 잠그지 않는다(모듈 머리)."""
    await _lock_user(db, novel.user_id)
    # 행이 곧 지워져 남지 않으므로 사유 칸은 어느 값이든 같다 — 우리 쪽 사정으로 끝낸 작업이라 `internal` 이다.
    await refund_active_jobs(db, novel_id=novel.id, failure_code="internal")
    await delete_novels(db, [novel.id])
    await db.commit()


# ── 설정 노트·주인공 이름 ───────────────────────────────────────────────────
@router.put("/{novel_id}/notes", dependencies=[Depends(require_legal_consent)])
async def update_novel_notes(
    payload: NovelSettingNotesRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """설정 노트를 바꾼다. 다음 장 생성과 AI 수정부터 실린다(이미 만든 장은 그대로)."""
    await db.execute(
        update(Novel).where(Novel.id == novel.id).values(setting_notes=payload.setting_notes, updated_at=func.now())
    )
    await db.commit()
    return await _detail(db, novel.id)


@router.put("/{novel_id}/protagonist-name", dependencies=[Depends(require_legal_consent)])
async def update_novel_protagonist_name(
    payload: NovelProtagonistNameRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """주인공 이름을 바꾼다. 다음 장 생성부터 쓰이고 이미 만든 장 본문은 그대로다."""
    await db.execute(
        update(Novel)
        .where(Novel.id == novel.id)
        .values(protagonist_name=payload.protagonist_name, updated_at=func.now())
    )
    await db.commit()
    return await _detail(db, novel.id)


@router.patch("/{novel_id}", dependencies=[Depends(require_legal_consent)])
async def update_novel(
    payload: NovelUpdateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """소설 제목·소개·표지를 바꾼다(보낸 칸만). 제목을 바꾸면 그 뒤로 생성이 제목을 덮지 않는다 — 같은 문장에서 제목과
    고친 시각을 함께 쓰므로, 겹친 생성 저장의 "고친 적 없을 때만 쓰기"와 엇갈리지 않는다.

    표지는 내 생성 이미지 중 준비가 끝난 것만 된다(아니면 422 `NOVEL_COVER_INVALID` — 남의 것·없는 것·업로드 이미지·준비
    중을 가르지 않는다). 그 이미지 행을 키 공유 잠금으로 확인한다 — 확인과 저장 사이에 이미지가 지워지면 저장이 FK 위반으로
    500 이 되는데, 잠금을 쥐면 삭제가 이 저장이 끝나기를 기다렸다가 표지를 비운다(표지 FK 는 SET NULL)."""
    values: dict[str, object] = {}
    if payload.title is not None:
        values["title"] = payload.title
        values["title_edited_at"] = func.now()
    if payload.synopsis is not None:
        values["synopsis"] = payload.synopsis
    if "cover_asset_id" in payload.model_fields_set:
        if payload.cover_asset_id is not None:
            usable = await db.scalar(
                select(Asset.id)
                .where(
                    Asset.id == payload.cover_asset_id,
                    Asset.owner_user_id == novel.user_id,
                    Asset.kind == AssetKind.GENERATED,
                    Asset.status == AssetStatus.READY,
                )
                .with_for_update(key_share=True, read=True)
            )
            if usable is None:
                raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_COVER_INVALID")
        values["cover_asset_id"] = payload.cover_asset_id
    if values:
        await db.execute(update(Novel).where(Novel.id == novel.id).values(**values, updated_at=func.now()))
        await db.commit()
    return await _detail(db, novel.id)


@router.patch("/{novel_id}/chapters/{chapter_id}", dependencies=[Depends(require_legal_consent)])
async def update_novel_chapter(
    chapter_id: uuid.UUID,
    payload: NovelChapterUpdateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelDetailResponse:
    """화 제목·작가의 말을 바꾼다(보낸 칸만, 무과금). 본문은 개정 라우트로 고친다. 작가의 말은 프롬프트에 실리지 않는다.

    제목을 보내면 고친 시각을 찍어 다시 만들기가 그 제목을 덮지 않게 하고, 제목에 null 을 보내면 제목과 고친 시각을 함께
    비워 다음 다시 만들기가 AI 제목을 다시 쓰게 한다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    values: dict[str, object] = {}
    if "title" in payload.model_fields_set:
        values["title"] = payload.title
        values["title_edited_at"] = func.now() if payload.title is not None else None
    if payload.author_note is not None:
        values["author_note"] = payload.author_note
    if values:
        await db.execute(update(NovelChapter).where(NovelChapter.id == chapter.id).values(**values))
        await db.execute(update(Novel).where(Novel.id == novel.id).values(updated_at=func.now()))
        await db.commit()
    return await _detail(db, novel.id)


# ── 작업 폴링 ───────────────────────────────────────────────────────────────
def _job_not_found() -> HTTPException:
    return _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")


@router.get("/{novel_id}/jobs/{job_id}")
async def get_novel_job(
    novel_id: uuid.UUID,
    job_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> NovelJobResponse:
    """작업 폴링. 없는 작업·남의 소설·다른 소설의 작업은 모두 404 다(남의 것이 있다는 사실도 드러내지 않는다).

    답하기 전에 이 소설의 죽은 작업을 정리한다 — 서버가 재기동되어 작업이 사라졌으면 폴링이 실패·환불을 보게 된다."""
    owner = await db.scalar(select(Novel.user_id).where(Novel.id == novel_id))
    if owner != user_id:
        raise _job_not_found()
    await expire_stale_jobs(db, novel_id=novel_id)
    await db.commit()

    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.novel_id == novel_id)
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise _job_not_found()
    return await _job_response(db, job)


# ── 장: 공통 검사 ───────────────────────────────────────────────────────────
async def _get_chapter(db: AsyncSession, novel: Novel, chapter_id: uuid.UUID) -> NovelChapter:
    chapter = await db.scalar(
        select(NovelChapter)
        .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel.id)
        .execution_options(populate_existing=True)
    )
    if chapter is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    return chapter


async def _ensure_content_allows_model(db: AsyncSession, novel: Novel) -> None:
    """모델을 부르는 라우트(경계 제안·장 생성·재생성·AI 수정)만 막는다. 작품은 소설 행에 사본으로 둔 원작 id 로
    읽어 방이 지워져도 판정한다. 원작 행이 아예 없으면 이용 제한과 같이 막는다(풀어 줄 근거가 없다)."""
    content = await db.get(Content, novel.content_id, populate_existing=True)
    if content is None:
        raise _novel_error(status.HTTP_403_FORBIDDEN, "CONTENT_RESTRICTED")
    _ensure_content_playable(content)


def _source_room_id(novel: Novel) -> uuid.UUID:
    """새 장의 원문이 있는 방. 방이 지워진 소설은 읽고 고칠 수는 있어도 새 장·재생성을 할 원문이 없다."""
    if novel.chat_room_id is None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_ROOM_GONE")
    return novel.chat_room_id


async def _require_chapter_model(db: AsyncSession, novel: Novel, model: ChatModelId) -> None:
    """장 요청이 고른 모델을 이 계정이 쓸 수 있는지 차감 전에 본다. 기본 모델은 누구나 된다. 상위 모델은 소설 상위 모델
    허용이 있어야 하고, 없으면 403 `NOVEL_MODEL_NOT_ALLOWED` 하나다(꺼짐·명단 밖·허용 행 없음을 가르지 않는다). 방에
    저장된 모델처럼 기본 모델로 바꿔 받지 않는다 — 장 요청의 모델은 사용자가 그 가격과 함께 지금 고른 값이다."""
    if model != DEFAULT_CHAT_MODEL and not await has_novel_premium_access(db, novel.user_id):
        raise _novel_error(status.HTTP_403_FORBIDDEN, "NOVEL_MODEL_NOT_ALLOWED")


def _require_protagonist_name(novel: Novel) -> None:
    """장 본문은 사용자 쪽 인물을 이름으로 부른다 — 이름이 없으면 차감하기 전에 받는다."""
    if not (novel.protagonist_name or "").strip():
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_PROTAGONIST_NAME_REQUIRED")


async def _next_segment(
    db: AsyncSession, novel: Novel, room_id: uuid.UUID, model: ChatModelId
) -> list[ChatMessage]:
    """다음 묶음이 될 수 있는 원문 — 시작 메시지부터 응답을 그 모델의 묶음 턴 상한만큼 셀 때까지. 상한이 모델마다 다른
    것은 모델마다 출력 속도가 달라 한 작업 시간 상한 안에 쓸 수 있는 원문 길이가 달라서다. 시작은 서버가 정한다(마지막
    화 끝 키보다 뒤의 첫 메시지). 묶음으로 만들 응답이 하나도 없으면 409 `NOVEL_NOTHING_NEW`."""
    last_chapter = await db.scalar(
        select(NovelChapter).where(NovelChapter.novel_id == novel.id).order_by(NovelChapter.ordinal.desc()).limit(1)
    )
    start = await next_chapter_start(db, room_id, last_chapter)
    candidates = (
        await load_candidates(db, room_id, message_key(start), chapter_max_turns(model)) if start is not None else []
    )
    if not candidates:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_NOTHING_NEW")
    return candidates


async def _start_job(
    db: AsyncSession, job: NovelJob, expected_cost: int, session_factory: "SessionFactory", llm_client: LLMClient
) -> NovelJobResponse:
    """차감하며 작업을 넣고(커밋) 백그라운드로 띄운다. 거절 판정은 모두 이 앞에서 끝낸다 — 거절된 요청은 원장에
    아무것도 남기지 않는다. 응답은 띄우기 전에 만든다: 띄운 작업이 같은 커넥션을 쓰는 테스트에서 겹치지 않게."""
    job = await create_charged_job(db, job=job, expected_cost=expected_cost, now=datetime.now(UTC))
    response = await _job_response(db, await db.get_one(NovelJob, job.id, populate_existing=True))
    enqueue = enqueue_chain_job if job.kind == "chain_generate" else enqueue_job
    await enqueue(session_factory, llm_client, job.id)
    return response


async def _expire_before_new_job(db: AsyncSession, novel: Novel) -> None:
    """새 작업 차감 직전의 지연 정리. 커밋까지 해 둔다 — 작업 생성이 거절하며 롤백해도 정리(환불)는 남고, 서버
    재기동으로 죽은 작업이 진행 중으로 남아 새 작업을 계속 409 로 막지 않는다. 묶음 없는 화도 여기서 묶음에 넣는다 —
    그대로 다음 묶음을 만들면 그 화가 나중에 받는 묶음 번호가 화 순서와 어긋나고, 다시 만들기는 묶음을 찾지 못한다."""
    await expire_stale_jobs(db, novel_id=novel.id)
    await ensure_batches(db, novel.id)
    await db.commit()


SessionFactory = async_sessionmaker[AsyncSession]


# ── 장 경계 제안 ────────────────────────────────────────────────────────────
_PROPOSAL_SCOPE = "novelize-proposal"
_HOUR_SECONDS = 3600
# 후보 턴 발췌 길이(글자)와 제안 이유 상한. 이유는 문안이 60자 이내로 쓰라고 하지만 넘쳐 와도 버리지 않고 자른다.
_EXCERPT_CHARS = 80
_REASON_MAX_CHARS = 100
_WHITESPACE = re.compile(r"\s+")


def _excerpt(message: ChatMessage, novel: Novel) -> str:
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    text = _WHITESPACE.sub(" ", names.expand(strip_media_tags(message.content))).strip()
    return text[:_EXCERPT_CHARS]


async def _check_proposal_limit(user_id: uuid.UUID) -> None:
    """무과금 호출의 남용 상한(시간당 고정 창). 면제 계정도 센다 — 과금이 없어 이 상한이 유일한 제동이다. Redis 가
    실패하면 채팅·이미지 상한과 같이 통과시킨다."""
    try:
        retry_after = await check_rate_limit(
            _PROPOSAL_SCOPE, str(user_id), settings.novelize_proposal_hourly_limit, window_seconds=_HOUR_SECONDS
        )
    except RedisError:
        logger.warning("소설 장 경계 제안 상한 검사 실패 — 통과시킨다", exc_info=True)
        return
    if retry_after > 0:
        raise _too_many_requests(user_id, "novelize", retry_after)


@router.post("/{novel_id}/chapter-proposal", dependencies=[Depends(require_legal_consent)])
async def propose_novel_chapter(
    payload: NovelChapterProposalRequest | None = None,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelChapterProposalResponse:
    """다음 묶음의 후보 턴 목록과 모델이 고른 끝 턴(무과금, 동기). 본문이 없으면 기본 모델이다(이 본문을 모르는 옛 화면).

    후보는 서버가 정한 시작부터 응답을 요청한 모델의 턴 상한만큼 센 턴들이고, 후보마다 그 모델로 거기까지 만들 때의 화
    수·금액이 붙는다 — 화면은 모델을 먼저 고르고 그 모델로 이 제안을 받는다. 화면의 방 메시지 캐시는 최근 일부뿐이라 묶음
    시작이 그보다 앞일 수 있어 후보를 서버가 준다. 모델 제안은 그 후보 안에서 고르고, 실패해도 200 에 `suggestion: null`
    이다: 경계는 사용자가 고르는 것이라 제안 실패가 생성을 막을 이유가 없다. 모델을 부르기 전에 커밋해 커넥션을 돌려준다
    (모델 호출 동안 쥐지 않는다).

    모델을 바꿔 다시 받는 호출도 시간당 제안 상한에 센다 — 호출마다 실제로 경계 제안 모델을 부른다. 상위 모델은 허용이
    있어야 하고(없으면 403 `NOVEL_MODEL_NOT_ALLOWED`), 그 판정이 상한 검사보다 앞이라 거절된 요청은 상한을 깎지 않는다."""
    model = payload.model if payload is not None else DEFAULT_CHAT_MODEL
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    await _require_chapter_model(db, novel, model)
    candidates = await _next_segment(db, novel, room_id, model)
    turns = group_turns(candidates)
    counts = episode_counts(turns, novel, model)
    source = await load_novel_prompt_source(db, novel)
    await _check_proposal_limit(novel.user_id)
    chapter_models, _ = await _chapter_models(db, novel.user_id)
    await db.commit()

    suggestion: NovelChapterSuggestion | None = None
    suggested = await suggest_end_turn(
        llm_client, novel=novel, turns=turns, sections=source.sections, chat_set=source.chat_set, room_id=room_id
    )
    if suggested is not None:
        end_turn, reason = suggested
        suggestion = NovelChapterSuggestion(
            end_message_id=turns[end_turn - 1].assistant.id, reason=reason.strip()[:_REASON_MAX_CHARS]
        )

    return NovelChapterProposalResponse(
        start_message_id=candidates[0].id,
        candidates=[
            NovelChapterCandidate(
                message_id=turn.assistant.id,
                ordinal=n,
                created_at=turn.assistant.created_at,
                excerpt=_excerpt(turn.assistant, novel),
                episode_count=count,
                cost=job_price("chapter_generate", model, count),
            )
            for n, (turn, count) in enumerate(zip(turns, counts, strict=True), start=1)
        ],
        suggestion=suggestion,
        cost=job_price("chapter_generate"),
        chapter_models=chapter_models,
    )


# ── 묶음 생성·다시 만들기 ───────────────────────────────────────────────────
@router.post(
    "/{novel_id}/chapters", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_legal_consent)]
)
async def create_novel_chapter(
    payload: NovelChapterCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """다음 묶음을 만드는 작업(과금, 202). 시작은 서버가 정하고, 끝(`endMessageId`)은 경계 제안의 후보 턴 중 하나여야
    한다 — 다음 묶음 시작부터 요청 모델의 턴 상한 안의 AI 응답이 아니면 422 `NOVEL_CHAPTER_END_INVALID`.

    `model` 은 이 묶음을 쓸 모델이다(기본 Gemini). 작업에 적혀 실행이 그대로 쓴다. 화 수는 서버가 그 구간의 원문 분량과
    모델로 다시 세어 작업에 싣고(경계 제안의 후보 화 수와 같은 계산), 금액은 그 화 수 × 모델의 화 단가다 — 확인한 금액과
    다르면 409 `NOVELIZE_PRICE_CHANGED` + `currentCost`.

    순서: 작품 상태(403)·방(409)·주인공 이름(422)·모델 허용(403) → 죽은 작업 정리·묶음 보정·커밋 → 구간 검사(409·422) →
    차감·작업 생성(금액 409·진행 중 409·하루 상한 429·잔액 429) → 띄우기. 차감 앞의 거절은 원장에 아무것도 남기지 않는다."""
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    _require_protagonist_name(novel)
    await _require_chapter_model(db, novel, payload.model)
    await _expire_before_new_job(db, novel)

    candidates = await _next_segment(db, novel, room_id, payload.model)
    turns = group_turns(candidates)
    end_index = next((i for i, turn in enumerate(turns) if turn.assistant.id == payload.end_message_id), None)
    if end_index is None:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_CHAPTER_END_INVALID")
    end = turns[end_index].assistant
    start = candidates[0]
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chapter_generate",
        model=payload.model,
        start_message_id=start.id,
        start_message_created_at=start.created_at,
        end_message_id=end.id,
        end_message_created_at=end.created_at,
        episode_count_target=episode_counts(turns[: end_index + 1], novel, payload.model)[-1],
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


# ── 남은 대화 한 번에(연쇄 생성) ────────────────────────────────────────────
async def _remaining_turns(db: AsyncSession, novel: Novel, room_id: uuid.UUID) -> int:
    """다음 묶음 시작부터 방 끝까지의 턴(AI 응답) 수. 끝에 응답 없이 남은 사용자 메시지는 묶음이 될 수 없어 세지 않는다."""
    last_chapter = await db.scalar(
        select(NovelChapter).where(NovelChapter.novel_id == novel.id).order_by(NovelChapter.ordinal.desc()).limit(1)
    )
    start = await next_chapter_start(db, room_id, last_chapter)
    if start is None:
        return 0
    turns = await db.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.chat_room_id == room_id,
            ChatMessage.role == ChatMessageRole.ASSISTANT,
            tuple_(ChatMessage.created_at, ChatMessage.id) >= message_key(start),
        )
    )
    return int(turns or 0)


def _chain_batch_count(remaining_turns: int, model: ChatModelId) -> int:
    """남은 턴을 `model` 의 묶음 턴 상한으로 나눈 묶음 수(올림), 한 번의 상한까지. 실제 경계는 묶음마다 자동 제안이 그
    상한 안에서 고르므로 묶음이 더 필요할 수 있다 — 그때 남은 대화는 다음에 다시 누른다."""
    needed = -(-remaining_turns // chapter_max_turns(model))
    return min(needed, settings.novelize_chain_max_batches)


@router.get("/{novel_id}/chain-estimate")
async def estimate_novel_chain(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChainEstimateResponse:
    """"남은 대화 한 번에"의 모델별 견적. 이 계정이 고를 수 있는 모델마다 묶음 수·최대 화 수·금액이다. 작품 상태(403)·방
    (409 `NOVEL_ROOM_GONE`)을 생성과 같이 보고, 만들 턴이 없으면 409 `NOVEL_NOTHING_NEW` 다."""
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    remaining = await _remaining_turns(db, novel, room_id)
    if remaining == 0:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_NOTHING_NEW")
    chapter_models, _ = await _chapter_models(db, novel.user_id)
    options: list[NovelChainEstimate] = []
    for option in chapter_models:
        batches = _chain_batch_count(remaining, option.id)
        options.append(
            NovelChainEstimate(
                model=option.id,
                name=option.name,
                batch_count=batches,
                max_episode_count=batches * k_max(option.id),
                cost=chain_price(option.id, batches),
            )
        )
    return NovelChainEstimateResponse(options=options)


@router.post("/{novel_id}/chain", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_legal_consent)])
async def create_novel_chain(
    payload: NovelChainCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """"남은 대화 한 번에"(과금, 202 부모 작업). 모델은 연쇄 전체에 하나다. 묶음 수는 남은 대화를 그 모델의 턴 상한으로
    나눈 수를 `maxBatches` 와 한 번의 상한으로 자른 값이고, 금액은 묶음 수 × 그 모델의 화 수 상한 × 화 단가다(견적의
    `cost`). 확인한 금액과 다르면 409 `NOVELIZE_PRICE_CHANGED` + `currentCost`. 묶음마다 자동 경계로 하나씩 만들고, 끝나면
    쓰지 않은 몫을 돌려준다. 폴링은 이 부모 작업으로 하고 진행은 `completedBatches`/`plannedBatches` 다.

    순서: 작품 상태(403)·방(409)·주인공 이름(422)·모델 허용(403) → 죽은 작업 정리·묶음 보정·커밋 → 남은 턴(409
    `NOVEL_NOTHING_NEW`) → 차감·작업 생성(금액 409·진행 중 409·잔액 429) → 띄우기. 같은 시작 메시지 하루 상한은 연쇄
    부모에 걸지 않는다 — 부모는 한 구간이 아니라 남은 대화 전체를 맡는다."""
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    _require_protagonist_name(novel)
    await _require_chapter_model(db, novel, payload.model)
    await _expire_before_new_job(db, novel)

    remaining = await _remaining_turns(db, novel, room_id)
    if remaining == 0:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_NOTHING_NEW")
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chain_generate",
        model=payload.model,
        planned_batches=min(payload.max_batches, _chain_batch_count(remaining, payload.model)),
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


async def _get_batch(db: AsyncSession, novel: Novel, batch_id: uuid.UUID) -> NovelBatch:
    batch = await db.scalar(
        select(NovelBatch)
        .where(NovelBatch.id == batch_id, NovelBatch.novel_id == novel.id)
        .execution_options(populate_existing=True)
    )
    if batch is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_BATCH_NOT_FOUND")
    return batch


async def _chapter_batch(db: AsyncSession, novel: Novel, chapter_id: uuid.UUID) -> NovelBatch:
    """화 하나를 가리키는 옛 라우트가 다룰 묶음 — 그 화가 든 묶음이다. 옛 판 코드가 넣어 묶음이 없는 화면 먼저 묶음에
    넣는다(커밋까지 — 뒤의 거절이 롤백해도 보정은 남는다)."""
    chapter = await _get_chapter(db, novel, chapter_id)
    if chapter.batch_id is None:
        # 다시 만들기 경로에서만 온다. 삭제 경로는 사용자 잠금을 쥔 채 보정을 먼저 돌린 뒤 부르므로 여기서 묶음 없는 화를
        # 보지 않는다 — 그래서 이 커밋이 삭제의 사용자 잠금을 중간에 풀지 않는다.
        await ensure_batches(db, novel.id)
        await db.commit()
        chapter = await _get_chapter(db, novel, chapter_id)
    assert chapter.batch_id is not None  # 보정이 묶음 없는 화를 남기지 않는다
    return await _get_batch(db, novel, chapter.batch_id)


async def _regenerate_batch(
    db: AsyncSession,
    novel: Novel,
    batch: NovelBatch,
    *,
    model: ChatModelId,
    expected_cost: int,
    chapter_id: uuid.UUID | None,
    session_factory: SessionFactory,
    llm_client: LLMClient,
) -> NovelJobResponse:
    """묶음 하나를 같은 원문 구간·같은 화 수로 다시 만드는 작업을 넣는다. `chapter_id` 는 화 하나를 골라 들어온 옛
    라우트의 그 화다 — 작업이 끝나면 화면이 그 화로 이동한다.

    순서: 작품 상태(403)·방(409)·주인공 이름(422)·모델 허용(403) → 죽은 작업 정리·묶음 보정·커밋 → 원문 변경(409) →
    차감·작업 생성(모델 적격성 409 → 금액 409 → 진행 중·하루 상한·잔액). 적격성과 금액은 묶음의 화 수를 세야 해서
    사용자 잠금 아래에서 본다(`billing.create_charged_job`)."""
    await _ensure_content_allows_model(db, novel)
    room_id = _source_room_id(novel)
    _require_protagonist_name(novel)
    await _require_chapter_model(db, novel, model)
    await _expire_before_new_job(db, novel)

    segment = await load_segment(
        db,
        room_id,
        (batch.start_message_created_at, batch.start_message_id),
        (batch.end_message_created_at, batch.end_message_id),
    )
    if (
        not segment
        or segment[0].id != batch.start_message_id
        or segment[-1].id != batch.end_message_id
        or segment_hash(segment) != batch.source_hash
    ):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_CHANGED")
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="chapter_regenerate",
        model=model,
        batch_id=batch.id,
        chapter_id=chapter_id,
        start_message_id=batch.start_message_id,
        start_message_created_at=batch.start_message_created_at,
        end_message_id=batch.end_message_id,
        end_message_created_at=batch.end_message_created_at,
    )
    return await _start_job(db, job, expected_cost, session_factory, llm_client)


@router.post(
    "/{novel_id}/batches/{batch_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def regenerate_novel_batch(
    batch_id: uuid.UUID,
    payload: NovelBatchRegenerateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """묶음 하나를 같은 원문 구간으로 다시 만드는 작업(과금, 202). 마지막 묶음이 아니어도 된다. 화 수는 지금 그대로다 —
    결과는 화마다 새 개정으로 쌓이고(화 제목·요약·등장 인물도 바뀐다) 읽은 위치·작가의 말·개정 이력은 남는다. 결과 화 수가
    다르면 작업이 실패하고 전액 돌려준다.

    금액은 묶음의 화 수 × 고른 모델의 화 단가(상세의 묶음 `regenerateOptions`)다. 고른 모델이 그 화 수나 묶음의 턴 수를
    담지 못하면 차감 전에 409 `NOVEL_MODEL_INELIGIBLE` + `reason`. 원문이 묶음을 만든 때와 다르면(메시지 편집·응답
    재생성·삭제) 차감 전에 409 `NOVEL_SOURCE_CHANGED`. 없는 묶음은 404 `NOVEL_BATCH_NOT_FOUND`."""
    batch = await _get_batch(db, novel, batch_id)
    return await _regenerate_batch(
        db,
        novel,
        batch,
        model=payload.model,
        expected_cost=payload.expected_cost,
        chapter_id=None,
        session_factory=session_factory,
        llm_client=llm_client,
    )


@router.post(
    "/{novel_id}/chapters/{chapter_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def regenerate_novel_chapter(
    chapter_id: uuid.UUID,
    payload: NovelChapterRegenerateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """화 하나를 골라 들어오는 옛 다시 만들기 — 그 화가 든 묶음 전체를 다시 만든다(묶음 다시 만들기와 같은 검사·금액).
    작업 응답의 `chapterId` 는 고른 화이고, 끝나면 그 화의 새 개정이 `revisionId` 다."""
    batch = await _chapter_batch(db, novel, chapter_id)
    return await _regenerate_batch(
        db,
        novel,
        batch,
        model=payload.model,
        expected_cost=payload.expected_cost,
        chapter_id=chapter_id,
        session_factory=session_factory,
        llm_client=llm_client,
    )


# ── 마지막 묶음 삭제 ────────────────────────────────────────────────────────
async def _delete_last_batch(db: AsyncSession, novel: Novel, batch: NovelBatch, *, not_last_code: str) -> None:
    """`batch` 가 이 소설의 마지막 묶음이면 그 화들과 함께 지우고 커밋한다. 호출자가 사용자 행을 잠근 뒤 부른다."""
    active = await db.scalar(
        select(NovelJob.id).where(NovelJob.novel_id == novel.id, NovelJob.status.in_(ACTIVE_JOB_STATUSES)).limit(1)
    )
    if active is not None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_IN_PROGRESS")
    last_ordinal = await db.scalar(select(func.max(NovelBatch.ordinal)).where(NovelBatch.novel_id == novel.id))
    if batch.ordinal != last_ordinal:
        raise _novel_error(status.HTTP_409_CONFLICT, not_last_code)
    await delete_batch(db, novel_id=novel.id, batch_id=batch.id)
    await db.execute(update(Novel).where(Novel.id == novel.id).values(updated_at=func.now()))
    await db.commit()


@router.delete("/{novel_id}/batches/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_last_novel_batch(
    batch_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """마지막 묶음만 지운다(무과금) — 그 묶음의 화 전부와 개정·등장 인물·읽은 위치가 함께 지워지고, 다음 묶음 시작이 그
    묶음 시작으로 돌아간다. 경계를 잘못 골랐을 때 고치는 길이다. 인물 카드는 남고, 스냅샷은 남되 지운 화의 항목만
    `{chapterId, deleted: true}` 로 줄어든다. 마지막이 아니면 409 `NOVEL_BATCH_NOT_LAST`, 소설에 진행 중 작업이 있으면
    409 `NOVEL_JOB_IN_PROGRESS`(끝난 뒤 다시), 없는 묶음은 404 `NOVEL_BATCH_NOT_FOUND`.

    그 화들을 가리키던 작업 행은 지우지 않고 참조와 AI 수정 지시문·결과 본문만 비운다(`deletion.delete_batch`).

    잠금: 사용자 행(작업 생성과 줄 세우기 — 진행 중 확인과 삭제 사이에 새 작업이 끼지 않게) → 작업 행 → 화 행. 묶음 보정도
    이 잠금 아래에서 먼저 한다 — 빈 묶음이 남아 있으면 그것이 "마지막"으로 보여 실제 마지막 묶음을 지울 수 없다."""
    await _lock_user(db, novel.user_id)
    await ensure_batches(db, novel.id)
    batch = await _get_batch(db, novel, batch_id)
    await _delete_last_batch(db, novel, batch, not_last_code="NOVEL_BATCH_NOT_LAST")


@router.delete("/{novel_id}/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_last_novel_chapter(
    chapter_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """화 하나를 골라 들어오는 옛 마지막 장 삭제 — 그 화가 마지막 묶음에 들어 있으면 그 묶음 전체를 지운다(묶음 삭제와
    같은 규칙). 마지막 묶음의 화가 아니면 409 `NOVEL_CHAPTER_NOT_LAST`, 진행 중 작업이 있으면 409
    `NOVEL_JOB_IN_PROGRESS`."""
    await _lock_user(db, novel.user_id)
    # 보정을 먼저 돌려 둔다 — 그 뒤라 `_chapter_batch` 는 묶음 없는 화를 보지 않고, 그 안의 보정·커밋 갈래(잠금을 푼다)를
    # 타지 않는다.
    await ensure_batches(db, novel.id)
    batch = await _chapter_batch(db, novel, chapter_id)
    await _delete_last_batch(db, novel, batch, not_last_code="NOVEL_CHAPTER_NOT_LAST")


# ── 장 읽기·개정 이력 ───────────────────────────────────────────────────────
def _revision_summary(revision: NovelChapterRevision) -> NovelRevisionSummary:
    return NovelRevisionSummary(
        id=revision.id,
        revision_no=revision.revision_no,
        source=revision.source,
        reverted_from_revision_id=revision.reverted_from_revision_id,
        created_at=revision.created_at,
    )


def _revision_response(revision: NovelChapterRevision) -> NovelRevisionResponse:
    return NovelRevisionResponse(
        **_revision_summary(revision).model_dump(), body=revision.body, paragraphs=split_paragraphs(revision.body)
    )


async def _chapter_response(db: AsyncSession, chapter: NovelChapter) -> NovelChapterResponse:
    revision = await current_revision(db, chapter.id)
    assert revision is not None  # 장 행과 첫 개정은 한 트랜잭션에서 함께 들어간다
    return NovelChapterResponse(
        id=chapter.id,
        novel_id=chapter.novel_id,
        ordinal=chapter.ordinal,
        assistant_message_count=chapter.assistant_message_count,
        revision=_revision_response(revision),
    )


async def _get_revision(db: AsyncSession, chapter: NovelChapter, revision_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        select(NovelChapterRevision).where(
            NovelChapterRevision.id == revision_id, NovelChapterRevision.chapter_id == chapter.id
        )
    )
    if revision is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_REVISION_NOT_FOUND")
    return revision


@router.get("/{novel_id}/chapters/{chapter_id}")
async def get_novel_chapter(
    chapter_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """장의 현재 개정 본문과 그 문단 배열. 문단 범위(AI 수정)는 이 배열의 인덱스다 — 화면이 본문을 다시 나누면 빈 줄
    해석 차이로 범위가 어긋난다."""
    return await _chapter_response(db, await _get_chapter(db, novel, chapter_id))


@router.get("/{novel_id}/chapters/{chapter_id}/revisions")
async def list_novel_chapter_revisions(
    chapter_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelRevisionListResponse:
    """장의 개정 이력(최신 먼저). 본문은 싣지 않는다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    revisions = await db.scalars(
        select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter.id)
        .order_by(NovelChapterRevision.revision_no.desc())
    )
    return NovelRevisionListResponse(items=[_revision_summary(revision) for revision in revisions.all()])


@router.get("/{novel_id}/chapters/{chapter_id}/revisions/{revision_id}")
async def get_novel_chapter_revision(
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelRevisionResponse:
    chapter = await _get_chapter(db, novel, chapter_id)
    return _revision_response(await _get_revision(db, chapter, revision_id))


# ── 직접 수정·되돌리기·적용 ─────────────────────────────────────────────────
async def _lock_current_revision_for_edit(
    db: AsyncSession, chapter_id: uuid.UUID, base_revision_id: uuid.UUID
) -> NovelChapterRevision:
    """개정을 쌓는 세 경로(직접 수정·되돌리기·AI 수정 적용)의 공통 앞부분. 장 행을 먼저 잠그고(`FOR NO KEY UPDATE`)
    그 뒤에 현재 개정을 읽는다 — 잠그기 전에 읽으면 그사이 커밋된 새 개정을 못 보고 옛 개정 위에 덮어쓴다. 현재
    개정이 요청의 기준 개정이 아니면 409 `NOVEL_REVISION_CONFLICT`(다른 탭이 먼저 고쳤다). 장이 그사이 지워졌으면
    404. 재생성 결과 저장도 같은 잠금으로 줄을 서서 같은 번호를 두 번 쓰지 않는다."""
    locked = await db.scalar(select(NovelChapter.id).where(NovelChapter.id == chapter_id).with_for_update(key_share=True))
    if locked is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    current = await current_revision(db, chapter_id)
    if current is None or current.id != base_revision_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_REVISION_CONFLICT")
    return current


async def _stack_revision(
    db: AsyncSession, novel: Novel, current: NovelChapterRevision, revision: NovelChapterRevision
) -> NovelChapterRevision:
    """잠근 현재 개정 다음 번호로 `revision` 을 넣고 소설 수정 시각을 민다(커밋은 호출자)."""
    revision.chapter_id = current.chapter_id
    revision.revision_no = current.revision_no + 1
    db.add(revision)
    await db.flush()
    await db.execute(update(Novel).where(Novel.id == novel.id).values(updated_at=func.now()))
    return revision


async def _erase_stale_previews(db: AsyncSession, chapter_id: uuid.UUID) -> None:
    """새 개정을 커밋한 뒤 그 장의 낡은 AI 수정 미리보기를 비운다. 개정과 같은 트랜잭션에 두지 않는 이유는
    `erase_stale_ai_edit_previews` 에 있다(장 잠금을 쥔 채 작업 행을 고치면 적용과 교착한다).

    실패(교착 오류·잠금 대기 초과 등)는 되돌리고 남긴 뒤 삼킨다. 새 개정은 이미 커밋됐는데 여기서 500 을 내면 화면은
    저장 실패로 보고 같은 기준 개정으로 다시 보내 409 를 받는다 — 성공한 수정이 "다른 탭이 먼저 고쳤다"로 보인다.
    남은 낡은 미리보기는 상세 목록에서 이미 빠지고 적용해도 409 이며, 그 장의 다음 개정 때 비우기가 다시 지운다.

    되돌리기는 세션 전체가 아니라 SAVEPOINT 까지다. 세션을 통째로 롤백하면 이미 읽어 둔 소설·장 객체가 만료돼, 뒤이어
    응답을 만들 때 그 속성을 읽는 것이 예상 밖 DB 조회가 되어 실패한다. 커넥션이 아예 죽은 경우에는 뒤의 커밋도 응답
    조회도 어차피 실패하므로 그때는 500 이 맞다."""
    try:
        async with db.begin_nested():
            await erase_stale_ai_edit_previews(db, chapter_id)
    except Exception as exc:
        logger.warning("소설 장 %s 의 낡은 AI 수정 미리보기를 비우지 못했다: %s", chapter_id, type(exc).__name__)
        capture_dependency_failure(exc, dependency="db")
    await db.commit()


@router.post(
    "/{novel_id}/chapters/{chapter_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_novel_chapter_revision(
    chapter_id: uuid.UUID,
    payload: NovelRevisionCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """직접 수정 — 장 전체 본문을 새 개정으로 쌓는다(무과금). 화면이 고른 문단을 본문 안에서 바꿔 보내므로 서버는
    문단 범위를 모른다. 본문은 문단을 빈 줄 하나로 다시 이어 저장한다(문단 배열과 같은 나누기). 이용 제한 작품이나
    방이 지워진 소설도 고칠 수 있다(모델을 부르지 않는다)."""
    chapter = await _get_chapter(db, novel, chapter_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    await _stack_revision(
        db,
        novel,
        current,
        NovelChapterRevision(body="\n\n".join(split_paragraphs(payload.body)), source="manual_edit"),
    )
    await db.commit()
    await _erase_stale_previews(db, chapter.id)
    return await _chapter_response(db, chapter)


@router.post(
    "/{novel_id}/chapters/{chapter_id}/revisions/{revision_id}/restore",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_legal_consent)],
)
async def restore_novel_chapter_revision(
    chapter_id: uuid.UUID,
    revision_id: uuid.UUID,
    payload: NovelRevisionRestoreRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """옛 개정으로 되돌린다 — 옛 본문을 복제한 새 개정을 쌓는다(이력은 지우지 않는다)."""
    chapter = await _get_chapter(db, novel, chapter_id)
    source = await _get_revision(db, chapter, revision_id)
    current = await _lock_current_revision_for_edit(db, chapter.id, payload.base_revision_id)
    await _stack_revision(
        db,
        novel,
        current,
        NovelChapterRevision(body=source.body, source="revert", reverted_from_revision_id=source.id),
    )
    await db.commit()
    await _erase_stale_previews(db, chapter.id)
    return await _chapter_response(db, chapter)


@router.post(
    "/{novel_id}/chapters/{chapter_id}/ai-edits",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_legal_consent)],
)
async def create_novel_ai_edit(
    chapter_id: uuid.UUID,
    payload: NovelAiEditRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
    session_factory: SessionFactory = Depends(get_session_factory),
    llm_client: LLMClient = Depends(get_llm_client),
) -> NovelJobResponse:
    """고른 문단 범위(0부터, 양 끝 포함 — 장 조회의 `paragraphs` 인덱스)를 지시대로 고치는 작업(과금, 202). 결과는
    개정이 아니라 작업의 미리보기 본문(`aiEdit.resultText`)이고, 적용해야 새 개정이 된다. 버려도 환불은 없다.

    방이 지워진 소설도 고칠 수 있다(원문 대화가 필요 없다). 기준 개정이 현재 개정이 아니면 409, 범위가 문단 밖이면
    422 — 둘 다 차감 전이다."""
    chapter = await _get_chapter(db, novel, chapter_id)
    await _ensure_content_allows_model(db, novel)
    await _expire_before_new_job(db, novel)
    current = await current_revision(db, chapter.id)
    if current is None or current.id != payload.base_revision_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_REVISION_CONFLICT")
    if not payload.paragraph_start <= payload.paragraph_end < len(split_paragraphs(current.body)):
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_PARAGRAPH_RANGE_INVALID")
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=current.id,
        paragraph_start=payload.paragraph_start,
        paragraph_end=payload.paragraph_end,
        instruction=payload.instruction,
    )
    return await _start_job(db, job, payload.expected_cost, session_factory, llm_client)


@router.post(
    "/{novel_id}/jobs/{job_id}/apply", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def apply_novel_ai_edit(
    job_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelChapterResponse:
    """끝난 AI 수정의 미리보기를 새 개정으로 쌓는다(무과금). 수정을 맡긴 뒤 장이 바뀌었으면(기준 개정이 현재가
    아니면) 409 `NOVEL_REVISION_CONFLICT`. 적용할 수 없는 작업(AI 수정이 아님·아직 안 끝남·실패·이미 적용·버림·장이
    지워짐)은 409 `NOVEL_JOB_NOT_APPLICABLE`. 적용한 개정은 작업의 결과 개정(`revisionId`)이 된다. 적용한 작업의
    지시문·결과 본문은 비운다(결과는 이제 개정에 있다). 새 개정 때문에 낡은 같은 장의 다른 미리보기도 비운다.

    결과 본문이 있는지는 기준 개정 검사 **뒤에** 본다 — 장이 바뀌어 낡은 미리보기는 본문이 비워져 있지만, 사용자에게
    알릴 사유는 "장이 바뀌었다"(409 `NOVEL_REVISION_CONFLICT`)다.

    잠금은 작업 행 → 장 행이다(소설·마지막 장 삭제와 같은 순서). 같은 작업을 두 번 적용하려는 요청은 작업 행에서
    줄을 서고, 뒤 요청은 결과 개정이 채워진 것을 본다."""
    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.novel_id == novel.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")
    if (
        job.kind != "ai_edit"
        or job.status != "succeeded"
        or job.result_revision_id is not None
        or job.dismissed_at is not None
        or job.chapter_id is None
        or job.base_revision_id is None
    ):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_NOT_APPLICABLE")
    current = await _lock_current_revision_for_edit(db, job.chapter_id, job.base_revision_id)
    if job.result_text is None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_NOT_APPLICABLE")
    revision = await _stack_revision(
        db, novel, current, NovelChapterRevision(body=job.result_text, source="ai_edit")
    )
    await db.execute(
        update(NovelJob)
        .where(NovelJob.id == job.id)
        .values(result_revision_id=revision.id, instruction=None, result_text=None)
    )
    await db.commit()
    await _erase_stale_previews(db, current.chapter_id)
    return await _chapter_response(db, await _get_chapter(db, novel, current.chapter_id))


@router.post(
    "/{novel_id}/jobs/{job_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def dismiss_novel_ai_edit(
    job_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """끝난 AI 수정의 미리보기를 적용하지 않고 버린다(환불 없음). 버린 수정은 상세의 미적용 목록에서 빠지고 적용도
    409 가 된다. 지시문과 결과 본문은 비운다 — 버린 결과는 더 쓸 데가 없고, 행은 하루 상한 집계용으로 남는다.
    버릴 수 없는 작업(AI 수정이 아님·아직 안 끝남·실패·이미 적용·이미 버림)은 409 `NOVEL_JOB_NOT_APPLICABLE`.

    적용과 같은 작업 행을 잠근다 — 같은 수정의 적용과 버리기가 겹치면 뒤 요청이 앞 요청의 결과를 보고 409 다."""
    job = await db.scalar(
        select(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.novel_id == novel.id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_JOB_NOT_FOUND")
    if (
        job.kind != "ai_edit"
        or job.status != "succeeded"
        or job.result_revision_id is not None
        or job.dismissed_at is not None
    ):
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_NOT_APPLICABLE")
    await db.execute(
        update(NovelJob)
        .where(NovelJob.id == job.id)
        .values(dismissed_at=func.now(), instruction=None, result_text=None)
    )
    await db.commit()


# ── 인물 카드 ───────────────────────────────────────────────────────────────
async def _character_list(db: AsyncSession, novel_id: uuid.UUID) -> NovelCharacterListResponse:
    links = await db.execute(
        select(NovelChapterCharacter.character_id, NovelChapterCharacter.chapter_id)
        .join(NovelChapter, NovelChapter.id == NovelChapterCharacter.chapter_id)
        .where(NovelChapter.novel_id == novel_id)
        .order_by(NovelChapter.ordinal)
    )
    chapters_by_card: dict[uuid.UUID, list[uuid.UUID]] = {}
    for character_id, chapter_id in links.tuples():
        chapters_by_card.setdefault(character_id, []).append(chapter_id)
    return NovelCharacterListResponse(
        items=[
            NovelCharacterResponse(
                id=card.id,
                name=card.name,
                aliases=list(card.aliases),
                memo=card.memo,
                chapter_ids=chapters_by_card.get(card.id, []),
                created_at=card.created_at,
                updated_at=card.updated_at,
            )
            for card in await load_cards(db, novel_id)
        ]
    )


async def _get_character(db: AsyncSession, novel: Novel, character_id: uuid.UUID) -> NovelCharacter:
    card = await db.scalar(
        select(NovelCharacter)
        .where(NovelCharacter.id == character_id, NovelCharacter.novel_id == novel.id)
        .execution_options(populate_existing=True)
    )
    if card is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_CHARACTER_NOT_FOUND")
    return card


def _name_taken(exc: CharacterNameTakenError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"code": "NOVEL_CHARACTER_NAME_TAKEN", "name": exc.name}
    )


@router.get("/{novel_id}/characters")
async def list_novel_characters(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelCharacterListResponse:
    """인물 카드(만든 순서)와 카드마다 나온 화."""
    return await _character_list(db, novel.id)


@router.put("/{novel_id}/characters", dependencies=[Depends(require_legal_consent)])
async def add_novel_character(
    payload: NovelCharacterAddRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelCharacterListResponse:
    """생성 출력이 아직 내지 않은 인물의 카드를 직접 만든다(무과금). 같은 이름의 카드가 있으면 아무것도 바꾸지 않으므로
    다시 보내도 결과가 같다. 다른 카드의 별칭이면 409 `NOVEL_CHARACTER_NAME_TAKEN` + `name`. 카드를 단독으로 지우는
    길은 없다(합치기만) — 메모가 다음 묶음 입력에 실리는 카드를 실수로 잃지 않게.

    인물 카드를 고치는 모든 경로처럼 사용자 행을 먼저 잠근다 — 생성 결과 저장이 같은 잠금 아래에서 이름을 카드에 붙이므로,
    잠그지 않으면 둘이 같은 이름의 카드를 하나씩 만든다(`characters.py` 머리)."""
    await _lock_user(db, novel.user_id)
    try:
        await add_character(db, novel.id, payload.name)
    except CharacterNameTakenError as exc:
        raise _name_taken(exc) from exc
    await db.commit()
    return await _character_list(db, novel.id)


@router.patch("/{novel_id}/characters/{character_id}", dependencies=[Depends(require_legal_consent)])
async def update_novel_character(
    character_id: uuid.UUID,
    payload: NovelCharacterUpdateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelCharacterListResponse:
    """카드 이름·별칭·메모를 바꾼다(보낸 칸만, 무과금). 메모는 다음 묶음 생성 입력에 실린다(메모가 빈 인물은 빠진다).
    이름이나 별칭이 다른 카드의 이름·별칭과 겹치면 409 `NOVEL_CHARACTER_NAME_TAKEN` + `name`(겹친 값). 없는 카드는 404
    `NOVEL_CHARACTER_NOT_FOUND`. 잠금은 추가와 같다."""
    await _lock_user(db, novel.user_id)
    card = await _get_character(db, novel, character_id)
    try:
        await update_character(db, card, name=payload.name, aliases=payload.aliases, memo=payload.memo)
    except CharacterNameTakenError as exc:
        raise _name_taken(exc) from exc
    await db.commit()
    return await _character_list(db, novel.id)


@router.post("/{novel_id}/characters/{character_id}/merge", dependencies=[Depends(require_legal_consent)])
async def merge_novel_character(
    character_id: uuid.UUID,
    payload: NovelCharacterMergeRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelCharacterListResponse:
    """같은 인물의 이름 표기가 갈려 생긴 카드를 합친다(무과금). 경로의 카드가 `intoCharacterId` 카드로 흡수된다 — 이름·별칭은
    남는 카드의 별칭이 되고(그 뒤 생성 출력이 그 이름을 내면 남는 카드에 붙는다), 메모는 남는 카드 메모 뒤에 `[이름] 메모`
    로 붙고, 나온 화가 옮겨진 뒤 경로 카드는 지워진다. 편집 보드에 저장된 그 카드의 자리는 다음 배치 조회부터 빠진다.
    두 카드가 같으면 422 `NOVEL_CHARACTER_MERGE_SELF`, 어느 쪽이든 없으면 404 `NOVEL_CHARACTER_NOT_FOUND`.

    사용자 행을 먼저 잠근다. 생성 결과 저장은 같은 잠금을 쥔 채 카드 목록을 읽고 이름을 붙이므로, 합치기가 잠그지 않으면
    저장이 합치기 전 목록을 읽고 흡수될 카드에 연결을 넣는다(합치기가 그 카드를 지우는 것과 엇갈린다)."""
    await _lock_user(db, novel.user_id)
    if character_id == payload.into_character_id:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_CHARACTER_MERGE_SELF")
    absorbed = await _get_character(db, novel, character_id)
    into = await _get_character(db, novel, payload.into_character_id)
    await merge_characters(db, absorbed, into)
    await db.commit()
    return await _character_list(db, novel.id)


# ── 편집 보드 배치 ──────────────────────────────────────────────────────────
@router.get("/{novel_id}/board-layout")
async def get_novel_board_layout(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelBoardLayoutResponse:
    """저장한 편집 보드 배치. 지금 없는 화·인물의 자리는 빼고 돌려준다 — 묶음 삭제·인물 합치기 뒤에도 저장값을 고치지
    않으므로, 화면이 받은 키만 다음 저장에 다시 보내면 저절로 정리된다. 저장한 적이 없으면 `layout` 이 null 이다."""
    if not novel.board_layout:
        return NovelBoardLayoutResponse(layout=None)
    layout = NovelBoardLayout.model_validate(novel.board_layout)
    chapter_ids = {
        str(chapter_id)
        for chapter_id in (await db.scalars(select(NovelChapter.id).where(NovelChapter.novel_id == novel.id))).all()
    }
    card_ids = {str(card.id) for card in await load_cards(db, novel.id)}
    alive = {"episode": chapter_ids, "character": card_ids}
    positions = {
        key: position
        for key, position in layout.positions.items()
        if key == "notes" or key.partition(":")[2] in alive[key.partition(":")[0]]
    }
    return NovelBoardLayoutResponse(layout=layout.model_copy(update={"positions": positions}))


@router.put(
    "/{novel_id}/board-layout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def save_novel_board_layout(
    payload: NovelBoardLayout,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """편집 보드 배치를 통째로 저장한다. 끌기·화면 이동이 멈출 때마다 오므로 소설 수정 시각은 밀지 않는다(목록이 최근
    수정 순이다). 직렬화한 크기가 `limits.boardLayoutMaxBytes` 를 넘으면 422 `NOVEL_BOARD_LAYOUT_TOO_LARGE`.

    소설 행 하나만 고치고 다른 행을 잡지 않으므로 잠금 순서에 끼지 않는다."""
    stored = payload.model_dump(mode="json", by_alias=True)
    if len(json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode()) > BOARD_LAYOUT_MAX_BYTES:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_BOARD_LAYOUT_TOO_LARGE")
    await db.execute(update(Novel).where(Novel.id == novel.id).values(board_layout=stored))
    await db.commit()


# ── 읽은 위치 ───────────────────────────────────────────────────────────────
@router.put(
    "/{novel_id}/chapters/{chapter_id}/reading-position",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_legal_consent)],
)
async def save_novel_reading_position(
    chapter_id: uuid.UUID,
    payload: NovelReadingPositionRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """화를 읽던 자리를 저장한다. 화면을 떠날 때 응답을 기다리지 않는 요청으로도 오므로 본문이 작고 응답 본문이 없다.
    같은 값을 다시 보내도 결과가 같고, 한 번 다 읽은 화(`finished`)는 앞부분을 다시 읽어 저장해도 다 읽은 화로 남는다.
    문단 번호가 문단 수 밖이면 422 `NOVEL_PARAGRAPH_RANGE_INVALID`, 없는 화(지워진 화 포함)는 404
    `NOVEL_CHAPTER_NOT_FOUND`. 읽기는 수정이 아니라 소설 수정 시각은 밀지 않는다.

    화 행을 키 공유 잠금으로 확인한 뒤 저장한다. 묶음·소설 삭제는 화를 `FOR UPDATE` 로 잠근 뒤 읽은 위치를 지우므로, 이쪽이
    먼저 잡으면 삭제가 이 저장을 기다렸다가 함께 지우고, 삭제가 먼저 잡았으면 이 확인이 기다렸다가 화가 없음을 보고 404
    다. 확인 없이 저장하면 삭제가 커밋된 뒤 FK 위반(500)이 난다. 사용자 행은 잡지 않는다 — 이 저장은 사용자 행 아래의
    행(작업·인물·스냅샷·클로버)을 고치지 않고 화 행 하나와 자기 행만 쥐므로, 사용자 → 작업 → 화 순서로 잡는 삭제와 서로를
    기다리는 일이 없다."""
    if payload.paragraph_index >= payload.paragraph_count:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_PARAGRAPH_RANGE_INVALID")
    locked = await db.scalar(
        select(NovelChapter.id)
        .where(NovelChapter.id == chapter_id, NovelChapter.novel_id == novel.id)
        .with_for_update(key_share=True, read=True)
    )
    if locked is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_CHAPTER_NOT_FOUND")
    stmt = insert(NovelReadingPosition).values(
        chapter_id=chapter_id,
        novel_id=novel.id,
        paragraph_index=payload.paragraph_index,
        paragraph_count=payload.paragraph_count,
        revision_id=payload.revision_id,
        finished_at=func.now() if payload.finished else None,
        updated_at=func.now(),
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[NovelReadingPosition.chapter_id],
            set_={
                "paragraph_index": stmt.excluded.paragraph_index,
                "paragraph_count": stmt.excluded.paragraph_count,
                "revision_id": stmt.excluded.revision_id,
                # 한 번 찍힌 다 읽은 시각은 되돌리지 않는다.
                "finished_at": func.coalesce(NovelReadingPosition.finished_at, stmt.excluded.finished_at),
                "updated_at": func.now(),
            },
        )
    )
    await db.commit()


# ── 스냅샷 ─────────────────────────────────────────────────────────────────
def _snapshot_summary(snapshot: NovelSnapshot) -> NovelSnapshotSummary:
    return NovelSnapshotSummary(id=snapshot.id, name=snapshot.name, kind=snapshot.kind, created_at=snapshot.created_at)


async def _get_snapshot(db: AsyncSession, novel: Novel, snapshot_id: uuid.UUID) -> NovelSnapshot:
    snapshot = await db.scalar(
        select(NovelSnapshot)
        .where(NovelSnapshot.id == snapshot_id, NovelSnapshot.novel_id == novel.id)
        .execution_options(populate_existing=True)
    )
    if snapshot is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_SNAPSHOT_NOT_FOUND")
    return snapshot


@router.get("/{novel_id}/snapshots")
async def list_novel_snapshots(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSnapshotListResponse:
    """스냅샷 목록(최근 것 먼저). 내용은 상세로 따로 읽는다."""
    snapshots = await db.scalars(
        select(NovelSnapshot)
        .where(NovelSnapshot.novel_id == novel.id)
        .order_by(NovelSnapshot.created_at.desc(), NovelSnapshot.id.desc())
    )
    return NovelSnapshotListResponse(
        items=[_snapshot_summary(snapshot) for snapshot in snapshots.all()], limit=settings.novelize_snapshot_limit
    )


@router.post(
    "/{novel_id}/snapshots", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_legal_consent)]
)
async def create_novel_snapshot(
    payload: NovelSnapshotCreateRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSnapshotSummary:
    """지금 상태를 이름 붙여 저장한다(무과금) — 소설 제목·소개·설정 노트, 인물 카드, 화마다 지금 개정·제목·요약·작가의
    말. 상한에 닿으면 가장 오래된 복원 직전 자동 스냅샷부터 지우고, 이름 붙인 것만으로 차 있으면 409
    `NOVEL_SNAPSHOT_LIMIT`(하나 지운 뒤 다시).

    사용자 행을 먼저 잠근다 — 개수를 세고 지우고 넣는 사이에 같은 소설의 다른 저장·복원이 끼면 둘 다 자리가 있다고 보고
    상한을 넘긴다. 인물 카드를 읽는 순간도 카드를 고치는 경로들과 같은 잠금 아래라 어중간한 상태를 뜨지 않는다."""
    await _lock_user(db, novel.user_id)
    try:
        snapshot = await save_snapshot(db, novel.id, name=payload.name, kind="manual")
    except SnapshotLimitError as exc:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SNAPSHOT_LIMIT") from exc
    await db.commit()
    return _snapshot_summary(snapshot)


@router.get("/{novel_id}/snapshots/{snapshot_id}")
async def get_novel_snapshot(
    snapshot_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSnapshotDetail:
    """스냅샷 내용. 화의 본문은 싣지 않는다 — 비교 화면은 화마다 `revisionId` 의 개정을 개정 조회로 읽는다(화가 지워졌으면
    그 항목은 `deleted`)."""
    snapshot = await _get_snapshot(db, novel, snapshot_id)
    payload = snapshot.payload
    return NovelSnapshotDetail(
        **_snapshot_summary(snapshot).model_dump(),
        title=payload["title"],
        title_edited=payload["titleEditedAt"] is not None,
        synopsis=payload["synopsis"],
        setting_notes=payload["settingNotes"],
        characters=[
            NovelSnapshotCharacter(id=c["id"], name=c["name"], aliases=c["aliases"], memo=c["memo"])
            for c in payload["characters"]
        ],
        chapters=[
            NovelSnapshotChapter(
                chapter_id=entry["chapterId"],
                deleted=bool(entry.get("deleted")),
                revision_id=entry.get("revisionId"),
                title=entry.get("title"),
                summary=entry.get("summary"),
                author_note=entry.get("authorNote"),
            )
            for entry in payload["chapters"]
        ],
    )


@router.post("/{novel_id}/snapshots/{snapshot_id}/restore", dependencies=[Depends(require_legal_consent)])
async def restore_novel_snapshot(
    snapshot_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSnapshotRestoreResponse:
    """스냅샷 때의 내용으로 되돌린다(무과금). 구조는 그대로다 — 스냅샷 뒤에 생긴 화는 지우지 않고, 스냅샷의 화는 그때
    본문을 새 개정으로 쌓고(이력은 남는다) 화 제목·요약·작가의 말을 그때 값으로 덮는다. 소설 제목·소개·설정 노트와 인물
    카드도 그때 값이다. 화나 그때 개정이 지워진 화는 건너뛰고 `skippedChapters` 에 싣는다. 되돌리기 직전 상태는 자동
    스냅샷(`autoSnapshotId`)으로 남는다(상한에 닿아도 한 장 더 둔다). 진행 중 작업이 있으면(연쇄 포함) 409
    `NOVEL_JOB_IN_PROGRESS` — 생성 결과 저장이 같은 화·인물·제목을 고치기 때문이다. 없는 스냅샷은 404
    `NOVEL_SNAPSHOT_NOT_FOUND`.

    죽은 작업을 먼저 정리해 커밋한다(서버 재기동으로 남은 작업이 복원을 계속 막지 않게). 그다음 사용자 행을 잠근다 — 작업
    생성도 사용자 행을 먼저 잡으므로, 진행 중 확인과 복원 사이에 새 작업이 끼지 못한다. 화 → 소설 순서는
    `snapshots.restore_snapshot` 에 있다. 커밋한 뒤 새 개정을 쌓은 화마다 낡은 AI 수정 미리보기를 **별도 트랜잭션에서**
    비운다 — 화를 쥔 채 작업 행을 고치면 작업 → 화 순서로 잡는 적용과 교착한다(직접 수정과 같은 이유)."""
    await expire_stale_jobs(db, novel_id=novel.id)
    await db.commit()
    await _lock_user(db, novel.user_id)
    snapshot = await _get_snapshot(db, novel, snapshot_id)
    active = await db.scalar(
        select(NovelJob.id).where(NovelJob.novel_id == novel.id, NovelJob.status.in_(ACTIVE_JOB_STATUSES)).limit(1)
    )
    if active is not None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_JOB_IN_PROGRESS")
    result = await restore_snapshot(db, novel.id, snapshot)
    await db.commit()
    for chapter_id in result.restacked_chapter_ids:
        await _erase_stale_previews(db, chapter_id)
    return NovelSnapshotRestoreResponse(
        novel=await _detail(db, novel.id),
        skipped_chapters=result.skipped_chapter_ids,
        auto_snapshot_id=result.auto_snapshot_id,
    )


@router.delete("/{novel_id}/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_novel_snapshot(
    snapshot_id: uuid.UUID,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """스냅샷 하나를 지운다(이름 붙인 것·자동 것 모두). 자기 데이터를 지우는 길이라 재동의 게이트를 걸지 않는다. 없으면 404
    `NOVEL_SNAPSHOT_NOT_FOUND`. 개정은 스냅샷과 무관하게 남는다."""
    deleted = await db.scalar(
        delete(NovelSnapshot)
        .where(NovelSnapshot.id == snapshot_id, NovelSnapshot.novel_id == novel.id)
        .returning(NovelSnapshot.id)
    )
    if deleted is None:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_SNAPSHOT_NOT_FOUND")
    await db.commit()
