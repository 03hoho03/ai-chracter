"""여러 문단 수정의 순수 규칙 — 대상 블록 확인, 장면 하나 판정, 문맥 문단, 모델 응답 정리, 패치 낡음 판정. DB 를 타지 않는다."""

import hashlib
import random
import uuid

import pytest

from api.novelize.block_edits import (
    BlockEdit,
    BlockEditPatch,
    BlocksNotInOneSceneError,
    block_hash,
    context_positions,
    dismissed_all,
    normalized_result,
    one_scene,
    patch_is_fresh,
    request_targets,
    with_save_states,
)
from api.novelize.blocks import BlockIdsInvalidError

_PARAGRAPHS = ["가 문단.", "나 문단.", "다 문단.", "라 문단.", "마 문단."]


def _ids(count: int = len(_PARAGRAPHS)) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


# ── 대상 블록 ───────────────────────────────────────────────────────────────
def test_targets_come_back_in_text_order_with_their_hash_and_paragraph_number() -> None:
    """요청이 블록 id 를 어떤 차례로 보내든 대상은 본문 차례로 정렬되고, 라벨은 화 전체에서 센 1부터의 문단 번호, 기준 해시는 그
    문단 글자의 sha256 이다. 깨지는 시나리오: 라벨이 요청 차례를 따라 모델이 고친 문단을 다른 블록에 붙인다."""
    ids = _ids()

    targets = request_targets([ids[3], ids[0]], ids, _PARAGRAPHS)

    assert [(t.block_id, t.label, t.base_hash) for t in targets] == [
        (ids[0], 1, hashlib.sha256("가 문단.".encode()).hexdigest()),
        (ids[3], 4, hashlib.sha256("라 문단.".encode()).hexdigest()),
    ]


@pytest.mark.parametrize(
    "pick",
    [
        pytest.param(lambda ids: [], id="empty"),
        pytest.param(lambda ids: [ids[1], ids[1]], id="duplicate"),
        pytest.param(lambda ids: [ids[1], uuid.uuid4()], id="unknown"),
    ],
)
def test_targets_refuse_empty_duplicate_or_unknown_ids(pick: object) -> None:
    ids = _ids()
    with pytest.raises(BlockIdsInvalidError):
        request_targets(pick(ids), ids, _PARAGRAPHS)  # type: ignore[operator]


# ── 장면 ─────────────────────────────────────────────────────────────────────
def test_one_scene_is_the_shared_scene_or_none_for_a_chapter_without_scenes() -> None:
    assert one_scene(["s1", "s1", "s2"], [0, 1]) == "s1"
    assert one_scene([None, None, None], [0, 2]) is None
    with pytest.raises(BlocksNotInOneSceneError):
        one_scene(["s1", "s1", "s2"], [1, 2])


def test_context_is_the_whole_chapter_without_scenes_and_only_the_scene_with_them() -> None:
    """문맥 문단 = 장면 없는 화는 화 전체, 장면 있는 화는 대상 장면의 문단만(순서 그대로, 떨어져 있어도). 깨지는 시나리오: 다른
    장면 문단이 모델에 가서 그 문단을 고쳐 보내거나, 장면 없는 옛 화의 문맥이 줄어 옛 수정보다 앞뒤가 안 맞는다."""
    assert context_positions([None, None, None], None) == [0, 1, 2]
    assert context_positions(["s1", "s2", "s1", "s3"], "s1") == [0, 2]


# ── 모델 응답 정리 ──────────────────────────────────────────────────────────
def _targets(ids: list[uuid.UUID], positions: list[int]) -> list:  # type: ignore[type-arg]
    return request_targets([ids[i] for i in positions], ids, _PARAGRAPHS)


def test_patches_outside_the_targets_are_dropped_and_counted() -> None:
    """모델이 대상이 아닌 문단 번호로 낸 패치는 버리고 그 수를 센다 — 지정 외 블록은 결과에 들어갈 길이 없다. 같은 번호가 둘이면
    앞 것만 남는다. 빈 패치도 남기지 않는다."""
    ids = _ids()
    targets = _targets(ids, [1, 3])

    patches, bundles, outside = normalized_result(
        targets,
        [(2, ["고친 나."]), (3, ["고친 다 — 대상 아님."]), (2, ["두 번째 나."]), (9, ["없는 문단."]), (4, [])],
        [],
    )

    assert [(p.block_id, p.paragraphs, p.state, p.base_hash) for p in patches] == [
        (ids[1], ["고친 나."], "pending", block_hash("나 문단."))
    ]
    assert (bundles, outside) == ([], 2)


