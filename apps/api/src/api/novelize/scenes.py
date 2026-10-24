"""장면 경계 — 구성 흐름 원고가 쓴 화의 문단(블록 id)이 장면 구성안의 어느 장면인지 정하고 읽는다.

**쓰기**: 원고 출력은 장면 표시 없이 본문만 낸다(장면 계획 문안이 장면 번호나 계획 문장을 본문에 쓰지 말라고 한다). 그래서 경계는 모델이
아니라 이 모듈이 정한다 — 장면마다 근거 원문의 글자 수를 몫으로 삼아, 문단을 글자 수로 센 자리(가운데)가 장면 몫의 누적 구간 어디에
드는지로 장면 순서대로 나눈다(`assign_scenes`). 첫 문단은 늘 첫 장면, 끝 문단은 늘 끝 장면이다. 원고가 장면 계획의 차례를 따르므로
순서는 맞지만 문단 하나하나의 경계는 추정이다.

**읽기**: 블록 id 마다 행이 하나다(`NovelSceneBlock`). 되돌리기·스냅숏 복원은 옛 블록 id 를 그대로 복제하므로 어느 개정에서도 찾고,
수정으로 생긴 새 블록은 행이 없어 규칙으로 읽는다(`resolve_scenes`): 행이 있으면 그 장면, 없으면 바로 앞 블록의 장면, 화 맨 앞의 행
없는 블록들은 뒤에 오는 첫 행 있는 블록의 장면이다. 그 개정의 블록에 행이 하나도 없으면(옛 흐름 화 등) 화 전체를 한 장면으로 읽고
블록마다 None 을 돌려준다."""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelEpisodeOutline, NovelSceneBlock


def assign_scenes(paragraph_lengths: Sequence[int], scene_weights: Sequence[int]) -> list[int]:
    """문단마다 장면 순번(0부터)을 준다. `paragraph_lengths` 는 문단 글자 수, `scene_weights` 는 장면 차례대로 그 장면 근거 원문의 글자
    수다. 몫이 모두 0 이면 장면마다 같은 몫이다. 결과는 줄지 않는다(장면 차례를 거스르지 않는다)."""
    if not paragraph_lengths:
        return []
    weights = list(scene_weights) if any(scene_weights) else [1] * len(scene_weights)
    total_weight = sum(weights)
    bounds: list[float] = []
    running = 0
    for weight in weights:
        running += weight
        bounds.append(running / total_weight)
    total_length = sum(paragraph_lengths) or len(paragraph_lengths)
    out: list[int] = []
    position = 0
    for length in paragraph_lengths:
        middle = (position + length / 2) / total_length
        position += length
        out.append(next((i for i, bound in enumerate(bounds) if middle < bound), len(bounds) - 1))
    out[0] = 0
    out[-1] = len(bounds) - 1
    return out


def resolve_scenes(block_ids: Sequence[uuid.UUID], scene_of: Mapping[uuid.UUID, str]) -> list[str | None]:
    """개정의 블록 id 차례대로 장면 id 를 읽는다(모듈 docstring 의 읽기 규칙). 행이 하나도 없으면 블록마다 None(화 전체)."""
    resolved: list[str | None] = []
    current: str | None = None
    for block_id in block_ids:
        current = scene_of.get(block_id, current)
        resolved.append(current)
    first = next((scene for scene in resolved if scene is not None), None)
    return [first if scene is None else scene for scene in resolved]


async def revision_scenes(db: AsyncSession, chapter_id: uuid.UUID, block_ids: Sequence[uuid.UUID]) -> list[str | None]:
    """화 `chapter_id` 의 개정 하나(블록 id 목록)를 장면으로 읽는다."""
    rows = await db.execute(
        select(NovelSceneBlock.block_id, NovelSceneBlock.scene_id).where(NovelSceneBlock.chapter_id == chapter_id)
    )
    return resolve_scenes(block_ids, {block_id: scene_id for block_id, scene_id in rows.all()})


async def revision_scene_groups(
    db: AsyncSession, chapter_id: uuid.UUID, block_ids: Sequence[uuid.UUID]
) -> list[tuple[str, str, list[uuid.UUID]]]:
    """개정 하나(블록 id 목록)의 장면마다 (장면 id, 장면 제목, 그 장면의 블록 id 본문 차례), 본문에 처음 나오는 차례로. 블록마다 장면은
    `resolve_scenes` 로 읽고(여러 문단 수정의 장면 판정과 같은 읽기), 제목은 그 개정 블록의 행이 가리키는 장면 구성안 리비전에서 읽는다
    (같은 장면 id 가 여러 리비전에 있으면 가장 최근 리비전). 장면 경계가 없는 화는 빈 목록이다."""
    rows = (
        await db.execute(
            select(NovelSceneBlock.block_id, NovelSceneBlock.scene_id, NovelSceneBlock.episode_outline_id).where(
                NovelSceneBlock.chapter_id == chapter_id
            )
        )
    ).all()
    resolved = resolve_scenes(block_ids, {block_id: scene_id for block_id, scene_id, _ in rows})
    present = set(block_ids)
    outline_ids = {outline_id for block_id, _, outline_id in rows if block_id in present}
    outlines = await db.scalars(
        select(NovelEpisodeOutline)
        .where(NovelEpisodeOutline.id.in_(outline_ids))
        .order_by(NovelEpisodeOutline.revision)
    )
    titles = {scene["id"]: scene["title"] for outline in outlines.all() for scene in outline.scenes}
    groups: dict[str, list[uuid.UUID]] = {}
    for block_id, scene_id in zip(block_ids, resolved, strict=True):
        if scene_id is not None:
            groups.setdefault(scene_id, []).append(block_id)
    return [(scene_id, titles[scene_id], members) for scene_id, members in groups.items()]


def scene_block_rows(
    *,
    chapter_id: uuid.UUID,
    episode_outline_id: uuid.UUID,
    block_ids: Sequence[uuid.UUID],
    paragraph_lengths: Sequence[int],
    scenes: Sequence[tuple[str, int]],
) -> list[NovelSceneBlock]:
    """원고가 새로 쓴 개정의 블록마다 장면 행을 만든다. `scenes` 는 장면 차례대로 (장면 id, 근거 원문 글자 수)다."""
    picked = assign_scenes(paragraph_lengths, [weight for _, weight in scenes])
    return [
        NovelSceneBlock(
            block_id=block_id, chapter_id=chapter_id, episode_outline_id=episode_outline_id, scene_id=scenes[index][0]
        )
        for block_id, index in zip(block_ids, picked, strict=True)
    ]
