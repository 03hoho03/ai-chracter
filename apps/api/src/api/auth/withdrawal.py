"""회원 탈퇴 파기. `DELETE /me` 와 provider 쪽 연결 끊기 알림처럼 탈퇴를 일으키는 여러 경로가 같은
파기를 하도록 한 곳에 둔다. 라우터를 import 하지 않아 어느 라우터에서 불러도 순환이 생기지 않는다.

요청에 묶인 일(현재 세션 삭제·쿠키 지우기)과 세션 일괄 폐기는 커밋 뒤 호출자가 한다.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from botocore.exceptions import BotoCoreError, ClientError

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.assets.router import collect_asset_usages
from api.chat.room_deletion import delete_chat_rooms
from api.comments.actions import erase_user_comments, lock_withdrawal_contents
from api.core import clover
from api.core.s3 import build_thumbnail_key, delete_object
from api.core.security import hash_withdrawn_email
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User, WithdrawnEmail
from api.db.models.chat import ChatMessageReport, ChatRoom
from api.db.models.content import Content, ContentVisibility
from api.db.models.inquiry import Inquiry
from api.db.models.media import Asset, AssetKind, ImageGenerationRequest
from api.db.models.persona import UserPersona

logger = logging.getLogger(__name__)

StorageObjectDeleter = Callable[[str], Awaitable[None]]


async def delete_storage_object_now(storage_key: str) -> None:
    """오브젝트 스토리지(R2)에서 그 자리에서 지운다. `DELETE /me` 가 쓰는 기본 동작이다."""
    await run_in_threadpool(delete_object, storage_key)


async def delete_storage_objects_later(storage_keys: list[str]) -> None:
    """파기를 커밋한 뒤 백그라운드에서 모아 둔 오브젝트를 지운다. 응답이 이미 나가 재시도할 주체가
    없으므로 하나가 실패해도 나머지는 계속 지우고, 실패는 고아 오브젝트로 남으니 기록한다."""
    for storage_key in storage_keys:
        try:
            await delete_storage_object_now(storage_key)
        except (BotoCoreError, ClientError) as exc:
            logger.warning("storage delete after account erase failed: %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="s3")


async def erase_account(
    db: AsyncSession, user: User, *, delete_storage_object: StorageObjectDeleter
) -> None:
    """탈퇴 파기를 수행하고 커밋한다.

    호출자가 `user` 행을 FOR UPDATE 로 잠그고 탈퇴·정지 여부를 판정한 뒤 부른다 —
    `lock_active_user` 는 정지 회원에게 403 을 던지는 요청 전용 검사라, 요청이 아닌 경로가 같은
    파기를 쓰려면 잠금과 판정을 호출자에게 남겨야 한다.

    오브젝트 스토리지 삭제는 `delete_storage_object` 로 받는다. 호출 수가 회원이 만든 이미지
    수에 비례하고 상한이 없어서, 응답 시간 제한이 있는 경로는 키만 모아 두었다가 커밋 뒤
    백그라운드에서 지울 수 있게 하려는 것이다. 그 경우 DB 행이 먼저 사라지므로 나중 삭제가
    실패하면 오브젝트가 고아로 남는다 — 그 경로가 감수할 몫이다. `delete_storage_object_now`
    를 넘기면 지금까지의 순서(오브젝트를 먼저 지우고 DB 행을 지운다) 그대로다.
    """
    user_id = user.id
    await lock_withdrawal_contents(db, user_id)
    now = datetime.now(UTC)
    original_email = user.email

    # 프로필 이미지 R2 오브젝트를 지운다 —
    # core/s3.py의 delete_object·assets/router.py의 호출 선례(:116,133,382)를 따른다.
    if user.profile_image_asset_id is not None:
        asset = await db.get(Asset, user.profile_image_asset_id)
        if asset is not None:
            await delete_storage_object(asset.storage_key)
            # assets/router.py:124의 불변식 — READY 이미지 asset은 항상
            # `{key}_thumb.webp` 변형을 갖는다. 프로필 이미지도 그 공용 업로드
            # 경로(assets/router.py의 complete_asset_upload)를 타므로 원본만
            # 지우면 썸네일이 R2에 고아로 남는다.
            await delete_storage_object(build_thumbnail_key(asset.storage_key))

    user.deleted_at = now
    # users.email이 unique=True, nullable=False라
    # NULL을 못 쓴다 — 복원 불가능한 자리표시자로 유일성을 유지한다.
    user.email = f"withdrawn:{user_id}"
    user.password_hash = None
    user.nickname = None
    user.bio = None
    user.birth_date = None
    # 파기하지 않으면 구글 가입자는 google_sub 직접
    # 매치(google_callback)에 영구히 걸려, 이메일 가입자와 달리 1년이 지나도 재가입이 안 열린다.
    user.google_sub = None
    # 카카오도 같다 — 지우지 않으면 탈퇴한 카카오 계정이 콜백에서 기존 회원으로 잡혀 영구히 막힌다.
    user.kakao_id = None
    user.profile_image_asset_id = None
    # 아래 프로필 DELETE 전에 기본 참조를 끊는다(같은 flush에 실린다).
    user.default_persona_id = None

    # 평문 이메일 대신 키 있는 HMAC 한 행을 남긴다.
    # 같은 이메일이 만료 후 재사용됐다가 다시 탈퇴할 수 있어 PK 충돌이면 갱신한다.
    email_hmac = hash_withdrawn_email(original_email)
    withdrawn_row = await db.scalar(
        select(WithdrawnEmail).where(WithdrawnEmail.email_hmac == email_hmac)
    )
    if withdrawn_row is not None:
        withdrawn_row.withdrawn_at = now
    else:
        db.add(WithdrawnEmail(email_hmac=email_hmac, withdrawn_at=now))

    await db.execute(
        update(Content)
        .where(Content.creator_user_id == user_id)
        .values(visibility=ContentVisibility.PRIVATE)
    )
    await erase_user_comments(db, user_id, now)

    # 채팅 응답 신고의 증거는 신고자 본인의 대화 사본이다(신고자 = 방 소유자). 아래에서 그 대화를
    # 지우는데 사본만 90일 남기면 탈퇴로 대화를 파기한다는 약속과 어긋나므로 같이 비운다. 신고자
    # 메모도 대화를 옮겨 적을 수 있는 자유 입력이라 함께 비운다. 신고 사유·처리 상태·시각은 남긴다.
    # 방만 지웠을 때는 비우지 않는다(신고가 처리될 시간을 둔다).
    await db.execute(
        update(ChatMessageReport)
        .where(ChatMessageReport.reporter_user_id == user_id, ChatMessageReport.evidence_purged_at.is_(None))
        .values(evidence_response=None, evidence_user_message=None, note=None, evidence_purged_at=now)
    )
    room_ids = (await db.scalars(select(ChatRoom.id).where(ChatRoom.user_id == user_id))).all()
    await delete_chat_rooms(db, room_ids)

    # 위 `profile_image_asset_id = None` 대입이 DB에 반영된
    # 뒤라야 아래 `DELETE FROM assets`가 FK 위반을 내지 않는다. autoflush에 기대지 않는다.
    await db.flush()

    # 대화 프로필을 지운다. 참조하는 쪽(방은 위에서 DELETE,
    # `default_persona_id`는 위 flush로 NULL)이 먼저 끊겨 있어야 FK 위반이 나지 않는다.
    await db.execute(delete(UserPersona).where(UserPersona.user_id == user_id))

    # 탈퇴한 유저의 GENERATED asset과 요청 행을
    # "이미지와 같은 수명"으로 파기한다. profile_image_asset_id는 위에서 이미 None으로
    # 끊었으므로(프로필 이미지 삭제 블록) 여기서 지워도 프로필 FK가 안전하다.
    generated_assets = (
        await db.scalars(
            select(Asset).where(Asset.owner_user_id == user_id, Asset.kind == AssetKind.GENERATED)
        )
    ).all()
    if generated_assets:
        asset_ids = [asset.id for asset in generated_assets]
        usages_by_asset = await collect_asset_usages(db, asset_ids)
        # collect_asset_usages는 캐릭터/스토리 썸네일·상황별 이미지·미디어 북 칸만 본다 —
        # 문의 첨부(inquiries.attachment_asset_id)는 보지 않는다. 문의는 소유자만
        # 검사하고 kind를 안 보며(inquiry/router.py) 탈퇴해도 삭제되지 않으므로,
        # 제외하지 않으면 FK 위반으로 탈퇴 전체가 500으로 죽는다.
        inquiry_asset_ids = set(
            (
                await db.scalars(
                    select(Inquiry.attachment_asset_id).where(
                        Inquiry.attachment_asset_id.in_(asset_ids)
                    )
                )
            ).all()
        )

        deletable_assets = [
            asset
            for asset in generated_assets
            if not usages_by_asset.get(asset.id) and asset.id not in inquiry_asset_ids
        ]
        deletable_ids = {asset.id for asset in deletable_assets}
        for asset in deletable_assets:
            # S3를 먼저 지운다 — 실패하면 DB 행이 남아 재시도가 가능하다
            # (assets/router.py의 delete_generated_image와 같은 이유).
            await delete_storage_object(asset.storage_key)
            await delete_storage_object(build_thumbnail_key(asset.storage_key))
            await db.delete(asset)

        # 요청 행은 asset이 하나도 안 남은 것만 지운다. 남은 asset을 가진 요청 행과,
        # 애초에 asset이 없던 요청 행(차단·실패 — 90일 뒤 지우는 `purge_image_requests` 크론의 몫)은 남긴다. 이 유저의
        # GENERATED asset을 전부 조회했으므로(generated_assets), 다른 유저의 asset이
        # 같은 요청 행을 참조할 수 없어(요청 행과 asset은 항상 같은 소유자) 이 목록만으로
        # "남은 asset이 있는가"를 판단할 수 있다.
        surviving_request_ids = {
            asset.request_id
            for asset in generated_assets
            if asset.id not in deletable_ids and asset.request_id is not None
        }
        emptied_request_ids = {
            asset.request_id for asset in deletable_assets if asset.request_id is not None
        } - surviving_request_ids
        if emptied_request_ids:
            # assets.request_id FK 때문에 asset을 먼저 지우고 요청 행을 지워야 한다 —
            # flush로 위 db.delete(asset)들을 먼저 반영한다.
            await db.flush()
            await db.execute(
                delete(ImageGenerationRequest).where(
                    ImageGenerationRequest.id.in_(emptied_request_ids)
                )
            )

    # 잔액은 0으로 소멸시키고 **원장은 남긴다**. 탈퇴는 soft
    # delete라 `users` 행이 그대로 남으므로, 한 줄을 안 쓰면 "아무것도 안 함"이 기본값이고
    # 잔액이 그대로 살아 있게 된다.
    # 🔴 `user.clover_balance`를 넘기지 않는다. 그 값은 이 함수 초입에서 로드된 것이고 위의
    # 삭제들을 거치는 동안 다른 탭의 차감이 커밋될 수 있어 **낡았을 수 있다** — 낡은 값으로
    # `spend`를 부르면 조건부 가드에 걸려 아무것도 안 지워진 채 204가 나간다.
    # `burn_all`은 금액을 받지 않고 자기가 다시 읽어 0으로 덮는다. 잔액 0이면 원장 행도 없다.
    # 🔴 `core/clover.py`의 자기-트랜잭션 래퍼가 아니라 **호출자 세션**을 쓴다.
    # 그래야 소멸이 아래 `db.commit()` 하나에 얹혀 탈퇴 전체와
    # 같이 커밋되거나 같이 롤백된다 — 갈라 놓으면 "탈퇴는 실패했는데 잔액만 사라진" 상태가 생긴다.
    await clover.burn_all(db, user_id=user_id)

    await db.commit()
