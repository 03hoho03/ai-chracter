"""작가의 통합 작품 목록 — 캐릭터·스토리(발행작·초안)와 소설을 마지막 편집 순 한 목록으로.

줄 세우기와 자르기는 쿼리 하나가 한다: 작품 표와 소설 표에서 (편집 시각, 유형, id) 만 `UNION ALL` 로 뽑아 그 키 하나로
정렬하고 커서로 자른다. 유형마다 따로 페이지를 넘겨 화면에서 섞으면 페이지 경계에서 순서가 틀리고, 서버가 한 키로 자르면
경계의 중복·누락을 테스트로 고정할 수 있다. 행 내용은 그 페이지의 id 로 유형마다 한 번에 채운다.

유형이 키에 들어가는 이유: 작품과 소설은 다른 표라 id 가 같을 수 있다. (시각, id) 만으로 자르면 같은 시각·같은 id 의 다른
유형 행이 커서 경계에서 빠진다."""

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, String, case, exists, func, literal, or_, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from api.content.router import CREATOR_CONTENT_PAGE_SIZE, CREATOR_CONTENT_QUERY_MAX_LENGTH, sign_thumbnail_url
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus
from api.db.models.media import Asset
from api.db.models.novel import Novel, NovelChapter, NovelPublication
from api.db.models.story import StoryVersionDetail
from api.db.session import get_db_session
from api.novel_public.access import select_readable_publications
from api.novelize.access import has_novelize_access
from api.novelize.router import _covers
from api.session.dependencies import get_current_user_id
from api.works.schemas import (
    ContentWorkItem,
    NovelWorkItem,
    NovelWorkPublication,
    WorkItem,
    WorkListResponse,
    WorkListStatus,
    WorkListType,
)

router = APIRouter(prefix="/me", tags=["works"])

_KINDS = ("character", "story", "novel")


