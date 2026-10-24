"""여러 문단 수정의 규칙 — 대상 블록, 장면 하나 판정, 문맥 문단, 모델 응답 정리, 패치 낡음 판정. DB 를 타지 않는다.

**작업 행의 칸 하나**(`NovelJob.block_edit`, JSON)가 한 작업의 전부다: 요청 때 서버가 지금 개정에서 계산한 대상(블록 id·기준 해시·
화 전체에서 센 문단 번호), 대상 장면, 그리고 성공 저장 때 쓰는 블록마다의 패치와 의존 묶음. 사용자 글에서 나온 것은 패치 문단과
묶음 이유뿐이다 — 패치가 대기에서 벗어나는 순간(적용·버림·낡음) 그 문단을 비우고, 대기 원소가 없게 된 묶음의 이유도 비운다. 상태·
블록 id·번호는 건수 기록으로 남는다. 기준 해시는 짧은 문단이면 글을 되찾을 수 있어, 대기 패치가 없는 블록(적용·버림·낡음이 된
패치의 블록과 모델이 수정안을 내지 않은 대상)은 성공 저장·적용·버리기·낡음 표시·재검사 분리 때 지우고, 환불한 작업에서는 모두
지운다. 지운 해시는 빈 문자열이다 — `None` 으로 두면 이 칸을 문자열로 읽는 옛 이미지가 배포 겹침 동안 상세 조회에서 깨지고, 빈 문자열은 어떤
문단의 sha256 과도 같지 않아 그 패치를 다시 쓸 길이 없다.

**적용 단위**는 독립 패치 하나 또는 묶음 하나다(`unit_patches`). 묶음은 원소 하나라도 쓸 수 없으면 통째로 거절한다 — 하나만 적용하면
앞뒤가 어긋난 글이 남는다. 사용자가 묶음 원소의 블록을 고쳤으면 재검사(`recheck_plan`·`with_split`)로 남은 원소를 따로 적용해도
되는지 물을 수 있다.

**낡음은 패치 단위다**(`patch_is_fresh`): 그 패치의 블록 id 가 지금 개정에 있고 그 문단 글자의 sha256 이 요청 때와 같으면 쓸 수
있다. 화 전체 해시를 보는 옛 수정과 달리 다른 블록이 바뀌어도 이 패치는 산다. 블록 해시를 계산하고 패치를 판정하는 것은 이
모듈뿐이다 — 저장·목록이 모두 여기 함수를 부른다(자리마다 다른 판정이면 저장은 됐는데 목록에서 낡아 보이는 패치가 생긴다).

**모델에는 uuid 를 보내지 않는다.** 문맥 문단은 화 전체에서 센 1부터의 번호 `[n]` 으로 싣고, 모델은 그 번호로 패치를 낸다. 번호 →
블록 id 는 서버가 요청 때 적은 대상으로 되찾는다. 대상이 아닌 번호의 패치는 버린다 — 지정하지 않은 블록이 결과에 들어갈 길이 없다."""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

from api.core.schema import CamelModel
from api.novelize.blocks import BlockIdsInvalidError, inherit_range

PatchState = Literal["pending", "applied", "dismissed", "stale"]

# 묶음 이유는 문안이 짧게 쓰라고 하지만 넘쳐 와도 버리지 않고 자른다.
_REASON_MAX_CHARS = 100
# 지운 기준 해시. 어떤 문단의 sha256 과도 같지 않다.
_ERASED_HASH = ""
# 재검사에 참고로 싣는 주변 문단 — 고친 블록과 남은 패치 블록의 앞뒤로 이만큼(같은 장면 안).
RECHECK_CONTEXT_RADIUS = 2


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


class UnitNotFoundError(LookupError):
    """작업에 그런 패치나 묶음이 없다."""


class UnitNotApplicableError(ValueError):
    """그 단위로는 적용·버리기·재검사를 할 수 없다 — 묶음에 든 패치를 혼자 골랐거나, 이미 끝난 원소가 있거나, 재검사로 물을 남은
    원소·고친 글이 없다."""