def test_random_model_output_never_yields_a_patch_for_a_block_outside_the_targets() -> None:
    """무작위 대상 집합 × 무작위 응답(대상 밖 번호 섞음)에서 남는 패치의 블록은 모두 대상이고, 대상마다 많아야 하나다."""
    rng = random.Random(5)
    for _ in range(200):
        ids = _ids()
        positions = sorted(rng.sample(range(len(ids)), rng.randint(1, len(ids))))
        targets = _targets(ids, positions)
        raw = [(rng.randint(-1, 8), [f"글 {n}"]) for n in range(rng.randint(0, 8))]
        patches, _bundles, _outside = normalized_result(targets, raw, [])
        blocks = [p.block_id for p in patches]
        assert set(blocks) <= {ids[i] for i in positions}
        assert len(blocks) == len(set(blocks))


def test_bundles_keep_patched_members_merge_when_they_overlap_and_a_single_member_is_independent() -> None:
    """묶음은 패치가 있는 대상 번호만 남기고, 겹치는 묶음은 하나로 합치며, 남은 원소가 하나뿐이면 묶음이 아니다(독립)."""
    ids = _ids()
    targets = _targets(ids, [0, 1, 2, 3, 4])
    raw = [(n, [f"고친 {n}"]) for n in (1, 2, 3, 4)]

    patches, bundles, _ = normalized_result(
        targets, raw, [([1, 2], "앞이 정한 이름을 뒤가 쓴다"), ([2, 3], "같은 사건"), ([4, 5], "5는 패치 없음"), ([9], "없음")]
    )

    by_label = {p.block_id: p.id for p in patches}
    assert [sorted(b.patch_ids) for b in bundles] == [sorted([by_label[ids[0]], by_label[ids[1]], by_label[ids[2]]])]
    assert bundles[0].reason == "앞이 정한 이름을 뒤가 쓴다"


# ── 패치 낡음 판정 ──────────────────────────────────────────────────────────
def test_a_patch_is_fresh_while_its_block_exists_with_the_same_text_anywhere() -> None:
    """블록 id 가 지금 개정에 있고 그 문단 글자가 기준과 같으면 신선하다(자리를 옮겨도). 글자가 바뀌었거나 블록이 사라졌으면 낡았다."""
    ids = _ids()
    patch = BlockEditPatch(id="p", block_id=ids[1], base_hash=block_hash("나 문단."), paragraphs=["x"], state="pending")

    assert patch_is_fresh(patch, ids, _PARAGRAPHS)
    assert patch_is_fresh(patch, [ids[1], ids[0]], ["나 문단.", "가 문단."])
    assert not patch_is_fresh(patch, ids, ["가 문단.", "나 문단 고침.", *_PARAGRAPHS[2:]])
    assert not patch_is_fresh(patch, [ids[0], *ids[2:]], [_PARAGRAPHS[0], *_PARAGRAPHS[2:]])


def test_save_states_mark_only_the_changed_targets_stale_and_drop_their_text() -> None:
    ids = _ids()
    targets = _targets(ids, [0, 2])
    patches, _, _ = normalized_result(targets, [(1, ["고친 가."]), (3, ["고친 다."])], [])
    edit = BlockEdit(targets=targets, scene_id=None, patches=patches)

    saved, fresh = with_save_states(edit, ids, ["가 문단.", "나 문단.", "다 문단 사용자 고침.", "라 문단.", "마 문단."])

    assert fresh == 1
    assert [(p.block_id, p.state, p.paragraphs) for p in saved.patches] == [
        (ids[0], "pending", ["고친 가."]),
        (ids[2], "stale", None),
    ]


def test_dismissing_all_keeps_states_as_a_record_but_no_text() -> None:
    ids = _ids()
    targets = _targets(ids, [0, 1])
    patches, bundles, _ = normalized_result(targets, [(1, ["고친 가."]), (2, ["고친 나."])], [([1, 2], "이유")])
    edit = BlockEdit(targets=targets, scene_id="s1", patches=patches, bundles=bundles)

    dismissed = dismissed_all(edit)

    assert [(p.state, p.paragraphs) for p in dismissed.patches] == [("dismissed", None), ("dismissed", None)]
    assert [b.reason for b in dismissed.bundles] == [None]
    assert dismissed.to_json()["sceneId"] == "s1"
    assert "고친" not in str(dismissed.to_json()) and "이유" not in str(dismissed.to_json())
