import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Comment, Content, ContentVisibility, ModerationStatus, User


def comment_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def require_readable_content(content: Content, viewer_id: uuid.UUID | None) -> None:
    if (
        content.current_published_version_id is None
        or content.moderation_status != ModerationStatus.NORMAL
        or (content.visibility == ContentVisibility.PRIVATE and content.creator_user_id != viewer_id)
    ):
        raise comment_error(404, "CONTENT_UNAVAILABLE", "이 작품의 댓글을 볼 수 없습니다.")


async def get_readable_content(
    db: AsyncSession, content_id: uuid.UUID, viewer_id: uuid.UUID | None
) -> Content:
    content = await db.get(Content, content_id)
    if content is None:
        raise comment_error(404, "CONTENT_UNAVAILABLE", "이 작품의 댓글을 볼 수 없습니다.")
    require_readable_content(content, viewer_id)
    return content


async def lock_active_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """인증 후 탈퇴·정지가 경합해도 갱신된 회원 상태로 쓰기 권한을 다시 확인한다."""
    # FK의 KEY SHARE는 허용하되 같은 회원의 쓰기·탈퇴는 직렬화한다.
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True)
                           .execution_options(populate_existing=True))
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.suspended_at is not None:
        raise HTTPException(status_code=403, detail="Account suspended")
    return user


async def lock_content(db: AsyncSession, content_id: uuid.UUID) -> Content:
    content = await db.scalar(select(Content).where(Content.id == content_id).with_for_update()
                              .execution_options(populate_existing=True))
    if content is None:
        raise comment_error(404, "CONTENT_UNAVAILABLE", "이 작품의 댓글을 볼 수 없습니다.")
    return content


async def lock_comment_context(db: AsyncSession, comment_id: uuid.UUID) -> tuple[Content, Comment]:
    """일반 쓰기 호출자는 먼저 회원을 잠근다. 운영자는 작품→댓글 잠금을 사용한다."""
    content_id = await db.scalar(select(Comment.content_id).where(Comment.id == comment_id))
    if content_id is None:
        raise comment_error(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    content = await lock_content(db, content_id)
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id).with_for_update()
                             .execution_options(populate_existing=True))
    if comment is None:
        raise comment_error(404, "COMMENT_NOT_FOUND", "댓글을 찾을 수 없습니다.")
    return content, comment


def require_participation(content: Content) -> None:
    if content.visibility == ContentVisibility.PRIVATE:
        raise comment_error(403, "COMMENT_PARTICIPATION_UNAVAILABLE", "비공개 작품에는 새로 참여할 수 없습니다.")


def require_creator(content: Content, user_id: uuid.UUID) -> None:
    if content.creator_user_id != user_id:
        raise comment_error(403, "COMMENT_OWNER_REQUIRED", "작품 제작자만 관리할 수 있습니다.")


def require_unhide_allowed(comment: Comment) -> None:
    """삭제된 원댓글은 내용 복원 없이 스레드 숨김 flag만 해제할 수 있다."""
    if comment.deleted_at is not None and comment.root_comment_id is not None:
        raise comment_error(409, "COMMENT_DELETED", "삭제된 대댓글의 숨김을 해제할 수 없습니다.")
