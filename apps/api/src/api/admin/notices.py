import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.db.models.moderation import Notification
from api.db.models.notice import Notice
from api.db.session import get_db_session
from api.notice.schemas import (
    AdminNoticeCreateRequest,
    AdminNoticeDetailResponse,
    AdminNoticeListItem,
    AdminNoticeListResponse,
    AdminNoticeUpdateRequest,
)

router = APIRouter(prefix="/admin/notices", tags=["admin"])

ADMIN_NOTICE_PAGE_SIZE = 20


def _to_detail(notice: Notice) -> AdminNoticeDetailResponse:
    # `updated_at`은 응답에 담지 않는다 — `Notice.updated_at`은 이 저장소에서 유일하게
    # `onupdate=func.now()`(SQL 쪽 표현식)를 쓰는 컬럼이라, PATCH/publish/unpublish로
    # 이 행을 수정한 직후 커밋 시점에 그 속성만 expire되고 `expire_on_commit=False`가
    # 막아주지 못한다(다른 컬럼과 동일 취급이 아니다) — 동기 코드에서 읽으면 재조회가
    # 필요한데 그게 그린렛 밖이라 `MissingGreenlet`으로 500이 난다(실측). 응답 스펙에
    # 없는 필드라 db.refresh()로 우회하는 대신 아예 빼는 쪽을 골랐다.
    return AdminNoticeDetailResponse(
        id=notice.id,
        title=notice.title,
        body_markdown=notice.body_markdown,
        published=notice.published,
        published_at=notice.published_at,
        created_at=notice.created_at,
    )


async def _get_or_404(db: AsyncSession, id: uuid.UUID) -> Notice:
    notice = await db.get(Notice, id)
    if notice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found")
    return notice


@router.get("")
async def list_admin_notices(
    page: int = Query(1, ge=1),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNoticeListResponse:
    """어드민 목록은 미게시 포함, offset 페이징 — `list_admin_reports`
    (`moderation/router.py:195`)와 같은 모양(techspec.md §4-2). 유저용 `/notices`가
    커서도 페이징도 없는 것과의 비대칭은 의도된 것이다 — 어드민 검토 작업은 특정
    페이지로 바로 건너뛰는 게 유리하다는 그 docstring의 근거를 그대로 따른다."""
    total_count = await db.scalar(select(func.count()).select_from(Notice)) or 0
    total_pages = -(-total_count // ADMIN_NOTICE_PAGE_SIZE) if total_count else 0

    notices = (
        await db.scalars(
            select(Notice)
            .order_by(Notice.created_at.desc())
            .offset((page - 1) * ADMIN_NOTICE_PAGE_SIZE)
            .limit(ADMIN_NOTICE_PAGE_SIZE)
        )
    ).all()

    return AdminNoticeListResponse(
        items=[
            AdminNoticeListItem(
                id=notice.id,
                title=notice.title,
                published=notice.published,
                published_at=notice.published_at,
                created_at=notice.created_at,
            )
            for notice in notices
        ],
        page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_admin_notice(
    body: AdminNoticeCreateRequest,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNoticeDetailResponse:
    notice = Notice(title=body.title, body_markdown=body.body_markdown)
    db.add(notice)
    await db.commit()
    return _to_detail(notice)


@router.get("/{id}")
async def get_admin_notice(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNoticeDetailResponse:
    notice = await _get_or_404(db, id)
    return _to_detail(notice)


@router.patch("/{id}")
async def update_admin_notice(
    id: uuid.UUID,
    body: AdminNoticeUpdateRequest,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNoticeDetailResponse:
    notice = await _get_or_404(db, id)
    if body.title is not None:
        notice.title = body.title
    if body.body_markdown is not None:
        notice.body_markdown = body.body_markdown
    await db.commit()
    return _to_detail(notice)


@router.post("/{id}/publish")
async def publish_admin_notice(
    id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNoticeDetailResponse:
    """게시 + 알림 fan-out을 같은 트랜잭션에서 동기 실행한다(techspec.md §4-3, D-16).

    - `published`가 이미 true면 아무것도 하지 않는다 — 전이일 때만 fan-out한다.
    - `published_at`은 최초 게시에만 부여한다. 숨김 → 재게시 경로에서는 이미 값이
      있으므로 원래 게시일이 유지된다(`db/models/notice.py`의 모델 docstring 근거와
      같다).
    - **`already_sent` 선행 확인 + `ux_notifications_notice_user` 부분 유니크
      인덱스로 2중 방어한다.** 전자가 숨김 → 재게시 경로에서 알림을 또 안 만들게
      막고, 후자는 경쟁 상황에서도 DB 제약으로 같은 결론을 보장한다.
    - **`gen_random_uuid()`는 이 저장소에서 여기가 유일하다.** 다른 모든 PK는
      파이썬 쪽 `default=uuid.uuid4`로 채워지는데, `INSERT ... SELECT`는 ORM을
      거치지 않아 그 default를 우회한다 — Postgres 18이라 내장 함수라서 확장 설치가
      따로 필요 없다(`docker-compose.{dev,prod}.yml`이 postgres:18).
    - 생존 유저 판정은 `User.deleted_at IS NULL`이다 — `session/suspension.py`의
      `rebuild_suspended_user_markers`가 같은 조건을 쓰는 선례다.
    - **알려진 대가**: 게시 후 가입한 유저는 이 fan-out의 대상이 아니라 그 공지의
      알림을 받지 못한다. 목록 `/notices`에는 항상 보이므로 알림만 못 받는 것이다.
    - fan-out 규모 실측(dev DB, 2026-09-07): `SELECT count(*) FROM users WHERE
      deleted_at IS NULL` = 3. 이 값은 로컬 dev 환경 것이라 "동기 실행이 프로덕션
      규모에서도 감당 가능하다"는 근거로 쓸 수는 없다 — 가입자 수가 크게 늘면 이
      가정(D-16)을 다시 실측해 재검증할 것.
    """
    notice = await _get_or_404(db, id)
    if notice.published:
        return _to_detail(notice)

    notice.published = True
    if notice.published_at is None:
        notice.published_at = datetime.now(UTC)

    already_sent = await db.scalar(
        select(literal(1)).select_from(Notification).where(Notification.notice_id == notice.id).limit(1)
    )
    if already_sent is None:
        await db.execute(
            text(
                """
                INSERT INTO notifications (id, user_id, type, notice_id, read, created_at)
                SELECT gen_random_uuid(), u.id, 'notice', :notice_id, false, now()
                FROM users u WHERE u.deleted_at IS NULL
                """
            ),
            {"notice_id": notice.id},
        )

    await record_admin_action(
        db, admin_id=admin_id, action_type="notice-publish", reason_text=f"공지 '{notice.title}' 게시"
    )
    await db.commit()
    return _to_detail(notice)


@router.post("/{id}/unpublish")
async def unpublish_admin_notice(
    id: uuid.UUID,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminNoticeDetailResponse:
    notice = await _get_or_404(db, id)
    notice.published = False
    await record_admin_action(
        db, admin_id=admin_id, action_type="notice-unpublish", reason_text=f"공지 '{notice.title}' 숨김"
    )
    await db.commit()
    return _to_detail(notice)
