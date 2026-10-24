"""여러 문단 수정의 적용 단위 규칙 — 단위 고르기, 단위 낡음, 적용 본문·블록 id, 적용·버리기·낡음 표시 뒤의 칸, 기준 해시 지우기,
묶음 재검사 계획과 분리. DB 를 타지 않는다."""

import random
import uuid

import pytest

from api.novelize.block_edits import (
    BlockEdit,
    BlockEditPatch,
    RecheckNotNeededError,
    UnitNotApplicableError,
    UnitNotFoundError,
    applied_body,
    block_hash,
    dismissed_all,
    has_pending,
    normalized_result,
    recheck_plan,
    request_targets,
    stale_marked,
    unit_patches,
    unit_stale_ids,
    with_applied,
    with_dismissed,
    with_save_states,
    with_split,
    without_base_hashes,
)

_PARAGRAPHS = ["가 문단.", "나 문단.", "다 문단.", "라 문단.", "마 문단."]


def _ids(count: int = len(_PARAGRAPHS)) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


def _edit(
    ids: list[uuid.UUID],
    positions: list[int],
    bundles: list[list[int]] | None = None,
    paragraphs: list[str] | None = None,
) -> BlockEdit:
    """`positions` 문단마다 "고친 n." 패치, `bundles` 는 위치 목록의 묶음."""
    texts = paragraphs or _PARAGRAPHS
    targets = request_targets([ids[i] for i in positions], ids, texts)
    patches, patch_bundles, _ = normalized_result(
        targets,
        [(i + 1, [f"고친 {i + 1}."]) for i in positions],
        [([i + 1 for i in members], "앞이 정한 사실을 뒤가 쓴다") for members in bundles or []],
    )
    return BlockEdit(targets=targets, scene_id=None, patches=patches, bundles=patch_bundles)


def _by_block(edit: BlockEdit, block_id: uuid.UUID) -> BlockEditPatch:
    return next(patch for patch in edit.patches if patch.block_id == block_id)


# ── 단위 고르기 ─────────────────────────────────────────────────────────────
def test_a_unit_is_one_independent_patch_or_one_whole_bundle() -> None:
    """독립 패치는 혼자, 묶음은 원소 전부가 한 단위다. 묶음에 든 패치를 혼자 고르면 거절하고, 모르는 id 는 찾지 못함이다. 깨지는
    시나리오: 묶음 원소 하나만 적용돼 앞뒤가 어긋난 글이 남는다(N-Q12 묶음 원자)."""
    ids = _ids()
    edit = _edit(ids, [0, 2, 3], bundles=[[2, 3]])
    alone, b_patch, c_patch = edit.patches
    (bundle,) = edit.bundles

    assert unit_patches(edit, patch_id=alone.id, bundle_id=None) == [alone]
    assert unit_patches(edit, patch_id=None, bundle_id=bundle.id) == [b_patch, c_patch]
    with pytest.raises(UnitNotApplicableError):
        unit_patches(edit, patch_id=b_patch.id, bundle_id=None)
    with pytest.raises(UnitNotFoundError):
        unit_patches(edit, patch_id="nope", bundle_id=None)
    with pytest.raises(UnitNotFoundError):
        unit_patches(edit, patch_id=None, bundle_id="nope")


def test_a_unit_is_stale_when_any_member_is_stale_or_its_block_changed() -> None:
    """단위의 낡은 원소 id — 상태가 낡음이거나, 대기인데 그 블록 글이 바뀌었거나 블록이 없다. 끝난(적용·버림) 원소가 있으면 쓸 수
    없는 단위다."""
    ids = _ids()
    edit = _edit(ids, [1, 2, 3], bundles=[[1, 2, 3]])
    b, c, d = edit.patches
    edited = [*_PARAGRAPHS[:2], "사용자가 고친 다.", *_PARAGRAPHS[3:]]

    assert unit_stale_ids([b, c, d], ids, _PARAGRAPHS) == []
    assert unit_stale_ids([b, c, d], ids, edited) == [c.id]
    assert unit_stale_ids([b, c, d], [ids[0], ids[2], ids[3], ids[4]], [_PARAGRAPHS[i] for i in (0, 2, 3, 4)]) == [b.id]
    marked = b.model_copy(update={"state": "stale", "paragraphs": None})
    assert unit_stale_ids([marked, c, d], ids, _PARAGRAPHS) == [b.id]
    with pytest.raises(UnitNotApplicableError):
        unit_stale_ids([b.model_copy(update={"state": "applied"}), c], ids, _PARAGRAPHS)


