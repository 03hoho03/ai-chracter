import uuid
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    CharacterVersionDetail,
    Comment,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
)


async def _make_comment_content(
    db: AsyncSession, creator_id: uuid.UUID, content_type: ContentType = ContentType.CHARACTER
) -> Content:
    content = Content(
        creator_user_id=creator_id,
        type=content_type,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="작품 소개"
    )
    db.add(version)
    await db.flush()
    if content_type == ContentType.CHARACTER:
        db.add(CharacterVersionDetail(
            content_version_id=version.id, name="댓글 캐릭터", one_liner="소개", intro="시작",
            example_dialogues=[], character_prompt="설정",
        ))
    else:
        db.add(StoryVersionDetail(
            content_version_id=version.id, name="댓글 스토리", one_liner="소개",
            prompt_template=StoryPromptTemplate.BASIC, setting_text="설정",
        ))
    content.current_published_version_id = version.id
    await db.flush()
    return content


async def _make_comment(
    db: AsyncSession, content: Content, author_id: uuid.UUID, **overrides: object
) -> Comment:
    values: dict[str, object] = {
        "content_id": content.id,
        "author_user_id": author_id,
        "body": "감상 댓글",
        "request_id": uuid.uuid4(),
        "request_fingerprint": "test-fixture",
    }
    values.update(overrides)
    comment = Comment(**values)
    db.add(comment)
    await db.flush()
    return comment


def _comment_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "requestId": str(uuid.uuid4()),
        "body": "감상 댓글",
        "stickerId": None,
        "isSpoiler": False,
        "mentionUserIds": [],
        "rootCommentId": None,
        "replyToCommentId": None,
    }
    values.update(overrides)
    return values