# ── 커서 ────────────────────────────────────────────────────────────────────
# `content/router.py` 의 `_encode_cursor` 와 같은 인코딩(base64 JSON 문자열 목록). 모듈마다 복제하는 것이 이 저장소의
# 관례다(`novel_public/reading.py` 의 같은 복제).
def _encode_cursor(edited_at: datetime, kind: str, work_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([edited_at.isoformat(), kind, str(work_id)]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str, uuid.UUID]:
    """깨진 커서는 422 `INVALID_CURSOR` 다(손으로 고친 주소가 500 이 되지 않게)."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        edited_at, kind, work_id = decoded
        if kind not in _KINDS:
            raise ValueError(kind)
        return datetime.fromisoformat(edited_at), kind, uuid.UUID(work_id)
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "INVALID_CURSOR"}
        ) from None


# ── 키 쿼리 ─────────────────────────────────────────────────────────────────
def _title_version_id() -> Any:
    """목록이 제목·썸네일을 읽는 버전 — 가장 최근 미발행 버전(작가가 고치고 있는 초안). 발행은 다음 편집용 초안을 복제해
    두지만 그 초안이 없는 발행작(개발 시드의 샘플 캐릭터처럼 발행본만 넣은 행)은 발행본으로 대신한다 — 빠지면 발행작 목록에는
    있는 작품이 이 목록에서 사라진다."""
    latest_draft = (
        select(ContentVersion.id)
        .where(ContentVersion.content_id == Content.id, ContentVersion.published_at.is_(None))
        .order_by(ContentVersion.created_at.desc())
        .limit(1)
        .correlate(Content)
        .scalar_subquery()
    )
    return func.coalesce(latest_draft, Content.current_published_version_id)


def _content_keys(
    user_id: uuid.UUID, type_: WorkListType, status_: WorkListStatus, term: str | None
) -> Select[Any] | None:
    if type_ == "novel" or status_ == "review":
        return None
    kind = case((Content.type == ContentType.CHARACTER, literal("character")), else_=literal("story"))
    query = select(kind.label("kind"), Content.id.label("id"), Content.edited_at.label("edited_at")).where(
        Content.creator_user_id == user_id, Content.moderation_status != ModerationStatus.DELETED
    )
    if type_ != "all":
        query = query.where(Content.type == ContentType(type_))
    published = Content.current_published_version_id.is_not(None)
    if status_ == "draft":
        query = query.where(Content.current_published_version_id.is_(None))
    elif status_ == "public":
        query = query.where(
            published,
            Content.visibility == ContentVisibility.PUBLIC,
            Content.moderation_status == ModerationStatus.NORMAL,
        )
    elif status_ == "changed":
        query = query.where(published, Content.has_unpublished_changes.is_(True))
    if term is not None:
        version_id = _title_version_id()
        query = query.where(
            or_(
                exists().where(
                    CharacterVersionDetail.content_version_id == version_id,
                    CharacterVersionDetail.name.icontains(term, autoescape=True),
                ),
                exists().where(
                    StoryVersionDetail.content_version_id == version_id,
                    StoryVersionDetail.name.icontains(term, autoescape=True),
                ),
            )
        )
    return query


def _novel_keys(
    user_id: uuid.UUID, type_: WorkListType, status_: WorkListStatus, term: str | None
) -> Select[Any] | None:
    if type_ not in ("all", "novel") or status_ == "changed":
        return None
    # 독자 판정(`select_readable_publications`)이 `Novel` 을 자기 조인에 쓰므로 바깥 소설은 별칭으로 둔다 — 같은 이름이면
    # 상관 조건이 안쪽 행을 가리켜 아무 소설의 공개에나 걸린다.
    novel = aliased(Novel)
    query = select(
        literal("novel", String).label("kind"), novel.id.label("id"), novel.updated_at.label("edited_at")
    ).where(novel.user_id == user_id, novel.hidden_at.is_(None))
    has_publication = exists().where(NovelPublication.novel_id == novel.id)
    if status_ == "draft":
        # 첫 공개 반려는 독자에게 보인 적이 없다 — 심사는 연재권 잠금 전 첫 공개에만 걸린다.
        query = query.where(
            or_(
                ~has_publication,
                exists().where(NovelPublication.novel_id == novel.id, NovelPublication.review_status == "rejected"),
            )
        )
    elif status_ == "public":
        query = query.where(
            select_readable_publications(NovelPublication.novel_id)
            .where(NovelPublication.novel_id == novel.id)
            .exists()
        )
    elif status_ == "review":
        query = query.where(
            exists().where(NovelPublication.novel_id == novel.id, NovelPublication.review_status == "pending")
        )
    if term is not None:
        query = query.where(func.coalesce(novel.title, novel.content_title).icontains(term, autoescape=True))
    return query


# ── 행 채우기 ───────────────────────────────────────────────────────────────
async def _content_items(db: AsyncSession, content_ids: list[uuid.UUID]) -> dict[uuid.UUID, ContentWorkItem]:
    """작품 한 페이지를 쿼리 네 번으로 채운다(작품과 제목 버전, 캐릭터 상세, 스토리 상세, 썸네일 자산). 상세가 없는
    작품은 빠진다(`/me/drafts` 와 같은 규칙)."""
    if not content_ids:
        return {}
    rows = (
        await db.execute(select(Content, _title_version_id().label("version_id")).where(Content.id.in_(content_ids)))
    ).all()
    version_ids = [version_id for _content, version_id in rows if version_id is not None]
    details: dict[uuid.UUID, CharacterVersionDetail | StoryVersionDetail] = {}
    for character in (
        await db.scalars(
            select(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id.in_(version_ids))
        )
    ).all():
        details[character.content_version_id] = character
    for story in (
        await db.scalars(select(StoryVersionDetail).where(StoryVersionDetail.content_version_id.in_(version_ids)))
    ).all():
        details[story.content_version_id] = story
    asset_ids = {detail.thumbnail_asset_id for detail in details.values() if detail.thumbnail_asset_id is not None}
    assets = (
        {asset.id: asset for asset in (await db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))).all()}
        if asset_ids
        else {}
    )
    items: dict[uuid.UUID, ContentWorkItem] = {}
    for content, version_id in rows:
        detail = details.get(version_id) if version_id is not None else None
        if detail is None:
            continue
        asset = assets.get(detail.thumbnail_asset_id) if detail.thumbnail_asset_id is not None else None
        thumbnail_url = sign_thumbnail_url(asset) if asset is not None else None
        items[content.id] = ContentWorkItem(
            kind="character" if content.type == ContentType.CHARACTER else "story",
            id=content.id,
            title=detail.name,
            thumbnail_url=thumbnail_url,
            edited_at=content.edited_at,
            has_published=content.current_published_version_id is not None,
            visibility=content.visibility,
            moderation_status=content.moderation_status,
            has_unpublished_changes=content.has_unpublished_changes,
            view_count=content.view_count,
            chat_count=content.chat_count,
            like_count=content.like_count,
        )
    return items


async def _novel_items(db: AsyncSession, novel_ids: list[uuid.UUID]) -> dict[uuid.UUID, NovelWorkItem]:
    """소설 한 페이지를 채운다(소설과 화 수, 표지, 공개 상태, 독자 판정). 소설 상세(`GET /novels/{id}`)는 부르지 않는다 —
    그 라우트는 낡은 작업을 만료·환불하고 커밋한다."""
    if not novel_ids:
        return {}
    chapter_count = (
        select(func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == Novel.id).scalar_subquery()
    )
    rows = (await db.execute(select(Novel, chapter_count).where(Novel.id.in_(novel_ids)))).all()
    covers = await _covers(db, [novel for novel, _count in rows])
    publications = {
        publication.novel_id: publication
        for publication in (
            await db.scalars(select(NovelPublication).where(NovelPublication.novel_id.in_(novel_ids)))
        ).all()
    }
    readable = set(
        (
            await db.scalars(
                select_readable_publications(NovelPublication.novel_id).where(NovelPublication.novel_id.in_(novel_ids))
            )
        ).all()
    )
    items: dict[uuid.UUID, NovelWorkItem] = {}
    for novel, count in rows:
        publication = publications.get(novel.id)
        items[novel.id] = NovelWorkItem(
            kind="novel",
            id=novel.id,
            title=novel.title,
            content_title=novel.content_title,
            character_name=novel.character_name,
            cover=covers[novel.id][0],
            chapter_count=count,
            edited_at=novel.updated_at,
            publication=NovelWorkPublication(
                visibility=publication.visibility,
                review_status=publication.review_status,
                moderation_status=publication.moderation_status,
                readable=novel.id in readable,
            )
            if publication is not None
            else None,
        )
    return items


@router.get("/works")
async def list_my_works(
    type: WorkListType = "all",
    status_: WorkListStatus = Query("all", alias="status"),
    q: str | None = Query(None, max_length=CREATOR_CONTENT_QUERY_MAX_LENGTH),
    cursor: str | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> WorkListResponse:
    """내 캐릭터·스토리(운영 삭제 제외, 초안 포함)와 소설(숨김 제외)을 마지막 편집 순으로. 정렬 키는 (편집 시각, 유형, id)
    내림차순이고 편집 시각은 작품의 `edited_at`, 소설의 `updated_at` 이다. 커서는 그 셋을 담으므로 `type`·`status`·`q` 는
    페이지마다 다시 넘긴다.

    소설은 소설화 허용(`has_novelize_access`)이 있는 계정에만 섞는다 — 허용이 없으면(회수당해 소설 행만 남았어도) 소설은
    빠지고, `type=novel` 도 403 이 아니라 빈 목록이다.

    `status`:
    - `draft` 초안: 작품은 발행된 적 없음, 소설은 공개 상태 행이 없거나 첫 공개가 반려됨.
    - `public` 공개 중: 작품은 발행됨 ∧ 공개 ∧ 이용제한 아님(링크 공개·비공개 발행작은 아니다), 소설은 독자가 지금 읽을
      수 있음(`select_readable_publications`, 응답의 `publication.readable` 과 같은 판정).
    - `changed` 수정본 있음: 발행됨 ∧ 고친 초안이 있음 — 공개 범위·이용제한과 무관하다. 소설에는 없다.
    - `review` 심사 중: 소설의 첫 공개가 운영자 승인을 기다림. 작품에는 없다(작품 발행은 요청 안에서 끝난다).

    `q` 는 제목 부분 일치다 — 작품은 목록에 보이는 제목 버전(`_title_version_id`), 소설은 소설 제목(없으면 원작 제목).

    이미지는 싣지 않는다(제목·편집 시각이 없다)."""
    term = (q.strip() or None) if q is not None else None
    after = _decode_cursor(cursor) if cursor is not None else None
    branches = [_content_keys(user_id, type, status_, term)]
    if await has_novelize_access(db, user_id):
        branches.append(_novel_keys(user_id, type, status_, term))
    selects = [branch for branch in branches if branch is not None]
    if not selects:
        return WorkListResponse(items=[], next_cursor=None)

    keys = (union_all(*selects) if len(selects) > 1 else selects[0]).subquery()
    query = select(keys.c.kind, keys.c.id, keys.c.edited_at).order_by(
        keys.c.edited_at.desc(), keys.c.kind.desc(), keys.c.id.desc()
    )
    if after is not None:
        # 오른쪽은 평범한 튜플이다 — `tuple_` 끼리 비교하면 mypy 가 결과를 bool 로 본다.
        position: ColumnElement[bool] = tuple_(keys.c.edited_at, keys.c.kind, keys.c.id) < after
        query = query.where(position)
    rows = (await db.execute(query.limit(CREATOR_CONTENT_PAGE_SIZE + 1))).all()
    page = rows[:CREATOR_CONTENT_PAGE_SIZE]

    contents = await _content_items(db, [work_id for kind, work_id, _at in page if kind != "novel"])
    novels = await _novel_items(db, [work_id for kind, work_id, _at in page if kind == "novel"])
    items: list[WorkItem] = []
    for kind, work_id, _at in page:
        item = novels.get(work_id) if kind == "novel" else contents.get(work_id)
        if item is not None:
            items.append(item)

    # 커서는 항목이 아니라 조회한 마지막 **키 행**에서 뽑는다 — 상세가 없어 빠진 행이 페이지 끝이어도 다음 페이지가 그 행을
    # 다시 읽지 않게 하기 위해서다(`/me/drafts` 와 같은 규칙).
    next_cursor = (
        _encode_cursor(page[-1][2], page[-1][0], page[-1][1]) if len(rows) > CREATOR_CONTENT_PAGE_SIZE else None
    )
    return WorkListResponse(items=items, next_cursor=next_cursor)