# ── 적용 본문 ───────────────────────────────────────────────────────────────
def test_applying_replaces_only_the_unit_blocks_and_keeps_every_other_paragraph_and_id() -> None:
    """적용 본문은 지금 개정을 앞에서부터 걸으며 단위의 블록만 패치 문단으로 바꾼다 — 그 밖의 문단·id 는 자리째 그대로다(지정 외
    블록 불변). 블록이 그사이 옮겨졌어도 id 로 찾는다."""
    ids = _ids()
    edit = _edit(ids, [1, 3])
    moved_ids = [ids[3], ids[0], ids[1], ids[2], ids[4]]
    moved = [_PARAGRAPHS[3], _PARAGRAPHS[0], _PARAGRAPHS[1], _PARAGRAPHS[2], _PARAGRAPHS[4]]

    paragraphs, block_ids = applied_body(edit.patches, moved_ids, moved)

    assert paragraphs == ["고친 4.", "가 문단.", "고친 2.", "다 문단.", "마 문단."]
    assert block_ids == moved_ids


@pytest.mark.parametrize(
    ("replacement", "kept_at"),
    [
        pytest.param(["새 글 하나.", "새 글 둘."], 0, id="split-first-inherits"),
        pytest.param(["앞에 더한 글.", "나 문단."], 1, id="same-text-keeps-id"),
    ],
)
def test_a_patch_with_several_paragraphs_keeps_the_block_id_on_one_of_them(
    replacement: list[str], kept_at: int
) -> None:
    """패치가 문단 여럿이면 블록 id 는 하나에만 남는다 — 글자가 같은 문단이 있으면 그 문단, 없으면 첫 문단(범위 편집과 같은 승계).
    나머지는 새 id 다. 깨지는 시나리오: 이 블록 뒤에 붙은 삽화가 위치를 잃거나 다른 문단으로 옮겨 붙는다."""
    ids = _ids()
    edit = _edit(ids, [1])
    patch = edit.patches[0].model_copy(update={"paragraphs": replacement})

    paragraphs, block_ids = applied_body([patch], ids, _PARAGRAPHS)

    assert paragraphs == [_PARAGRAPHS[0], *replacement, *_PARAGRAPHS[2:]]
    new = block_ids[1:3]
    assert new[kept_at] == ids[1]
    assert new[1 - kept_at] not in ids
    assert [block_ids[0], *block_ids[3:]] == [ids[0], *ids[2:]]


def test_applied_bodies_never_change_blocks_outside_the_unit_for_random_units() -> None:
    """성질: 무작위 화·무작위 단위에서 단위 밖 블록의 (id, 글) 순서열이 적용 전후로 같고, id 가 겹치지 않는다(N-Q11)."""
    rng = random.Random(5)
    for _ in range(200):
        count = rng.randint(1, 8)
        texts = [f"문단 {rng.randint(0, 3)}-{i}." for i in range(count)]
        ids = _ids(count)
        positions = sorted(rng.sample(range(count), rng.randint(1, count)))
        targets = request_targets([ids[i] for i in positions], ids, texts)
        patches, _, _ = normalized_result(
            targets, [(i + 1, [f"새 {i}-{k}." for k in range(rng.randint(1, 3))]) for i in positions], []
        )
        unit = rng.sample(patches, rng.randint(1, len(patches)))
        touched = {patch.block_id for patch in unit}

        paragraphs, block_ids = applied_body(unit, ids, texts)

        outside_before = [(i, t) for i, t in zip(ids, texts, strict=True) if i not in touched]
        outside_after = [(i, t) for i, t in zip(block_ids, paragraphs, strict=True) if i in set(ids) - touched]
        assert outside_after == outside_before
        assert len(set(block_ids)) == len(block_ids) == len(paragraphs)
        assert touched <= set(block_ids)


