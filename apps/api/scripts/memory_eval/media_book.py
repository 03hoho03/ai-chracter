"""로컬 미디어 북 넣기 — 측정 작업 DB 의 작품 발행 버전에 미디어 북(인물·장면 축과 칸, 칸마다 상황 설명 한 문장)을 넣는다.
튜토리얼 스토리에는 미디어 북이 없어 스토리 턴의 칸 판정(`chat_media_book_image`)이 불리지 않고, 그러면 판정 표본에 그림 판정
줄이 생기지 않는다. 내용은 튜토리얼 인물·장소에 맞춘 합성이고, 저장소 밖 측정 데이터 폴더(`--data-dir`)의 `SPEC_FILE` 에 둔다.

넣는 곳은 작품의 지금 발행 버전이다 — 방은 만들 때 발행 버전을 고정하고, 칸 판정은 방이 고정한 버전의 칸(대화 중 노출 제외가
아닌 것)을 후보로 읽는다. 그래서 이 명령은 방을 만들기 전에 돌린다. 칸은 축을 entity_id 로 가리키고 그림 자산은 물리 id 로
가리키므로 축 행을 먼저, 자산을 그다음, 칸을 마지막에 넣는다. 그림은 판정에 실리지 않으므로(판정은 인물·장면 이름과 상황 설명만
본다) 저장소에 바이트가 없는 더미 자산(원본·블러본)을 둔다 — 화면에서 그 칸을 열면 그림이 깨진다.

이미 미디어 북이 있는 버전은 거부한다(섞이면 어느 칸이 합성인지 가릴 수 없다)."""

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Asset, AssetKind, AssetStatus
from api.db.models.story import MediaBookCell, MediaBookPerson, MediaBookScene

# 측정 데이터 폴더 안의 기본 명세 파일 이름. 명세는 측정 데이터라 저장소에 두지 않는다.
SPEC_FILE = "media_book_filmclub.json"
# 더미 자산의 크기 — 칸 그림의 화면 비율(세로)만 맞춘다.
_DUMMY_SIZE = (768, 1024)


def load_spec(path: Path) -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return spec


def _check_spec(spec: Mapping[str, Any]) -> None:
    people, scenes = list(spec["people"]), list(spec["scenes"])
    errors = []
    if len(set(people)) != len(people) or len(set(scenes)) != len(scenes):
        errors.append("인물·장면 이름이 겹친다")
    seen: set[tuple[str, str]] = set()
    for cell in spec["cells"]:
        where = (cell["person"], cell["scene"])
        if cell["person"] not in people or cell["scene"] not in scenes:
            errors.append(f"축에 없는 칸: {where}")
        if where in seen:
            errors.append(f"같은 자리 칸이 둘: {where}")
        seen.add(where)
    if errors:
        raise SystemExit("미디어 북 명세 거부: " + "; ".join(errors))


def _dummy_asset(owner_user_id: uuid.UUID, kind: AssetKind) -> Asset:
    return Asset(
        owner_user_id=owner_user_id,
        storage_key=f"memory-eval/dummy-media-book/{uuid.uuid4()}.webp",
        kind=kind,
        status=AssetStatus.READY,
        width=_DUMMY_SIZE[0],
        height=_DUMMY_SIZE[1],
    )


async def insert_media_book(
    db: AsyncSession, content_version_id: uuid.UUID, owner_user_id: uuid.UUID, spec: Mapping[str, Any]
) -> dict[str, int]:
    """명세의 축과 칸을 그 버전에 넣고 flush 한다(커밋은 부르는 쪽). 축 순서는 명세의 순서다."""
    _check_spec(spec)
    for table in (MediaBookPerson, MediaBookScene, MediaBookCell):
        existing = await db.scalar(
            select(func.count()).select_from(table).where(table.content_version_id == content_version_id)
        )
        if existing:
            raise SystemExit(
                f"버전 {content_version_id} 에 이미 미디어 북 행이 있다({table.__tablename__} {existing}개)"
            )
    people = {
        name: MediaBookPerson(entity_id=uuid.uuid4(), content_version_id=content_version_id, name=name, order=i)
        for i, name in enumerate(spec["people"])
    }
    scenes = {
        name: MediaBookScene(entity_id=uuid.uuid4(), content_version_id=content_version_id, name=name, order=i)
        for i, name in enumerate(spec["scenes"])
    }
    db.add_all([*people.values(), *scenes.values()])
    cells = []
    for cell in spec["cells"]:
        image, blurred = _dummy_asset(owner_user_id, AssetKind.ORIGINAL), _dummy_asset(owner_user_id, AssetKind.BLURRED)
        db.add_all([image, blurred])
        await db.flush()
        cells.append(
            MediaBookCell(
                entity_id=uuid.uuid4(),
                content_version_id=content_version_id,
                person_entity_id=people[cell["person"]].entity_id,
                scene_entity_id=scenes[cell["scene"]].entity_id,
                image_asset_id=image.id,
                blurred_asset_id=blurred.id,
                situation_description=cell["situation"],
            )
        )
    db.add_all(cells)
    await db.flush()
    return {"people": len(people), "scenes": len(scenes), "cells": len(cells)}
