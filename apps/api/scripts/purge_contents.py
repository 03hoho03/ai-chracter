"""운영자가 api 컨테이너 안에서 돌려 작품(contents) 몇 편을 DB 와 저장소에서 완전히 지우는 도구.

앱에는 발행된 적 있는 작품을 지우는 경로가 없다(초안 삭제는 발행작이면 거부한다). 이 스크립트가 그 빈자리를 운영자 손으로만
메운다. 기본은 계획이다 — 무엇을 몇 행 지우고 무엇을 남기는지, 왜 거부하는지를 보여 주기만 하고 쓰지 않는다. 적용은 대상 작품
수를 따로 적어야 하고(`--expect-contents`), 지운 행이 가리키던 저장소 키는 커밋 전에 파일로 남겨 두었다가 커밋이 끝난 뒤 별도
명령(`delete-objects`)으로 지운다. DB 와 저장소를 한 트랜잭션으로 묶을 수 없어서, 커밋이 실패해도 그림이 먼저 사라지지 않게
순서를 나눈 것이다.

    # 계획만(쓰기 없음)
    python scripts/purge_contents.py plan --ids-file ids.txt

    # 적용 — 한 트랜잭션. 지울 저장소 키를 keys.json 에 남긴다
    python scripts/purge_contents.py apply --ids-file ids.txt --expect-contents 2 --keys-out keys.json

    # 저장소 정리 — 기본은 지울 키 수만 보여 주고, --apply 를 붙여야 지운다
    python scripts/purge_contents.py delete-objects --keys-file keys.json --apply

ids 파일은 한 줄에 작품 id 하나이고, 빈 줄과 `#` 로 시작하는 줄은 무시한다.

함께 지우는 것: 그 작품의 모든 대화방(다른 회원의 방 포함)과 그 자식, 그 작품이 원작이거나 그 방에서 나온 소설, 회원이 그
작품에 남긴 좋아요·즐겨찾기·대화 참여·이미지 노출·신고·엔딩 수집, 버전과 그 자식, 대상 작품만 쓰던 그림. 운영 조치·통지·
조치 기록·응답 신고·버린 응답 기록은 기록이라 행을 남기고 작품·방·소설 칸만 FK(`SET NULL`)가 비운다. 돈·공개·남의 글이
얽힌 행(댓글, 클로버 사용처, 정산 내역, 홈 지정, 공개·판매된 소설)이나 남이 쓰는 그림·시작설정이 있으면 아무것도 쓰지 않고
거부한다 — 그런 작품은 운영자가 먼저 그 얽힘을 정리해야 한다.
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.router import collect_asset_usages, delete_emptied_generation_requests
from api.chat.room_deletion import delete_chat_rooms
from api.core.s3 import build_variant_keys, delete_object

# 초안 자식 삭제는 라우터 안에만 있다. 사본을 두면 버전 자식 테이블이 늘 때 한쪽에만 더해지므로 private 함수를 그대로 쓴다
# (시드 업서트도 같은 이유로 라우터의 private 함수를 import 한다).
from api.content.router import _delete_draft_children
from api.db.models import (
    AdminActionLog,
    Asset,
    AssetKind,
    CharacterImageExposure,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageReport,
    ChatRoom,
    CloverSpendUsage,
    Comment,
    Content,
    ContentChatParticipant,
    ContentType,
    ContentVersion,
    CreatorPayoutConfirmationLine,
    DiscardedResponse,
    Favorite,
    HomeCuration,
    HomeNovelCuration,
    ImageGenerationRequest,
    Inquiry,
    Like,
    MediaBookCell,
    ModerationAction,
    Notification,
    Novel,
    NovelChapter,
    NovelChapterIllustration,
    NovelChapterRevision,
    NovelPublication,
    NovelPurchase,
    Report,
    SituationalImage,
    StartingSetup,
    StoryEndingUnlock,
    StoryMediaExposure,
    StoryVersionDetail,
    User,
)
from api.novelize.deletion import delete_novels
from api.novelize.illustrations import UPLOAD_KEY_PREFIX

# 버전이 그림을 가리키는 여섯 칸 — 생성 이미지 삭제의 사용처 판정(`collect_asset_usages`)이 훑는 칸과 같다.
_VERSION_ASSET_COLUMNS: tuple[tuple[Any, Any], ...] = (
    (CharacterVersionDetail.content_version_id, CharacterVersionDetail.thumbnail_asset_id),
    (StoryVersionDetail.content_version_id, StoryVersionDetail.thumbnail_asset_id),
    (SituationalImage.content_version_id, SituationalImage.image_asset_id),
    (SituationalImage.content_version_id, SituationalImage.blurred_asset_id),
    (MediaBookCell.content_version_id, MediaBookCell.image_asset_id),
    (MediaBookCell.content_version_id, MediaBookCell.blurred_asset_id),
)


@dataclass
class PurgePlan:
    content_ids: list[uuid.UUID]
    missing_ids: list[uuid.UUID]
    counts: dict[str, int] = field(default_factory=dict)
    refusals: list[str] = field(default_factory=list)
    asset_ids: list[uuid.UUID] = field(default_factory=list)
    storage_keys: list[str] = field(default_factory=list)


class PurgeRefused(Exception):  # noqa: N818 — 테스트·운영 안내가 이 이름으로 부른다(오류가 아니라 의도한 거부다)
    """계획에 거부 사유가 있거나 적용 조건이 맞지 않아 아무것도 쓰지 않았다."""

    def __init__(self, plan: PurgePlan) -> None:
        super().__init__("; ".join(plan.refusals))
        self.plan = plan


@dataclass
class _Targets:
    """적용이 지울 행의 id. 계획과 적용이 같은 계산을 쓰게 한 곳에서 만든다."""

    contents: list[tuple[uuid.UUID, ContentType]]
    version_ids: list[uuid.UUID]
    setup_entity_ids: list[uuid.UUID]
    room_ids: list[uuid.UUID]
    novel_ids: list[uuid.UUID]
    # 대상 버전만 쓰던 그림(이 스크립트가 지운다)과, 소설 삭제가 삽화 정리로 지울 그림의 키(`delete_novels` 가 지운다).
    content_assets: list[Asset]
    novel_storage_keys: list[str]


async def _count(db: AsyncSession, model: Any, *conditions: Any) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


async def _ids(db: AsyncSession, query: Select[Any]) -> list[uuid.UUID]:
    return sorted({value for value in (await db.scalars(query)).all() if value is not None})


async def _novel_freed_assets(db: AsyncSession, novel_ids: list[uuid.UUID]) -> tuple[list[uuid.UUID], list[str]]:
    """`delete_novels` 가 끝에 지울 삽화 그림과 그 저장소 키를 미리 센다(`delete_unused_illustration_assets` 의 판정을 그대로
    옮긴 것). 적용은 이 값과 실제로 지운 키가 같은지 확인한다 — 키 파일은 계획의 키 목록이고 저장소는 그 파일로만 지운다.

    그 함수가 도는 시점의 DB 를 기준으로 본다 — 대상 소설의 배치·소설 행은 이미 지워졌고, 대상 작품의 버전은 아직 남아 있다.
    그래서 대상 작품 버전이 쓰는 그림은 여기서 빠지고 이 스크립트의 그림 정리가 지운다."""
    if not novel_ids:
        return [], []
    revision_ids = (
        select(NovelChapterRevision.id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id.in_(novel_ids))
    )
    withdrawn_owner = select(User.id).where(User.id == Asset.owner_user_id, User.deleted_at.is_not(None)).exists()
    candidates = list(
        (
            await db.scalars(
                select(Asset).where(
                    Asset.id.in_(
                        select(NovelChapterIllustration.asset_id).where(
                            NovelChapterIllustration.revision_id.in_(revision_ids)
                        )
                    ),
                    or_(
                        (Asset.kind == AssetKind.ORIGINAL) & Asset.storage_key.startswith(UPLOAD_KEY_PREFIX),
                        (Asset.kind == AssetKind.GENERATED) & withdrawn_owner,
                    ),
                )
            )
        ).all()
    )
    if not candidates:
        return [], []
    candidate_ids = [asset.id for asset in candidates]
    referenced: set[uuid.UUID | None] = set((await collect_asset_usages(db, candidate_ids)).keys())
    referenced |= set(
        await _ids(
            db,
            select(NovelChapterIllustration.asset_id).where(
                NovelChapterIllustration.asset_id.in_(candidate_ids),
                NovelChapterIllustration.revision_id.not_in(revision_ids),
            ),
        )
    )
    referenced |= set(
        await _ids(db, select(Inquiry.attachment_asset_id).where(Inquiry.attachment_asset_id.in_(candidate_ids)))
    )
    referenced |= set(
        await _ids(db, select(User.profile_image_asset_id).where(User.profile_image_asset_id.in_(candidate_ids)))
    )
    referenced |= set(
        await _ids(
            db, select(Novel.cover_asset_id).where(Novel.cover_asset_id.in_(candidate_ids), Novel.id.not_in(novel_ids))
        )
    )
    freed = [asset for asset in candidates if asset.id not in referenced]
    keys = [key for asset in freed for key in (asset.storage_key, *build_variant_keys(asset.storage_key))]
    return sorted(asset.id for asset in freed), sorted(set(keys))


async def _plan(db: AsyncSession, content_ids: Sequence[uuid.UUID]) -> tuple[PurgePlan, _Targets]:
    ids = sorted(set(content_ids))
    contents = [
        (content_id, content_type)
        for content_id, content_type in (
            await db.execute(select(Content.id, Content.type).where(Content.id.in_(ids)).order_by(Content.id))
        ).tuples()
    ]
    found = [content_id for content_id, _ in contents]
    plan = PurgePlan(content_ids=ids, missing_ids=[content_id for content_id in ids if content_id not in found])
    refusals = plan.refusals
    if plan.missing_ids:
        refusals.append(f"DB 에 없는 작품 id {len(plan.missing_ids)}개 — 다른 환경의 목록이거나 오타일 수 있다")

    version_ids = await _ids(db, select(ContentVersion.id).where(ContentVersion.content_id.in_(found)))
    setup_entity_ids = await _ids(
        db, select(StartingSetup.entity_id).where(StartingSetup.content_version_id.in_(version_ids))
    )
    room_ids = await _ids(db, select(ChatRoom.id).where(ChatRoom.content_id.in_(found)))
    # 방을 지우면 `novels.chat_room_id` 가 비므로(`SET NULL`) 방에서 나온 소설은 방 삭제 전에 골라 둔다.
    novel_ids = await _ids(
        db, select(Novel.id).where(or_(Novel.content_id.in_(found), Novel.chat_room_id.in_(room_ids)))
    )

    shared_setups = await _count(
        db,
        StartingSetup,
        StartingSetup.entity_id.in_(setup_entity_ids),
        StartingSetup.content_version_id.not_in(version_ids),
    )
    if shared_setups:
        refusals.append(
            f"대상 밖 작품의 시작설정 {shared_setups}개가 대상과 같은 entity id 를 쓴다 — 엔딩 수집은 그 id 로만 이어져 있어"
            " 지우면 그 작품의 수집까지 지워진다"
        )
    blockers: list[tuple[str, Any, Any]] = [
        ("댓글", Comment, Comment.content_id.in_(found)),
        ("정산 확정 내역", CreatorPayoutConfirmationLine, CreatorPayoutConfirmationLine.content_id.in_(found)),
        ("홈 지정", HomeCuration, HomeCuration.content_id.in_(found)),
        ("클로버 사용처(작품 칸)", CloverSpendUsage, CloverSpendUsage.content_id.in_(found)),
        # 방·소설 칸에는 FK 가 없어 DB 가 막아 주지 않는다 — 여기서 보지 않으면 사용처가 지워진 방·소설을 가리키는 고아가 된다.
        ("클로버 사용처(방 칸)", CloverSpendUsage, CloverSpendUsage.chat_room_id.in_(room_ids)),
        ("클로버 사용처(소설 칸)", CloverSpendUsage, CloverSpendUsage.novel_id.in_(novel_ids)),
        ("노벨 공개 상태", NovelPublication, NovelPublication.novel_id.in_(novel_ids)),
        ("노벨 구매", NovelPurchase, NovelPurchase.novel_id.in_(novel_ids)),
        ("홈 노벨 지정", HomeNovelCuration, HomeNovelCuration.novel_id.in_(novel_ids)),
    ]
    for label, model, condition in blockers:
        blocking = await _count(db, model, condition)
        if blocking:
            refusals.append(
                f"{label} {blocking}개가 대상 작품·방·소설을 가리킨다 — 기록·공개가 얽혀 있어 지우지 않는다"
            )

    used_by_targets: set[uuid.UUID] = set()
    used_elsewhere: set[uuid.UUID] = set()
    for version_column, asset_column in _VERSION_ASSET_COLUMNS:
        used_by_targets |= set(await _ids(db, select(asset_column).where(version_column.in_(version_ids))))
    for version_column, asset_column in _VERSION_ASSET_COLUMNS:
        used_elsewhere |= set(
            await _ids(
                db,
                select(asset_column).where(asset_column.in_(used_by_targets), version_column.not_in(version_ids)),
            )
        )
    content_asset_ids = sorted(used_by_targets - used_elsewhere)
    novel_revision_ids = (
        select(NovelChapterRevision.id)
        .join(NovelChapter, NovelChapter.id == NovelChapterRevision.chapter_id)
        .where(NovelChapter.novel_id.in_(novel_ids))
    )
    asset_blockers: list[tuple[str, Any, Any]] = [
        (
            "남길 소설의 삽화",
            NovelChapterIllustration,
            NovelChapterIllustration.asset_id.in_(content_asset_ids)
            & NovelChapterIllustration.revision_id.not_in(novel_revision_ids),
        ),
        ("회원 프로필 이미지", User, User.profile_image_asset_id.in_(content_asset_ids)),
        ("문의 첨부", Inquiry, Inquiry.attachment_asset_id.in_(content_asset_ids)),
    ]
    for label, model, condition in asset_blockers:
        blocking = await _count(db, model, condition)
        if blocking:
            refusals.append(f"{label} {blocking}개가 대상 작품만 쓰는 그림을 쓴다 — 그림을 지우면 그 화면이 깨진다")

    content_assets = list(
        (await db.scalars(select(Asset).where(Asset.id.in_(content_asset_ids)).order_by(Asset.id))).all()
    )
    novel_asset_ids, novel_storage_keys = await _novel_freed_assets(db, novel_ids)
    plan.asset_ids = sorted([*content_asset_ids, *novel_asset_ids])
    plan.storage_keys = sorted(
        {
            *novel_storage_keys,
            *(key for asset in content_assets for key in (asset.storage_key, *build_variant_keys(asset.storage_key))),
        }
    )

    emptied_requests = await _count(
        db,
        ImageGenerationRequest,
        ImageGenerationRequest.id.in_(select(Asset.request_id).where(Asset.id.in_(plan.asset_ids))),
        ImageGenerationRequest.status != "pending",
        ~select(Asset.id)
        .where(Asset.request_id == ImageGenerationRequest.id, Asset.id.not_in(plan.asset_ids))
        .exists(),
    )
    plan.counts = {
        "contents": len(found),
        "content_versions": len(version_ids),
        "chat_rooms": len(room_ids),
        "chat_messages": await _count(db, ChatMessage, ChatMessage.chat_room_id.in_(room_ids)),
        "novels": len(novel_ids),
        "likes": await _count(db, Like, Like.content_id.in_(found)),
        "favorites": await _count(db, Favorite, Favorite.content_id.in_(found)),
        "content_chat_participants": await _count(
            db, ContentChatParticipant, ContentChatParticipant.content_id.in_(found)
        ),
        "character_image_exposures": await _count(
            db, CharacterImageExposure, CharacterImageExposure.content_id.in_(found)
        ),
        "story_media_exposures": await _count(db, StoryMediaExposure, StoryMediaExposure.content_id.in_(found)),
        "reports": await _count(db, Report, Report.content_id.in_(found)),
        "story_ending_unlocks": await _count(
            db, StoryEndingUnlock, StoryEndingUnlock.starting_setup_entity_id.in_(setup_entity_ids)
        ),
        "assets": len(plan.asset_ids),
        "image_generation_requests": emptied_requests,
        "moderation_actions.content_id:set_null": await _count(
            db, ModerationAction, ModerationAction.content_id.in_(found)
        ),
        "notifications.content_id:set_null": await _count(db, Notification, Notification.content_id.in_(found)),
        "admin_action_logs.target_content_id:set_null": await _count(
            db, AdminActionLog, AdminActionLog.target_content_id.in_(found)
        ),
        "admin_action_logs.target_chat_room_id:set_null": await _count(
            db, AdminActionLog, AdminActionLog.target_chat_room_id.in_(room_ids)
        ),
        "admin_action_logs.target_novel_id:set_null": await _count(
            db, AdminActionLog, AdminActionLog.target_novel_id.in_(novel_ids)
        ),
        "chat_message_reports.chat_room_id:set_null": await _count(
            db, ChatMessageReport, ChatMessageReport.chat_room_id.in_(room_ids)
        ),
        "discarded_responses.chat_room_id:set_null": await _count(
            db, DiscardedResponse, DiscardedResponse.chat_room_id.in_(room_ids)
        ),
        "novels.cover_asset_id:set_null": await _count(
            db, Novel, Novel.cover_asset_id.in_(plan.asset_ids), Novel.id.not_in(novel_ids)
        ),
        "image_generation_requests.reference_asset_id:set_null": await _count(
            db, ImageGenerationRequest, ImageGenerationRequest.reference_asset_id.in_(plan.asset_ids)
        ),
    }
    targets = _Targets(
        contents=contents,
        version_ids=version_ids,
        setup_entity_ids=setup_entity_ids,
        room_ids=room_ids,
        novel_ids=novel_ids,
        content_assets=content_assets,
        novel_storage_keys=novel_storage_keys,
    )
    return plan, targets


async def build_plan(db: AsyncSession, content_ids: Sequence[uuid.UUID]) -> PurgePlan:
    """읽기만 한다. 지울 행 수·지울 그림과 저장소 키·거부 사유를 센다."""
    plan, _ = await _plan(db, content_ids)
    return plan


async def _delete(db: AsyncSession, targets: _Targets) -> list[str]:
    """계획한 행을 지운다. 소설 삭제가 내놓은 저장소 키를 돌려준다(커밋은 호출부)."""
    content_ids = [content_id for content_id, _ in targets.contents]
    await delete_chat_rooms(db, targets.room_ids)
    freed_novel_keys: list[str] = []
    await delete_novels(db, targets.novel_ids, freed_storage_keys=freed_novel_keys)

    for model in (Like, Favorite, ContentChatParticipant, CharacterImageExposure, StoryMediaExposure, Report):
        await db.execute(delete(model).where(model.content_id.in_(content_ids)))
    await db.execute(
        delete(StoryEndingUnlock).where(StoryEndingUnlock.starting_setup_entity_id.in_(targets.setup_entity_ids))
    )
    await db.execute(
        update(Content)
        .where(Content.id.in_(content_ids))
        .values(current_published_version_id=None, pinned_comment_id=None)
    )

    content_types = dict(targets.contents)
    for version_id, content_id in (
        await db.execute(
            select(ContentVersion.id, ContentVersion.content_id)
            .where(ContentVersion.id.in_(targets.version_ids))
            .order_by(ContentVersion.id)
        )
    ).tuples():
        await _delete_draft_children(db, content_types[content_id], version_id)
    for detail_model in (CharacterVersionDetail, StoryVersionDetail):
        await db.execute(delete(detail_model).where(detail_model.content_version_id.in_(targets.version_ids)))
    await db.execute(delete(ContentVersion).where(ContentVersion.id.in_(targets.version_ids)))
    await db.execute(delete(Content).where(Content.id.in_(content_ids)))

    asset_ids = [asset.id for asset in targets.content_assets]
    await db.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    await db.flush()
    await delete_emptied_generation_requests(
        db, {asset.request_id for asset in targets.content_assets if asset.request_id is not None}
    )
    return freed_novel_keys


async def apply_purge(
    db: AsyncSession, content_ids: Sequence[uuid.UUID], *, expect_contents: int, keys_out: Path
) -> PurgePlan:
    """대상 작품 행을 id 순으로 잠그고 계획을 다시 세운 뒤, 거부 사유가 없으면 지우고 커밋한다. 거부면 `PurgeRefused` 이고
    아무것도 쓰지 않으며 키 파일도 만들지 않는다(롤백은 세션을 닫는 호출부가 한다).

    키 파일은 삭제가 끝난 뒤, 커밋 전에 쓴다. 삭제 도중 실패하면 행은 롤백돼 그대로인데 키 파일이 남아 있으면 운영자가 그
    파일로 살아 있는 그림을 지울 수 있어서다. 커밋이 실패하면 같은 이유로 키 파일을 지운다."""
    if keys_out.exists():  # noqa: ASYNC240 — 운영자가 한 번 돌리는 CLI 라 이벤트 루프를 막아도 기다릴 다른 일이 없다
        raise FileExistsError(f"{keys_out} 가 이미 있다 — 앞선 적용의 키 목록을 덮지 않는다")
    ids = sorted(set(content_ids))
    await db.execute(select(Content.id).where(Content.id.in_(ids)).order_by(Content.id).with_for_update())
    plan, targets = await _plan(db, ids)
    if expect_contents != len(ids):
        plan.refusals.append(f"--expect-contents {expect_contents} 가 입력 작품 수 {len(ids)} 와 다르다")
    if plan.refusals:
        raise PurgeRefused(plan)

    freed_novel_keys = await _delete(db, targets)
    if sorted(set(freed_novel_keys)) != targets.novel_storage_keys:
        raise RuntimeError("소설 삭제가 지운 삽화 키가 계획과 다르다 — 커밋하지 않는다")
    with keys_out.open("x", encoding="utf-8") as file:
        json.dump(plan.storage_keys, file, ensure_ascii=False, indent=0)
    try:
        await db.commit()
    except BaseException:
        keys_out.unlink(missing_ok=True)  # noqa: ASYNC240 — 위와 같다
        raise
    return plan


def delete_objects(keys: Sequence[str], *, apply: bool, delete_fn: Callable[[str], None]) -> dict[str, int]:
    """저장소 키를 하나씩 지운다. 하나가 실패해도 나머지를 지운다 — 행은 이미 사라져 다시 시도할 근거가 이 파일뿐이라, 멈추면
    실패한 키 뒤의 그림이 전부 남는다. 실패한 키는 표준 오류에 남긴다."""
    if not apply:
        return {"planned": len(keys)}
    deleted = failed = 0
    for key in keys:
        try:
            delete_fn(key)
        except Exception as exc:
            failed += 1
            print(f"지우지 못했다: {key} ({type(exc).__name__})", file=sys.stderr)
        else:
            deleted += 1
    return {"deleted": deleted, "failed": failed}


def format_plan(plan: PurgePlan) -> str:
    lines = [f"대상 작품 {len(plan.content_ids)}개"]
    lines += [f"  {content_id}" for content_id in plan.content_ids]
    if plan.missing_ids:
        lines.append(f"DB 에 없는 id {len(plan.missing_ids)}개")
        lines += [f"  {missing_id}" for missing_id in plan.missing_ids]
    lines.append("행 수(이름 끝이 :set_null 이면 행은 남고 그 칸만 빈다)")
    width = max((len(name) for name in plan.counts), default=0)
    lines += [f"  {name.ljust(width)}  {count}" for name, count in plan.counts.items()]
    lines.append(f"지울 그림 {len(plan.asset_ids)}개, 저장소 키 {len(plan.storage_keys)}개")
    if plan.refusals:
        lines.append("거부 사유")
        lines += [f"  - {reason}" for reason in plan.refusals]
    return "\n".join(lines)


def read_ids(path: Path) -> list[uuid.UUID]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [uuid.UUID(line) for line in lines if line and not line.startswith("#")]


async def _run(args: argparse.Namespace) -> int:
    from api.db.session import async_session_factory

    ids = read_ids(args.ids_file)
    async with async_session_factory() as session:
        if args.command == "plan":
            planned = await build_plan(session, ids)
            print(format_plan(planned))
            return 2 if planned.refusals else 0
        try:
            planned = await apply_purge(session, ids, expect_contents=args.expect_contents, keys_out=args.keys_out)
        except PurgeRefused as refused:
            print(format_plan(refused.plan))
            print("거부했다 — 아무것도 쓰지 않았다", file=sys.stderr)
            return 2
        print(format_plan(planned))
        print(f"적용했다. 저장소 키 {len(planned.storage_keys)}개를 {args.keys_out} 에 남겼다 — 다음은 delete-objects")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan", help="지울 행 수와 거부 사유만 보여 준다(쓰기 없음)")
    plan_parser.add_argument("--ids-file", type=Path, required=True)
    apply_parser = commands.add_parser("apply", help="한 트랜잭션으로 지우고 저장소 키를 파일에 남긴다")
    apply_parser.add_argument("--ids-file", type=Path, required=True)
    apply_parser.add_argument(
        "--expect-contents", type=int, required=True, help="ids 파일의 작품 수 — 다른 목록을 지우지 않게 따로 적는다"
    )
    apply_parser.add_argument("--keys-out", type=Path, required=True, help="지울 저장소 키를 남길 새 파일")
    objects_parser = commands.add_parser("delete-objects", help="apply 가 남긴 키 파일로 저장소 파일을 지운다")
    objects_parser.add_argument("--keys-file", type=Path, required=True)
    objects_parser.add_argument("--apply", action="store_true", help="붙여야 실제로 지운다(기본은 키 수만 보여 준다)")
    args = parser.parse_args(argv)

    if args.command == "delete-objects":
        keys = json.loads(args.keys_file.read_text(encoding="utf-8"))
        result = delete_objects(keys, apply=args.apply, delete_fn=delete_object)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("failed") else 0
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
