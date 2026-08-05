"""로컬 개발용 샘플 데이터 시드.

발행(published) 상태의 캐릭터 1개("미아")를 넣어 홈 목록에 뜨고 바로 채팅할 수 있게 한다.
빌더로 직접 만들면 이미지 업로드/발행 검증까지 거쳐야 하는데, 그 과정을 건너뛰기 위한 스크립트다.

    cd apps/api && uv run --env-file .env python scripts/seed_dev.py

- 썸네일용 placeholder 이미지를 moto(S3)에 업로드한다(moto 가 떠 있어야 함, 없으면 경고만 하고 계속).
- DB 로우는 고정 UUID 로 upsert 한다(`session.merge`): 없으면 넣고, 있으면 이 파일에 적힌 값으로
  덮어쓴다. 그래서 미아의 프롬프트나 소개 문구를 고친 뒤 다시 돌리면 그대로 반영된다 —
  이 스크립트가 시드 데이터의 단일 진실 공급원이다.
- dev DB 는 계속 쌓이는 작업공간이므로, 이 스크립트는 자기가 소유한 고정 UUID 로우만 건드린다.
  직접 만든 대화방·업로드한 자산 등 그 밖의 데이터는 절대 지우지 않는다.
- moto 는 인메모리라 재기동 시 이미지가 사라지므로, 이미지 업로드는 DB 상태와 무관하게 매번 수행한다.
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
from api.core.security import hash_password  # noqa: E402
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
from seed_content.ids import SEED_AUTHOR_USER_ID  # noqa: E402

# 고정 UUID (재실행 시 중복 방지). 실사용자 UUID 와 겹치지 않도록 5eed... 프리픽스 사용.
# 시드 콘텐츠 전체의 작가 계정. 이 UUID 는 절대 바꾸지 않는다 — 기존 시드 콘텐츠의
# creator_user_id 가 전부 이 값을 참조한다. 빌더로 시드 콘텐츠를 열어보려면 로그인이
# 필요하므로 독자 계정과 동일하게 비밀번호를 부여한다(작가/독자 계정은 분리 유지).
USER_ID = SEED_AUTHOR_USER_ID
SEED_AUTHOR_EMAIL = "seed-creator@example.com"
SEED_AUTHOR_PASSWORD = "password1234"
# 비밀번호로 바로 로그인 가능한 테스트 계정 (Google 설정 없이 채팅 흐름 확인용).
TEST_USER_ID = uuid.UUID("5eed0000-0000-4000-8000-0000000000d1")
TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "password1234"
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

    # 2) DB 로우 (고정 UUID upsert)
    #
    # 이 코드베이스는 `relationship()` 을 선언하지 않으므로(순수 FK 컬럼만) 참조 순서를 직접
    # 지킨다 — 부모를 merge 한 뒤 `flush()` 로 실제 INSERT 를 내보내고 나서 자식으로 넘어간다.
    async with async_session_factory() as session:
        now = datetime.now(UTC)

        # 2a) 비밀번호로 바로 로그인 가능한 테스트 계정 (성인 + 이메일 인증 완료 상태).
        await session.merge(
            User(
                id=TEST_USER_ID,
                email=TEST_EMAIL,
                password_hash=hash_password(TEST_PASSWORD),
                google_sub=None,
                nickname="테스트",
                birth_date=date(1995, 1, 1),
                terms_agreed_at=now,
                privacy_agreed_at=now,
                email_verified_at=now,
            )
        )

        # 2b) 발행된 샘플 캐릭터와 그 크리에이터.
        await session.merge(
            User(
                id=USER_ID,
                email=SEED_AUTHOR_EMAIL,
                password_hash=hash_password(SEED_AUTHOR_PASSWORD),
                google_sub=None,
                nickname="시드 작가",
                birth_date=date(1995, 1, 1),
                terms_agreed_at=now,
                privacy_agreed_at=now,
                email_verified_at=now,
            )
        )
        await session.flush()  # assets.owner_user_id -> users.id

        await session.merge(
            Asset(
                id=ASSET_ID,
                owner_user_id=USER_ID,
                storage_key=THUMBNAIL_KEY,
                kind=AssetKind.THUMBNAIL,
                status=AssetStatus.READY,
            )
        )
        # contents ↔ content_versions 순환 FK: `current_published_version_id` 를 생성자에
        # 아예 넘기지 않는다. merge 는 생성자에서 실제로 설정한 속성만 복사하므로, 최초
        # INSERT 때는 NULL(아직 버전 행이 없음)로 들어가고 재실행 때는 기존 값이 그대로
        # 보존된다 — 발행 포인터는 버전을 flush 한 뒤 아래에서 건다. `created_at` 같은
        # server_default 컬럼이 재실행 때 덮어써지지 않는 것도 같은 이유다.
        content = await session.merge(
            Content(
                id=CONTENT_ID,
                type=ContentType.CHARACTER,
                creator_user_id=USER_ID,
                genre_id=GENRE_ROMANCE,
                target=ContentTarget.ALL,
                hashtags=["데모", "샘플"],
                visibility=ContentVisibility.PUBLIC,
                moderation_status=ModerationStatus.NORMAL,
            )
        )
        await session.flush()  # content_versions.content_id -> contents.id

        await session.merge(
            ContentVersion(
                id=VERSION_ID,
                content_id=CONTENT_ID,
                version_number=1,
                published_at=now,
                detail_description="로컬 개발용 샘플 캐릭터입니다.",
            )
        )
        await session.flush()  # character_version_details / 발행 포인터가 이 행을 참조

        content.current_published_version_id = VERSION_ID
        await session.merge(
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
        await session.commit()
        print(f"  ✓ 테스트 로그인 계정(독자): {TEST_EMAIL} / {TEST_PASSWORD}")
        print(f"  ✓ 시드 작가 계정: {SEED_AUTHOR_EMAIL} / {SEED_AUTHOR_PASSWORD}")
        print("  ✓ 발행된 샘플 캐릭터 '미아' 시드 완료")


if __name__ == "__main__":
    asyncio.run(main())
