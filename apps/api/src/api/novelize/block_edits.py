"""여러 문단 수정의 규칙 — 대상 블록, 장면 하나 판정, 문맥 문단, 모델 응답 정리, 패치 낡음 판정. DB 를 타지 않는다.

**작업 행의 칸 하나**(`NovelJob.block_edit`, JSON)가 한 작업의 전부다: 요청 때 서버가 지금 개정에서 계산한 대상(블록 id·기준 해시·
화 전체에서 센 문단 번호), 대상 장면, 그리고 성공 저장 때 쓰는 블록마다의 패치와 의존 묶음. 사용자 글에서 나온 것은 패치 문단과
묶음 이유뿐이다 — 저장 때 이미 낡은 패치와 버린 패치는 그 문단(버리면 묶음 이유도)을 비우고 상태만 기록으로 남긴다. 저장 뒤
사용자가 블록을 고쳐 낡은 대기 패치의 문단을 비우는 일과 적용한 패치의 문단을 비우는 일은 아직 없다 — 수정안 적용·버리기
라우트와 함께 넣고, 그 전에는 스위치를 켜지 않는다.

**낡음은 패치 단위다**(`patch_is_fresh`): 그 패치의 블록 id 가 지금 개정에 있고 그 문단 글자의 sha256 이 요청 때와 같으면 쓸 수
있다. 화 전체 해시를 보는 옛 수정과 달리 다른 블록이 바뀌어도 이 패치는 산다. 블록 해시를 계산하고 패치를 판정하는 것은 이
모듈뿐이다 — 저장·목록이 모두 여기 함수를 부른다(자리마다 다른 판정이면 저장은 됐는데 목록에서 낡아 보이는 패치가 생긴다).

**모델에는 uuid 를 보내지 않는다.** 문맥 문단은 화 전체에서 센 1부터의 번호 `[n]` 으로 싣고, 모델은 그 번호로 패치를 낸다. 번호 →
블록 id 는 서버가 요청 때 적은 대상으로 되찾는다. 대상이 아닌 번호의 패치는 버린다 — 지정하지 않은 블록이 결과에 들어갈 길이 없다."""

import hashlib
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.novelize.blocks import BlockIdsInvalidError

PatchState = Literal["pending", "applied", "dismissed", "stale"]

# 묶음 이유는 문안이 짧게 쓰라고 하지만 넘쳐 와도 버리지 않고 자른다.
_REASON_MAX_CHARS = 100


class BlockEditTarget(CamelModel):
    """요청한 블록 하나. `label` 은 화 전체에서 센 1부터의 문단 번호(모델에 보이는 번호), `base_hash` 는 그 문단 글자의 sha256."""

    block_id: uuid.UUID
    base_hash: str
    label: int


class BlockEditPatch(CamelModel):
    """블록 하나의 수정안. `paragraphs` 는 그 블록 하나를 대신할 새 문단들이고, 대기(`pending`)일 때만 있다. `revision_id` 는
    적용해 만든 개정(정보용 — 개정을 지워도 남는다)."""

    id: str
    block_id: uuid.UUID
    base_hash: str
    paragraphs: list[str] | None
    state: PatchState
    revision_id: uuid.UUID | None = None


class BlockEditBundle(CamelModel):
    """함께 적용해야 하는 패치들(둘 이상). 원소가 하나뿐이면 묶음이 아니라 독립 패치다."""

    id: str
    patch_ids: list[str]
    reason: str | None


class BlockEdit(CamelModel):
    """작업 행 `block_edit` 칸의 내용. 요청 때는 대상·장면만 있고, 성공 저장이 패치·묶음을 채운다."""

    v: Literal[1] = 1
    targets: list[BlockEditTarget]
    # 장면 경계가 없는 화(옛 흐름 화 등)는 화 전체가 한 장면이라 null 이다.
    scene_id: str | None
    patches: list[BlockEditPatch] = Field(default_factory=list)
    bundles: list[BlockEditBundle] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class BlocksNotInOneSceneError(ValueError):
    """요청한 블록들이 한 장면 안에 있지 않다."""


def block_hash(paragraph: str) -> str:
    return hashlib.sha256(paragraph.encode("utf-8")).hexdigest()


