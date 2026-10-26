"""로컬 개발용 샘플 데이터 시드.

테스트 로그인 계정(독자)과 시드 작가 계정을 만들고, `seed_content/data/` 의 튜토리얼 스토리·캐릭터
JSON 을 그 작가의 발행 작품으로 업서트해 홈 목록에 뜨고 바로 채팅할 수 있게 한다. 빌더로 직접
만들면 이미지 업로드/발행 검증까지 거쳐야 하는데, 그 과정을 건너뛰기 위한 스크립트다.

    cd apps/api && uv run --env-file .env python scripts/seed_dev.py

- 썸네일 이미지를 moto(S3)에 업로드한다(moto 가 떠 있어야 함, 없으면 경고만 하고 계속).
- DB 로우는 고정 UUID 로 upsert 한다: 없으면 넣고, 있으면 데이터 파일에 적힌 값으로 덮어쓴다.
  그래서 시드 JSON 을 고친 뒤 다시 돌리면 그대로 반영된다 — 이 스크립트가 시드 데이터의 단일 진실
  공급원이다.
- dev DB 는 계속 쌓이는 작업공간이므로, 이 스크립트는 자기가 소유한 고정 UUID 로우만 건드린다.
  직접 만든 대화방·업로드한 자산 등 그 밖의 데이터는 절대 지우지 않는다.
- moto 는 인메모리라 재기동 시 이미지가 사라지므로, 이미지 업로드는 DB 상태와 무관하게 매번 수행한다.
"""

import asyncio
import os
import uuid
from datetime import UTC, date, datetime

# boto3(api.core.s3 모듈 전역 클라이언트)는 URL 서명에도 자격증명이 "존재"해야 하고 moto
# 엔드포인트를 알아야 한다. `--env-file .env` 로 실행하면 이미 채워져 있고, 아니면 여기서 기본값.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:5001")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.security import hash_password
from api.db.models.auth import User
from api.db.models.content import Genre
from api.db.models.media import AssetKind
from api.db.session import async_session_factory
from replay import local_db as replay_local_db
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.images import ensure_asset
from seed_content.loader import load_all_characters, load_all_stories
from seed_content.upsert import upsert_character, upsert_story

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


async def seed_content_files(session: AsyncSession) -> None:
    """`seed_content/data/` 의 스토리·캐릭터 JSON 을 전부 발행 상태로 업서트한다.

    콘텐츠 대표 썸네일은 자동저장 로직이 소유하지 않는 필드라 여기서 `ensure_asset` 으로
    만들어 payload 에 주입한다(상황별 이미지는 `upsert_character` 가 직접 만든다).
    장르명은 이미지가 없을 때 쓰는 목업 색을 장르별로 갈라놓기 위한 것뿐이다.

    데이터 파일이나 발행 검증이 잘못됐으면 그 자리에서 죽는다 — 시드가 콘텐츠의 단일 진실
    공급원이라 절반만 들어간 상태로 넘어가면 안 된다.
    """
    genre_names = {
        genre_id: name
        for genre_id, name in (await session.execute(select(Genre.id, Genre.name))).all()
    }

    for story in load_all_stories():
        genre_id = story.payload.genre_id
        thumbnail_asset_id = await ensure_asset(
            session,
            story.slug,
            AssetKind.THUMBNAIL,
            genre_names.get(genre_id) if genre_id is not None else None,
        )
        await session.flush()  # story_version_details.thumbnail_asset_id -> assets.id
        await upsert_story(
            session,
            story.slug,
            story.payload.model_copy(update={"thumbnail_asset_id": thumbnail_asset_id}),
        )
        print(f"  ✓ 스토리 시드: {story.slug} — 「{story.payload.name}」")

    for character in load_all_characters():
        genre_id = character.payload.genre_id
        thumbnail_asset_id = await ensure_asset(
            session,
            character.slug,
            AssetKind.THUMBNAIL,
            genre_names.get(genre_id) if genre_id is not None else None,
        )
        await session.flush()  # character_version_details.thumbnail_asset_id -> assets.id
        await upsert_character(
            session,
            character.slug,
            character.payload.model_copy(update={"thumbnail_asset_id": thumbnail_asset_id}),
        )
        print(f"  ✓ 캐릭터 시드: {character.slug} — {character.payload.name}")


def ensure_local_database(database_url: str) -> None:
    """로컬 DB 가 아니면 `SystemExit`. 운영에서 이 스크립트를 돌리면 테스트 계정을 만들고, 이미지가 없으면 목업이 실제
    아트를 덮고, 어드민 조치와 빌더 편집을 시드 값으로 되돌린다 — 그걸 막는 장치가 사람의 기억뿐이었다. 허용 목록은
    측정 도구와 같은 것을 쓴다."""
    replay_local_db.ensure_local_database(database_url, tool="seed_dev.py")


def ensure_local_object_store(endpoint_url: str | None) -> None:
    """S3 엔드포인트가 로컬(DB 와 같은 허용 목록)이 아니면 `SystemExit`. 엔드포인트가 없으면 boto3 가 실제 AWS 로
    나가므로 그것도 거부한다. DB 만 로컬이고 저장소가 운영 버킷이면 목업 이미지가 운영 객체 키를 덮어쓴다.
    아직 아무것도 검사하지 않는다."""


async def main() -> None:
    ensure_local_database(settings.database_url)
    ensure_local_object_store(settings.s3_endpoint_url)

    # 이 코드베이스는 `relationship()` 을 선언하지 않으므로(순수 FK 컬럼만) 참조 순서를 직접
    # 지킨다 — 부모를 merge 한 뒤 `flush()` 로 실제 INSERT 를 내보내고 나서 자식으로 넘어간다.
    async with async_session_factory() as session:
        now = datetime.now(UTC)

        # 비밀번호로 바로 로그인 가능한 테스트 계정 (성인 + 이메일 인증 완료 상태).
        await session.merge(
            User(
                id=TEST_USER_ID,
                email=TEST_EMAIL,
                password_hash=await hash_password(TEST_PASSWORD),
                google_sub=None,
                nickname="테스트",
                birth_date=date(1995, 1, 1),
                terms_agreed_at=now,
                privacy_agreed_at=now,
                email_verified_at=now,
            )
        )

        # 시드 콘텐츠의 작가.
        await session.merge(
            User(
                id=USER_ID,
                email=SEED_AUTHOR_EMAIL,
                password_hash=await hash_password(SEED_AUTHOR_PASSWORD),
                google_sub=None,
                nickname="시드 작가",
                birth_date=date(1995, 1, 1),
                terms_agreed_at=now,
                privacy_agreed_at=now,
                email_verified_at=now,
            )
        )
        await session.flush()  # assets.owner_user_id -> users.id

        await seed_content_files(session)
        await session.commit()
        print(f"  ✓ 테스트 로그인 계정(독자): {TEST_EMAIL} / {TEST_PASSWORD}")
        print(f"  ✓ 시드 작가 계정: {SEED_AUTHOR_EMAIL} / {SEED_AUTHOR_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