# ── 적용·버리기 뒤의 칸 ─────────────────────────────────────────────────────
def test_after_applying_a_unit_its_patches_are_applied_without_text_and_the_rest_wait() -> None:
    """적용한 패치는 상태 적용·문단 없음·적용한 개정 id, 다 끝난 묶음의 이유는 비운다. 같은 작업의 다른 패치는 대기 그대로다(N-Q12
    독립 A 단독)."""
    ids = _ids()
    edit = _edit(ids, [0, 2, 3], bundles=[[2, 3]])
    alone, b, c = edit.patches
    revision_id = uuid.uuid4()

    after_a = with_applied(edit, [alone.id], revision_id)
    after_bundle = with_applied(after_a, [b.id, c.id], revision_id)

    assert [(p.state, p.paragraphs, p.revision_id) for p in after_a.patches] == [
        ("applied", None, revision_id),
        ("pending", ["고친 3."], None),
        ("pending", ["고친 4."], None),
    ]
    assert after_a.bundles[0].reason == "앞이 정한 사실을 뒤가 쓴다"
    assert has_pending(after_a)
    assert [p.state for p in after_bundle.patches] == ["applied"] * 3
    assert after_bundle.bundles[0].reason is None
    assert not has_pending(after_bundle)


def test_dismissing_a_unit_drops_its_text_and_base_hashes_but_keeps_the_others() -> None:
    """버린 패치는 상태 버림·문단 없음이고, 그 블록의 기준 해시를 대상과 패치 양쪽에서 지운다(짧은 문단은 해시로 되찾을 수 있다).
    버리지 않은 패치·대상의 해시는 그대로다 — 적용할 때 판정에 쓴다. 낡음 패치도 버릴 수 있고, 끝난 패치를 버리려면 거절이다."""
    ids = _ids()
    edit = _edit(ids, [0, 2])
    a, b = edit.patches
    stale_b = edit.model_copy(update={"patches": [a, b.model_copy(update={"state": "stale", "paragraphs": None})]})

    after = with_dismissed(stale_b, [b.id])

    assert [(p.state, p.paragraphs, p.base_hash) for p in after.patches] == [
        ("pending", ["고친 1."], block_hash(_PARAGRAPHS[0])),
        ("dismissed", None, ""),
    ]
    assert [t.base_hash for t in after.targets] == [block_hash(_PARAGRAPHS[0]), ""]
    with pytest.raises(UnitNotApplicableError):
        with_dismissed(with_applied(edit, [a.id], uuid.uuid4()), [a.id])


def test_dismissing_everything_and_refunding_drop_every_base_hash() -> None:
    """전부 버리기는 대기 패치를 버림으로 바꾸고 모든 문단·묶음 이유·기준 해시를 지운다. 환불(요청 때 대상만 있는 칸)도 대상의
    기준 해시를 지운다. 상태·블록 id·번호는 건수 기록으로 남는다."""
    ids = _ids()
    edit = _edit(ids, [0, 2], bundles=[[0, 2]])
    requested = BlockEdit(targets=edit.targets, scene_id=None)

    dropped = dismissed_all(edit)
    refunded = without_base_hashes(requested)

    assert [(p.state, p.paragraphs, p.base_hash) for p in dropped.patches] == [("dismissed", None, "")] * 2
    assert [b.reason for b in dropped.bundles] == [None]
    assert [t.base_hash for t in dropped.targets] == ["", ""]
    assert [(t.block_id, t.label, t.base_hash) for t in refunded.targets] == [(ids[0], 1, ""), (ids[2], 3, "")]


def test_stale_marking_turns_only_changed_pending_patches_stale_and_settles_finished_bundles() -> None:
    """저장 뒤 비우기: 블록이 바뀐 대기 패치만 낡음(문단 없음)으로, 신선한 패치는 그대로. 대기 원소가 하나도 없게 된 묶음의 이유를
    비운다."""
    ids = _ids()
    edit = _edit(ids, [0, 1, 3], bundles=[[0, 1]])
    edited = ["사용자가 고친 가.", "사용자가 고친 나.", *_PARAGRAPHS[2:]]

    marked = stale_marked(edit, ids, edited)

    assert [(p.state, p.paragraphs) for p in marked.patches] == [
        ("stale", None),
        ("stale", None),
        ("pending", ["고친 4."]),
    ]
    assert [b.reason for b in marked.bundles] == [None]
    assert stale_marked(edit, ids, _PARAGRAPHS) == edit


