"""로컬 개발용 샘플 데이터 시드.

발행(published) 상태의 캐릭터 1개("미아")를 넣어 홈 목록에 뜨고 바로 채팅할 수 있게 한다.
빌더로 직접 만들면 이미지 업로드/발행 검증까지 거쳐야 하는데, 그 과정을 건너뛰기 위한 스크립트다.

    cd apps/api && uv run --env-file .env python scripts/seed_dev.py

- 썸네일용 placeholder 이미지를 moto(S3)에 업로드한다(moto 가 떠 있어야 함, 없으면 경고만 하고 계속).
- DB 로우는 고정 UUID 로 idempotent 하게 넣는다(이미 있으면 건너뜀). moto 는 인메모리라
  재기동 시 이미지가 사라지므로, 이미지 업로드는 DB 존재 여부와 무관하게 매번 다시 수행한다.
"""

import asyncio
import io
import os
import uuid
from datetime import UTC, date, datetime

# boto3(api.core.s3 모듈 전역 클라이언트)는 URL 서명에도 자격증명이 "존재"해야 하고 moto
# 엔드포인트를 알아야 한다. `--env-file .env` 로 실행하면 이미 채워져 있고, 아니면 여기서 기본값.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:5001")

from PIL import Image  # noqa: E402

from api.core.s3 import build_object_key, upload_object  # noqa: E402
from api.db.models.auth import User  # noqa: E402
from api.db.models.character import CharacterVersionDetail  # noqa: E402
from api.db.models.content import (  # noqa: E402
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus  # noqa: E402
from api.db.session import async_session_factory  # noqa: E402

# 고정 UUID (재실행 시 중복 방지). 실사용자 UUID 와 겹치지 않도록 5eed... 프리픽스 사용.
USER_ID = uuid.UUID("5eed0000-0000-4000-8000-000000000001")
ASSET_ID = uuid.UUID("5eed0000-0000-4000-8000-0000000000a5")
CONTENT_ID = uuid.UUID("5eed0000-0000-4000-8000-0000000000c0")
VERSION_ID = uuid.UUID("5eed0000-0000-4000-8000-0000000000e0")
# 장르 '로맨스' — 마이그레이션(91a008760f4a)이 시드한 고정 UUID.
GENRE_ROMANCE = uuid.UUID("b8a1e6b0-1c1a-4b8a-9b0a-000000000001")

THUMBNAIL_KEY = build_object_key("thumbnail", ASSET_ID, "image/png")


def _placeholder_png() -> bytes:
    """480x720 단색 다크 썸네일 (Pillow, 폰트 의존 없음)."""
    image = Image.new("RGB", (480, 720), (32, 32, 36))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def main() -> None:
    # 1) 썸네일 이미지 업로드 (moto 없으면 경고만 — 썸네일만 깨지고 채팅은 됨)
    try:
        upload_object(THUMBNAIL_KEY, _placeholder_png(), "image/png")
        print(f"  ✓ placeholder 썸네일 업로드: {THUMBNAIL_KEY}")
    except Exception as exc:  # noqa: BLE001 - moto 미기동 등 어떤 실패든 시드 자체는 계속
        print(f"  ! 썸네일 업로드 건너뜀 ({exc!r}) — moto 기동 후 seed 재실행하면 채워짐")

    # 2) DB 로우 (idempotent)
    async with async_session_factory() as session:
        if await session.get(Content, CONTENT_ID) is not None:
            print("  = 샘플 캐릭터가 이미 있음 → DB 삽입 건너뜀")
            return

        now = datetime.now(UTC)
        session.add(
            User(
                id=USER_ID,
                email="seed-creator@example.com",
                password_hash=None,
                google_sub=None,
                nickname="샘플 크리에이터",
                birth_date=date(1995, 1, 1),
                terms_agreed_at=now,
                privacy_agreed_at=now,
                email_verified_at=now,
            )
        )
        session.add(
            Asset(
                id=ASSET_ID,
                owner_user_id=USER_ID,
                storage_key=THUMBNAIL_KEY,
                kind=AssetKind.THUMBNAIL,
                status=AssetStatus.READY,
            )
        )
        content = Content(
            id=CONTENT_ID,
            type=ContentType.CHARACTER,
            creator_user_id=USER_ID,
            genre_id=GENRE_ROMANCE,
            target=ContentTarget.ALL,
            hashtags=["데모", "샘플"],
            visibility=ContentVisibility.PUBLIC,
            moderation_status=ModerationStatus.NORMAL,
            current_published_version_id=None,
        )
        session.add(content)
        session.add(
            ContentVersion(
                id=VERSION_ID,
                content_id=CONTENT_ID,
                version_number=1,
                published_at=now,
                detail_description="로컬 개발용 샘플 캐릭터입니다.",
            )
        )
        await session.flush()
        session.add(
            CharacterVersionDetail(
                content_version_id=VERSION_ID,
                name="미아",
                one_liner="불 꺼진 방, 당신 곁을 지키는 다정한 목소리",
                thumbnail_asset_id=ASSET_ID,
                intro="(조용히 곁에 앉으며) 아직 안 잤구나. 오늘 하루는 어땠어? 천천히 말해줘, 다 들어줄게.",
                example_dialogues=[
                    {
                        "userLine": "오늘 좀 힘들었어",
                        "characterLine": "그랬구나… 많이 지쳤겠다. 여기 앉아서 잠깐 쉬어. 무슨 일이 있었는지 말해줄래?",
                    }
                ],
                character_prompt=(
                    "너는 '미아'라는 이름의 캐릭터다. 늦은 밤 사용자 곁을 지키는 다정하고 차분한 친구다. "
                    "항상 한국어로, 따뜻하고 나직한 말투로 대화한다. 사용자의 감정을 먼저 살피고 공감하며, "
                    "짧고 부드럽게 반응한다. 설교하거나 판단하지 않는다."
                ),
                playguide=None,
            )
        )
        # contents ↔ content_versions 순환 FK: 버전이 flush 된 뒤에 발행 포인터를 건다.
        content.current_published_version_id = VERSION_ID
        await session.commit()
        print("  ✓ 발행된 샘플 캐릭터 '미아' 시드 완료")


if __name__ == "__main__":
    asyncio.run(main())
