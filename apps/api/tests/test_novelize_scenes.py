"""장면 경계 — 원고 문단을 장면에 나누는 규칙과, 블록 id → 장면 행으로 지금 개정의 블록마다 장면을 읽는 규칙(DB 없음)."""

import uuid

import pytest

from api.novelize.scenes import assign_scenes, resolve_scenes


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def test_a_block_with_a_row_reads_its_scene_and_a_new_block_reads_the_scene_before_it() -> None:
    """행이 있는 블록은 그 장면, 행이 없는 블록(수정으로 생긴 새 문단)은 바로 앞 블록의 장면이다. 깨지는 시나리오: 장면 사이에 끼운 새
    문단이 장면 없음으로 읽혀 같은 장면 묶음 수정에서 빠진다."""
    a, new, b, new2 = _ids(4)

    assert resolve_scenes([a, new, b, new2], {a: "s1", b: "s2"}) == ["s1", "s1", "s2", "s2"]


def test_leading_blocks_without_a_row_read_the_first_scene_after_them() -> None:
    """화 맨 앞에 끼운 행 없는 블록들은 뒤에 오는 첫 행 있는 블록의 장면이다(앞 블록이 없으므로). 깨지는 시나리오: 맨 앞 새 문단이
    어느 장면에도 들지 않는다."""
    new1, new2, a, b = _ids(4)

    assert resolve_scenes([new1, new2, a, b], {a: "s2", b: "s3"}) == ["s2", "s2", "s2", "s3"]


def test_a_chapter_without_scene_rows_is_one_whole_chapter_scene() -> None:
    """장면 행이 하나도 없는 화(옛 흐름 화, 또는 모든 블록이 새로 바뀐 화)는 블록마다 None — 화 전체를 한 장면으로 읽는다. 깨지는
    시나리오: 행 없는 화에서 엉뚱한 장면 id 가 나오거나 예외가 난다."""
    blocks = _ids(3)

    assert resolve_scenes(blocks, {}) == [None, None, None]
    assert resolve_scenes(blocks, {uuid.uuid4(): "다른 개정의 장면"}) == [None, None, None]


@pytest.mark.parametrize(
    ("lengths", "weights", "expected"),
    [
        pytest.param([10] * 6, [1, 2], [0, 0, 1, 1, 1, 1], id="one_to_two"),
        pytest.param([10] * 4, [1, 1, 1, 1], [0, 1, 2, 3], id="one_each"),
        pytest.param([10] * 2, [1, 1, 1], [0, 2], id="fewer_paragraphs_than_scenes"),
        pytest.param([1, 1, 98], [50, 50], [0, 0, 1], id="by_length"),
        pytest.param([10, 10, 10], [5], [0, 0, 0], id="one_scene"),
        pytest.param([10, 10], [0, 0], [0, 1], id="zero_weights"),
        pytest.param([98, 1, 1], [1, 99], [0, 1, 1], id="first_paragraph_is_the_first_scene"),
        pytest.param([1, 1, 98], [99, 1], [0, 0, 1], id="last_paragraph_is_the_last_scene"),
    ],
)
def test_paragraphs_are_shared_out_to_scenes_in_order_by_their_share_of_the_source(
    lengths: list[int], weights: list[int], expected: list[int]
) -> None:
    """문단은 글자 수로 센 자리(가운데)가 장면들의 원문 몫 누적 구간 어디에 드는지로 장면을 받는다 — 장면 순서대로 이어지고, 첫 문단은
    늘 첫 장면, 끝 문단은 늘 끝 장면이다. 원문 몫이 모두 0 이면 장면 수로 고르게 나눈다. 깨지는 시나리오: 장면 순서가 뒤집히거나 첫·끝
    장면에 문단이 하나도 가지 않는다."""
    assert assign_scenes(lengths, weights) == expected