def test_a_save_that_finds_a_whole_bundle_edited_drops_its_reason() -> None:
    """성공 저장 때 묶음 원소가 모두 이미 고쳐져 낡음이 되면 그 묶음의 이유(모델이 사용자 글을 읽고 쓴 문장)를 비운다 — 다른 독립
    패치가 살아 저장은 성공하므로, 비우지 않으면 그 화에 다음 개정이 생길 때까지 남는다."""
    ids = _ids()
    edit = _edit(ids, [0, 1, 3], bundles=[[0, 1]])
    edited = ["사용자가 고친 가.", "사용자가 고친 나.", *_PARAGRAPHS[2:]]

    saved, fresh = with_save_states(edit, ids, edited)

    assert fresh == 1
    assert [b.reason for b in saved.bundles] == [None]


# ── 재검사 ───────────────────────────────────────────────────────────────────
def test_a_recheck_plan_needs_an_edited_member_and_a_member_still_to_apply() -> None:
    """재검사는 묶음에 사용자가 고친(낡은) 원소가 있고 아직 적용할 수 있는 원소가 남을 때만 한다. 고친 원소의 지금 글과 위치, 남은
    원소의 지금 위치를 돌려준다. 고친 블록이 화에서 지워졌으면 그 블록의 글은 싣지 않는다."""
    ids = _ids()
    edit = _edit(ids, [0, 2, 3], bundles=[[0, 2, 3]])
    a, b, c = edit.patches
    (bundle,) = edit.bundles
    edited = ["사용자가 고친 가.", *_PARAGRAPHS[1:]]

    plan = recheck_plan(edit, bundle.id, ids, edited)

    assert plan.edited == [(0, "사용자가 고친 가.")]
    assert plan.edited_patch_ids == [a.id]
    assert [(position, patch.id) for position, patch in plan.remaining] == [(2, b.id), (3, c.id)]
    with pytest.raises(RecheckNotNeededError):
        recheck_plan(edit, bundle.id, ids, _PARAGRAPHS)
    with pytest.raises(UnitNotFoundError):
        recheck_plan(edit, "nope", ids, edited)
    every = [f"사용자가 고친 {i}." for i in range(5)]
    with pytest.raises(UnitNotApplicableError):
        recheck_plan(edit, bundle.id, ids, every)
    gone_ids = ids[1:]
    with pytest.raises(UnitNotApplicableError):
        recheck_plan(edit, bundle.id, gone_ids, _PARAGRAPHS[1:])


@pytest.mark.parametrize(
    ("members", "expected_bundles"),
    [
        pytest.param([0, 2], [], id="two-members-leave-one-independent"),
        pytest.param([0, 2, 3], [[2, 3]], id="three-members-keep-the-rest-together"),
    ],
)
def test_a_split_takes_the_edited_members_out_and_marks_them_stale(
    members: list[int], expected_bundles: list[list[int]]
) -> None:
    """따로 적용해도 된다는 판정이면 고친 원소를 묶음에서 빼 낡음(문단 없음)으로 두고, 남은 원소가 하나면 독립, 둘 이상이면 여전히
    한 묶음이다(서로 기대는지는 처음 판정 그대로). 깨지는 시나리오: B 를 고친 뒤 C 가 영영 적용되지 못하거나, C·D 가 서로 떨어져
    하나만 적용된다."""
    ids = _ids()
    edit = _edit(ids, members, bundles=[members])
    (bundle,) = edit.bundles
    edited = ["사용자가 고친 가.", *_PARAGRAPHS[1:]]

    split = with_split(edit, bundle.id, recheck_plan(edit, bundle.id, ids, edited))

    assert _by_block(split, ids[0]).state == "stale" and _by_block(split, ids[0]).paragraphs is None
    assert [[next(p.block_id for p in split.patches if p.id == pid) for pid in b.patch_ids] for b in split.bundles] == [
        [ids[i] for i in group] for group in expected_bundles
    ]
    assert all(p.state == "pending" for p in split.patches if p.block_id != ids[0])
