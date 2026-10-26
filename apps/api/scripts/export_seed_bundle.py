"""운영 작품을 비공개 시드 묶음(`seed_content/private/`)으로 읽기 전용으로 내보낸다.

운영 api 활성 컨테이너 안에서 돈다(앱 코드·DB·저장소 접근은 그 컨테이너의 env):

    python -u scripts/export_seed_bundle.py --map /tmp/map.txt --out /tmp/seed-bundle.tar.gz

`--map` 은 한 줄에 `<콘텐츠 uuid> <시드 slug>` 이고 빈 줄과 `#` 로 시작하는 줄은 건너뛴다. 조감독·민유나는 측정 도구가
기본값으로 쓰는 튜토리얼 slug(`tutorial-filmclub`·`tutorial-filmclub-yuna`)를 이어받는다.

묶음은 로더(`seed_content/loader.py`)가 읽는 꼴 그대로다 — `stories/{slug}.json`·`characters/{slug}.json`(빌더 초안
응답을 시드 입력 모델이 받는 camelCase 로, 발행본이 없으면 초안을 담고 최상위 `seedPublished: false`), `images/`(대표
이미지·미디어 북 칸·상황별 이미지 원본 바이트), `manifest.json`(작품 slug 별로 어느 파일이 어느 그림인지와 원래 종류·형식·
프레임 수·크롭). tar.gz 안에는 최상위 폴더가 없어 로컬에서 `tar -xzf … -C apps/api/scripts/seed_content/private/` 로 푼다.

DB 는 읽기 전용 트랜잭션으로만 읽는다 — 실수로 쓰기가 섞여도 DB 가 거부한다. 표준 출력에는 작품 수·이미지 수·바이트·
sha256 만 남긴다. 작품 이름이나 본문은 컨테이너 로그에 남기지 않는다.
"""

import argparse
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

# 작품 하나를 직렬화하는 경로다. 테스트가 이 이름 자리를 감싸 직렬화 시점의 트랜잭션 상태를 본다.
from api.content.router import _character_draft_response, _story_draft_response
from api.core.s3 import download_object

# 안전장치가 묶음 만들기를 거부했을 때의 종료 코드 — 묶음 파일은 만들지 않는다.
EXIT_REFUSED = 2


class ExportRefusedError(Exception):
    """맵이나 출력 자리가 안전장치에 걸렸다. 메시지에는 작품 이름·본문을 넣지 않는다."""


@dataclass(frozen=True)
class MapEntry:
    content_id: uuid.UUID
    slug: str


@dataclass(frozen=True)
class ExportSummary:
    works: int
    images: int
    size_bytes: int
    sha256: str


def read_map(path: Path) -> list[MapEntry]:
    """`<콘텐츠 uuid> <slug>` 줄을 읽는다. 빈 줄과 `#` 줄은 건너뛴다."""
    return []


async def export_seed_bundle(session: AsyncSession, entries: Sequence[MapEntry], out: Path) -> ExportSummary:
    """`entries` 의 작품을 묶음으로 만들어 `out` 에 tar.gz 로 쓴다.

    첫 문장으로 트랜잭션을 읽기 전용으로 바꾸고, 세션의 트랜잭션을 끝내지 않는다(커밋·닫기는 호출부 몫). 맵의 id 가
    DB 에 없거나, 작가가 맵 전체에서 한 명이 아니거나, slug 가 겹치거나, `out` 이 이미 있으면 아무것도 쓰지 않고
    `ExportRefusedError` 를 던진다."""
    return ExportSummary(works=0, images=0, size_bytes=0, sha256="")


async def run(session: AsyncSession, map_path: Path, out: Path) -> int:
    """맵을 읽어 내보내고 요약 한 줄을 찍은 뒤 종료 코드를 돌려준다 — 성공 0, 안전장치 거부 `EXIT_REFUSED`."""
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="운영 작품을 비공개 시드 묶음으로 읽기 전용 내보내기")
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