class RecheckNotNeededError(ValueError):
    """묶음 원소가 하나도 고쳐지지 않았다 — 묻지 않아도 묶음째 적용할 수 있다."""


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
    """성공 저장 때 — 지금 개정에 쓸 수 없는 대기 패치를 낡음으로 바꾸고 문단과 그 블록의 기준 해시를 비우며, 대기 원소가 없게 된
    묶음의 이유도 비운다(그 화에 다음 개정이 생길 때까지 모델이 쓴 문장이 남지 않게). 쓸 수 있는 패치 수를 함께 돌려준다."""
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
    return _settled(edit.model_copy(update={"patches": patches})), fresh


def dismissed_all(edit: BlockEdit) -> BlockEdit:
    """남은 수정안을 모두 버린다 — 대기·낡음 패치는 버림으로, 모든 패치 문단·묶음 이유·기준 해시를 지운다. 상태·블록 id 는 건수
    기록으로 남는다."""
    patches = [
        patch.model_copy(
            update={"state": "dismissed" if patch.state in ("pending", "stale") else patch.state, "paragraphs": None}
        )
        for patch in edit.patches
    ]
    bundles = [bundle.model_copy(update={"reason": None}) for bundle in edit.bundles]
    return without_base_hashes(edit.model_copy(update={"patches": patches, "bundles": bundles}))


def _settled(edit: BlockEdit) -> BlockEdit:
    """대기 원소가 하나도 없는 묶음의 이유를 비우고(이유는 모델이 사용자 글을 읽고 쓴 글이다), 대기 패치가 없는 모든 블록의 기준
    해시를 대상·패치 양쪽에서 지운다 — 끝난(적용·버림·낡음) 패치의 블록도, 모델이 수정안을 내지 않은 대상도다. 기준 해시는 대기
    패치의 적용 판정에만 쓰고, 짧은 문단은 해시로 글을 되찾을 수 있다. 정산 자리마다 같은 규칙이라 이전 판이 남긴 해시도 다음
    정산 때 지워진다."""
    states = {patch.id: patch.state for patch in edit.patches}
    bundles = [
        bundle
        if any(states.get(patch_id) == "pending" for patch_id in bundle.patch_ids)
        else bundle.model_copy(update={"reason": None})
        for bundle in edit.bundles
    ]
    waiting = {patch.block_id for patch in edit.patches if patch.state == "pending"}
    blocks = {target.block_id for target in edit.targets} | {patch.block_id for patch in edit.patches}
    return _without_hashes_of(edit.model_copy(update={"bundles": bundles}), blocks - waiting)


def _without_hashes_of(edit: BlockEdit, blocks: set[uuid.UUID] | None) -> BlockEdit:
    """`blocks`(None 이면 전부)의 기준 해시를 대상과 패치 양쪽에서 지운다."""

    def erased(block_id: uuid.UUID) -> bool:
        return blocks is None or block_id in blocks

    targets = [
        target.model_copy(update={"base_hash": _ERASED_HASH}) if erased(target.block_id) else target
        for target in edit.targets
    ]
    patches = [
        patch.model_copy(update={"base_hash": _ERASED_HASH}) if erased(patch.block_id) else patch
        for patch in edit.patches
    ]
    return edit.model_copy(update={"targets": targets, "patches": patches})


def without_base_hashes(edit: BlockEdit) -> BlockEdit:
    """환불한 작업·전부 버린 작업 — 모든 기준 해시를 지운다. 블록 id·번호·상태는 건수 기록으로 남는다."""
    return _without_hashes_of(edit, None)


def has_pending(edit: BlockEdit) -> bool:
    return any(patch.state == "pending" for patch in edit.patches)