def request_targets(
    requested: Sequence[uuid.UUID], block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> list[BlockEditTarget]:
    """요청한 블록 id 를 지금 개정(`block_ids`·`paragraphs`, 같은 길이)에서 찾아 본문 차례의 대상으로 만든다. 비었거나, 같은 id 가
    둘이거나, 지금 개정에 없는 id 가 있으면 `BlockIdsInvalidError`."""
    position = {block_id: index for index, block_id in enumerate(block_ids)}
    if not requested or len(set(requested)) != len(requested) or any(b not in position for b in requested):
        raise BlockIdsInvalidError
    return [
        BlockEditTarget(block_id=block_ids[index], base_hash=block_hash(paragraphs[index]), label=index + 1)
        for index in sorted(position[b] for b in requested)
    ]


def one_scene(scenes: Sequence[str | None], positions: Sequence[int]) -> str | None:
    """`positions` 문단이 모두 같은 장면이면 그 장면 id(장면 없는 화는 None), 아니면 `BlocksNotInOneSceneError`. `scenes` 는 개정의
    블록마다 읽은 장면(`scenes.revision_scenes`)이다."""
    found = {scenes[index] for index in positions}
    if len(found) != 1:
        raise BlocksNotInOneSceneError
    return found.pop()


def context_positions(scenes: Sequence[str | None], scene_id: str | None) -> list[int]:
    """모델에 보낼 문맥 문단의 위치. 장면 없는 화는 화 전체, 장면 있는 화는 그 장면의 문단만(본문 차례)."""
    return [index for index, scene in enumerate(scenes) if scene_id is None or scene == scene_id]


def normalized_result(
    targets: Sequence[BlockEditTarget],
    patches: Sequence[tuple[int, list[str]]],
    bundles: Sequence[tuple[Sequence[int], str]],
) -> tuple[list[BlockEditPatch], list[BlockEditBundle], int]:
    """모델 응답(번호마다의 문단, 번호 묶음)을 대상 블록의 대기 패치와 묶음으로 정리한다. 돌려주는 셋째 값은 대상이 아닌 번호로 온
    패치 수다(버린다).

    - 같은 번호가 둘이면 앞 것만, 문단이 비면 남기지 않는다. 패치는 본문 차례로 둔다.
    - 묶음은 패치가 남은 번호만 보고, 겹치는 묶음은 하나로 합친다(이유는 합친 묶음 중 모델이 가장 먼저 낸 것). 원소가 하나뿐이면
      묶음이 아니다."""
    by_label = {target.label: target for target in targets}
    kept: dict[int, BlockEditPatch] = {}
    outside = 0
    for label, paragraphs in patches:
        target = by_label.get(label)
        if target is None:
            outside += 1
            continue
        if label in kept or not paragraphs:
            continue
        kept[label] = BlockEditPatch(
            id=uuid.uuid4().hex,
            block_id=target.block_id,
            base_hash=target.base_hash,
            paragraphs=list(paragraphs),
            state="pending",
        )

    # (원소, 이유, 모델이 낸 차례) — 합친 묶음은 목록 뒤로 옮겨지므로 이유는 목록 자리가 아니라 낸 차례가 가장 이른 것에서 고른다.
    groups: list[tuple[set[int], str, int]] = []
    for order, (labels, reason) in enumerate(bundles):
        members = {label for label in labels if label in kept}
        if not members:
            continue
        overlapping = [group for group in groups if group[0] & members]
        merged = members.union(*(group[0] for group in overlapping))
        first = min([(order, reason.strip()[:_REASON_MAX_CHARS]), *((group[2], group[1]) for group in overlapping)])
        groups = [group for group in groups if not group[0] & members]
        groups.append((merged, first[1], first[0]))
    ordered = [kept[label] for label in sorted(kept)]
    patch_bundles = [
        BlockEditBundle(id=uuid.uuid4().hex, patch_ids=[kept[label].id for label in sorted(members)], reason=reason or None)
        for members, reason, _order in groups
        if len(members) >= 2
    ]
    return ordered, patch_bundles, outside


def patch_is_fresh(patch: BlockEditPatch, block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]) -> bool:
    """패치가 지금 개정(`block_ids`·`paragraphs`, 같은 길이)에 아직 쓸 수 있는가 — 그 블록이 있고 그 문단 글자가 요청 때와 같다.
    블록 자리가 옮겨졌어도 글자가 같으면 쓸 수 있다."""
    for block_id, paragraph in zip(block_ids, paragraphs, strict=True):
        if block_id == patch.block_id:
            return block_hash(paragraph) == patch.base_hash
    return False


def fresh_flags(edit: BlockEdit, block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]) -> list[bool]:
    """패치마다 지금 개정에 쓸 수 있는가(대기 패치만 참일 수 있다). 상세 목록이 지금 개정으로 계산해 싣는다."""
    return [patch.state == "pending" and patch_is_fresh(patch, block_ids, paragraphs) for patch in edit.patches]


def with_save_states(
    edit: BlockEdit, block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> tuple[BlockEdit, int]:
    """성공 저장 때 — 지금 개정에 쓸 수 없는 대기 패치를 낡음으로 바꾸고 문단을 비운다. 쓸 수 있는 패치 수를 함께 돌려준다."""
    patches: list[BlockEditPatch] = []
    fresh = 0
    for patch in edit.patches:
        if patch.state == "pending" and patch_is_fresh(patch, block_ids, paragraphs):
            fresh += 1
            patches.append(patch)
        elif patch.state == "pending":
            patches.append(patch.model_copy(update={"state": "stale", "paragraphs": None}))
        else:
            patches.append(patch)
    return edit.model_copy(update={"patches": patches}), fresh


def dismissed_all(edit: BlockEdit) -> BlockEdit:
    """남은 수정안을 모두 버린다 — 대기 패치는 버림으로, 모든 패치 문단과 묶음 이유를 비운다. 상태·블록 id 는 기록으로 남는다."""
    patches = [
        patch.model_copy(update={"state": "dismissed" if patch.state == "pending" else patch.state, "paragraphs": None})
        for patch in edit.patches
    ]
    bundles = [bundle.model_copy(update={"reason": None}) for bundle in edit.bundles]
    return edit.model_copy(update={"patches": patches, "bundles": bundles})