def unit_patches(edit: BlockEdit, *, patch_id: str | None, bundle_id: str | None) -> list[BlockEditPatch]:
    """적용·버리기 단위의 패치들(본문 차례). 묶음이면 원소 전부, 패치면 묶음에 들지 않은 그 패치 하나. 모르는 id 는
    `UnitNotFoundError`, 묶음에 든 패치를 혼자 고르면 `UnitNotApplicableError`."""
    if bundle_id is not None:
        bundle = next((bundle for bundle in edit.bundles if bundle.id == bundle_id), None)
        if bundle is None:
            raise UnitNotFoundError
        members = set(bundle.patch_ids)
        return [patch for patch in edit.patches if patch.id in members]
    patch = next((patch for patch in edit.patches if patch.id == patch_id), None)
    if patch is None:
        raise UnitNotFoundError
    if any(patch.id in bundle.patch_ids for bundle in edit.bundles):
        raise UnitNotApplicableError
    return [patch]


def unit_stale_ids(
    patches: Sequence[BlockEditPatch], block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> list[str]:
    """단위에서 지금 개정에 쓸 수 없는 원소의 id — 낡음 상태이거나, 대기인데 그 블록이 없거나 글이 바뀌었다. 이미 끝난(적용·버림)
    원소가 있으면 `UnitNotApplicableError`."""
    if any(patch.state in ("applied", "dismissed") for patch in patches):
        raise UnitNotApplicableError
    return [
        patch.id for patch in patches if patch.state == "stale" or not patch_is_fresh(patch, block_ids, paragraphs)
    ]


def applied_body(
    patches: Sequence[BlockEditPatch], block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> tuple[list[str], list[uuid.UUID]]:
    """지금 개정(`block_ids`·`paragraphs`)에 대기 패치들을 적용한 문단·블록 id. 앞에서부터 걸으며 패치의 블록만 그 문단들로 바꾸고,
    그 밖의 문단·id 는 자리째 둔다. id 는 블록마다 따로 잇는다 — 글자가 같은 문단이 있으면 그 문단, 없으면 첫 문단이 그 블록 id 를
    받고 나머지는 새 id 라(범위 편집과 같은 승계), 블록 id 가 다른 블록 자리로 건너가지 않는다."""
    by_block = {patch.block_id: patch for patch in patches}
    out_paragraphs: list[str] = []
    out_ids: list[uuid.UUID] = []
    for block_id, paragraph in zip(block_ids, paragraphs, strict=True):
        patch = by_block.get(block_id)
        if patch is None:
            out_paragraphs.append(paragraph)
            out_ids.append(block_id)
            continue
        assert patch.paragraphs  # 대기 패치는 문단을 하나 이상 가진다(`normalized_result`)
        out_paragraphs.extend(patch.paragraphs)
        out_ids.extend(inherit_range([paragraph], [block_id], 0, 0, patch.paragraphs))
    return out_paragraphs, out_ids


def with_applied(edit: BlockEdit, patch_ids: Sequence[str], revision_id: uuid.UUID) -> BlockEdit:
    """`patch_ids` 를 적용했다 — 상태 적용, 문단·그 블록의 기준 해시 비움, 적용한 개정 id. 다 끝난 묶음의 이유를 비운다."""
    chosen = set(patch_ids)
    patches = [
        patch.model_copy(update={"state": "applied", "paragraphs": None, "revision_id": revision_id})
        if patch.id in chosen
        else patch
        for patch in edit.patches
    ]
    return _settled(edit.model_copy(update={"patches": patches}))


def with_dismissed(edit: BlockEdit, patch_ids: Sequence[str]) -> BlockEdit:
    """`patch_ids` 를 버린다 — 대기·낡음 패치만 버릴 수 있고(아니면 `UnitNotApplicableError`), 문단과 그 블록의 기준 해시를 지운다.
    다 끝난 묶음의 이유를 비운다."""
    chosen = set(patch_ids)
    if any(patch.id in chosen and patch.state not in ("pending", "stale") for patch in edit.patches):
        raise UnitNotApplicableError
    patches = [
        patch.model_copy(update={"state": "dismissed", "paragraphs": None}) if patch.id in chosen else patch
        for patch in edit.patches
    ]
    return _settled(edit.model_copy(update={"patches": patches}))


def stale_marked(edit: BlockEdit, block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]) -> BlockEdit:
    """새 개정 뒤 — 지금 개정에 쓸 수 없게 된 대기 패치를 낡음으로(문단·기준 해시 비움) 바꾸고 다 끝난 묶음의 이유를 비운다. 낡음은 영구다:
    같은 글로 되돌아와도 되살리지 않는다(되살릴 문단이 이미 없다)."""
    marked, _fresh = with_save_states(edit, block_ids, paragraphs)
    return marked


@dataclass(frozen=True)
class RecheckPlan:
    """재검사에 실을 것. `edited` 는 사용자가 고친 원소 중 블록이 아직 화에 있는 것의 (지금 위치, 지금 글), `remaining` 은 아직 적용할
    수 있는 원소의 (지금 위치, 패치), `edited_patch_ids` 는 고친 원소 전부(블록이 지워진 것 포함)."""

    edited: list[tuple[int, str]]
    remaining: list[tuple[int, BlockEditPatch]]
    edited_patch_ids: list[str]


def recheck_plan(
    edit: BlockEdit, bundle_id: str, block_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> RecheckPlan:
    """묶음 `bundle_id` 를 지금 개정에서 재검사할 계획. 고친 원소(낡음, 또는 대기인데 블록이 바뀜·없음)가 없으면
    `RecheckNotNeededError`. 남은 원소가 없거나 고친 블록이 모두 화에서 지워져 보여 줄 글이 없으면 `UnitNotApplicableError` — 짝
    문단을 지운 묶음은 물을 거리가 없어 버리기만 남는다. 모르는 묶음은 `UnitNotFoundError`."""
    members = unit_patches(edit, patch_id=None, bundle_id=bundle_id)
    stale = set(unit_stale_ids(members, block_ids, paragraphs))
    if not stale:
        raise RecheckNotNeededError
    position = {block_id: index for index, block_id in enumerate(block_ids)}
    edited = sorted(
        (position[patch.block_id], paragraphs[position[patch.block_id]])
        for patch in members
        if patch.id in stale and patch.block_id in position
    )
    remaining = sorted(
        ((position[patch.block_id], patch) for patch in members if patch.id not in stale), key=lambda item: item[0]
    )
    if not remaining or not edited:
        raise UnitNotApplicableError
    return RecheckPlan(
        edited=edited, remaining=remaining, edited_patch_ids=[patch.id for patch in members if patch.id in stale]
    )


def recheck_context_positions(plan: RecheckPlan, scenes: Sequence[str | None], scene_id: str | None) -> list[int]:
    """재검사에 참고로 실을 주변 문단 위치 — 고친 블록과 남은 패치 블록의 앞뒤 `RECHECK_CONTEXT_RADIUS` 안, 같은 장면. 고친 블록
    자신은 따로 실으므로 뺀다."""
    allowed = set(context_positions(scenes, scene_id))
    edited = {index for index, _text in plan.edited}
    anchors = edited | {index for index, _patch in plan.remaining}
    near = {
        index for anchor in anchors for index in range(anchor - RECHECK_CONTEXT_RADIUS, anchor + RECHECK_CONTEXT_RADIUS + 1)
    }
    return sorted((near & allowed) - edited)


def with_split(edit: BlockEdit, bundle_id: str, plan: RecheckPlan) -> BlockEdit:
    """남은 원소를 따로 적용해도 된다는 판정 — 고친 원소를 묶음에서 빼 낡음(문단·기준 해시 없음)으로 두고, 남은 원소가 하나면 묶음을
    없애 독립 패치로, 둘 이상이면 그 원소들끼리 묶음으로 남긴다(남은 원소끼리 기대는지는 처음 판정 그대로다)."""
    edited = set(plan.edited_patch_ids)
    patches = [
        patch.model_copy(update={"state": "stale", "paragraphs": None}) if patch.id in edited else patch
        for patch in edit.patches
    ]
    bundles: list[BlockEditBundle] = []
    for bundle in edit.bundles:
        if bundle.id != bundle_id:
            bundles.append(bundle)
            continue
        kept = [patch_id for patch_id in bundle.patch_ids if patch_id not in edited]
        if len(kept) >= 2:
            bundles.append(bundle.model_copy(update={"patch_ids": kept}))
    return _settled(edit.model_copy(update={"patches": patches, "bundles": bundles}))
