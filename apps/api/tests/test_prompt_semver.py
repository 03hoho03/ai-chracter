"""프롬프트 판 매기기의 순수 규칙 — 단계 올리기, 체인 단계, 섹션 내용 비교, 판 계획. DB 를 쓰지 않는다."""

import uuid
from dataclasses import dataclass, replace

import pytest

from api.admin.prompt_semver import (
    SPEAKER_LABELS,
    ChainBase,
    SemverLevelError,
    bump,
    chain_level,
    diff_sections,
    draft_fingerprint,
    format_semver,
    plan_semver,
    section_contents,
)


@dataclass(frozen=True)
class _Row:
    channel: str
    slot: str
    body: str
    scope: str = "both"
    variant: str = ""
    conditional: bool = False
    order: int = 0


@dataclass(frozen=True)
class _Labels:
    user_label: str = "사용자"
    story_assistant_label: str = "진행자"
    story_example_label: str = "서술자"
    character_assistant_label: str = "캐릭터"


_LABELS = _Labels()
_ROWS = [
    _Row("system", "intro", "합성 문장 하나.", order=1),
    _Row("system", "rules", "합성 문장 둘.", order=2, conditional=True),
    _Row("generation", "turn", "합성 문장 셋.", order=1),
]


def _contents(rows: list[_Row] = _ROWS, labels: _Labels = _LABELS) -> dict[str, tuple[object, ...]]:
    return section_contents(labels, rows)


def _changed_channels(new: list[_Row], labels: _Labels = _LABELS) -> set[str]:
    changes = diff_sections(_contents(new, labels), _contents())
    return {channel for channel, change in changes.items() if change != "unchanged"}


# ── 단계 올리기 ─────────────────────────────────────────────────────────────
def test_bump_resets_the_lower_parts_only_for_the_raised_level() -> None:
    """major 는 minor·patch 를, minor 는 patch 를 0 으로 되돌리고 patch 는 patch 만 올린다. 깨지는 시나리오: 공지급 변경
    뒤의 판이 2.3.5 처럼 앞판의 뒷자리를 끌고 가 "새 앞자리의 첫 판"으로 읽히지 않는다."""
    assert bump((1, 2, 3), "major") == (2, 0, 0)
    assert bump((1, 2, 3), "minor") == (1, 3, 0)
    assert bump((1, 2, 3), "patch") == (1, 2, 4)
    assert format_semver((2, 10, 0)) == "2.10.0"


def test_chain_level_is_the_largest_section_level() -> None:
    """체인은 바뀐 섹션 단계 중 가장 큰 단계로 오르고, 바뀐 섹션이 없으면 patch 다. 깨지는 시나리오: 한 섹션을 major 로
    올렸는데 체인은 patch 로 올라 공지급 변경이 체인 번호에 드러나지 않는다."""
    assert chain_level(["patch", "minor"]) == "minor"
    assert chain_level(["minor", "major", "patch"]) == "major"
    assert chain_level(["minor", "patch"]) == "minor"
    assert chain_level([]) == "patch"


# ── 섹션 내용 비교 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"body": "합성 문장 하나. "}, id="body-one-byte"),
        pytest.param({"order": 7}, id="order-only"),
        pytest.param({"conditional": True}, id="conditional-only"),
        pytest.param({"scope": "story"}, id="scope-only"),
        pytest.param({"slot": "intro2"}, id="slot-only"),
        pytest.param({"variant": "alt"}, id="variant-only"),
    ],
)
def test_any_field_of_any_row_changes_the_section(change: dict[str, object]) -> None:
    """채널의 어느 행이든 범위·슬롯·변형·본문·조건·순서 중 하나만 달라도 그 섹션이 바뀐다(본문은 공백 하나까지). 깨지는
    시나리오: 순서나 조건만 바꾼 게시가 "안 바뀜"으로 셈해져, 같은 섹션 번호가 다른 프롬프트를 가리킨다."""
    assert _changed_channels([replace(_ROWS[0], **change), *_ROWS[1:]]) == {"system"}  # type: ignore[arg-type]


def test_an_added_variant_row_changes_the_section() -> None:
    assert _changed_channels([*_ROWS, _Row("system", "intro", "합성 변형.", variant="alt", order=1)]) == {"system"}


def test_row_order_in_the_list_does_not_change_a_section() -> None:
    """행을 담은 순서만 다르면 같은 섹션이다. 깨지는 시나리오: 조회 순서가 바뀌었을 뿐인데 모든 섹션이 바뀜으로 셈해진다."""
    assert _changed_channels(list(reversed(_ROWS))) == set()


@pytest.mark.parametrize(
    "field", ["user_label", "story_assistant_label", "story_example_label", "character_assistant_label"]
)
def test_any_one_speaker_label_changes_the_label_section(field: str) -> None:
    """화자 라벨 넷 중 하나만 달라도 라벨 섹션이 바뀐다. 깨지는 시나리오: 정지 시퀀스에 실리는 라벨을 바꾼 게시가 어느 섹션
    판에도 남지 않는다."""
    assert _changed_channels(list(_ROWS), replace(_LABELS, **{field: "합성 라벨"})) == {SPEAKER_LABELS}


def test_diff_names_added_removed_and_initial_sections() -> None:
    """기준판에만 있으면 빠짐, 새 세트에만 있으면 새 섹션, 기준판이 없으면 전부 시작판이다."""
    new = [*_ROWS[:2], _Row("memory_fact", "intro", "합성 문장 넷.", order=1)]
    assert diff_sections(_contents(new), _contents()) == {
        "system": "unchanged",
        "generation": "removed",
        "memory_fact": "added",
        SPEAKER_LABELS: "unchanged",
    }
    assert diff_sections(_contents(), None) == {"system": "initial", "generation": "initial", SPEAKER_LABELS: "initial"}


def test_fingerprint_follows_the_content() -> None:
    """초안 해시는 내용이 같으면 같고 한 바이트만 달라도 다르다. 깨지는 시나리오: 다른 관리자가 초안을 고친 것을 해시가 놓쳐
    화면이 보지 않은 변경이 게시된다."""
    assert draft_fingerprint(_contents()) == draft_fingerprint(_contents(list(reversed(_ROWS))))
    assert draft_fingerprint(_contents()) != draft_fingerprint(
        _contents([replace(_ROWS[0], body=_ROWS[0].body + " "), *_ROWS[1:]])
    )
    assert draft_fingerprint(_contents()) != draft_fingerprint(_contents(labels=_Labels(user_label="합성")))


# ── 판 계획 ────────────────────────────────────────────────────────────────
_BASE_ID = uuid.uuid4()


def _base(number: tuple[int, int, int] = (1, 2, 0), **maxima: tuple[int, int, int]) -> ChainBase:
    numbers = {"system": (1, 1, 0), "generation": (1, 0, 3), SPEAKER_LABELS: (1, 0, 0)}
    return ChainBase(
        set_id=_BASE_ID,
        number=number,
        section_numbers=numbers,
        contents=_contents(),
        section_maxima={**numbers, **maxima},
    )


def test_plan_raises_only_the_changed_sections_and_copies_the_rest() -> None:
    """바뀐 섹션만 고른 단계로 오르고, 안 바뀐 섹션과 라벨은 기준판 번호를 단계 없이 물려받으며, 체인은 가장 큰 단계로
    오른다. 깨지는 시나리오: 안 바뀐 섹션도 올라 무엇이 바뀌었는지 판으로 읽을 수 없다."""
    new = [replace(_ROWS[0], body="합성 수정."), _ROWS[1], replace(_ROWS[2], body="합성 수정 둘.")]
    plan = plan_semver(_base(), _contents(new), {"system": "minor"})

    assert plan.base_set_id == _BASE_ID
    assert (plan.number, plan.level) == ((1, 3, 0), "minor")
    assert plan.sections == {
        "system": ((1, 2, 0), "minor"),
        "generation": ((1, 0, 4), "patch"),
        SPEAKER_LABELS: ((1, 0, 0), None),
    }
    assert plan.removed == []


def test_plan_with_no_changes_raises_only_the_chain_by_a_patch() -> None:
    """바뀐 섹션이 없는 게시도 허용하고 체인만 patch 로 올린다."""
    plan = plan_semver(_base(), _contents(), {})
    assert (plan.number, plan.level) == ((1, 2, 1), "patch")
    assert all(level is None for _, level in plan.sections.values())
    assert {channel: number for channel, (number, _) in plan.sections.items()} == _base().section_numbers


def test_plan_continues_a_returning_section_from_its_largest_number_in_the_chain() -> None:
    """빠졌다가 다시 들어온 섹션은 1.0.0 을 다시 쓰지 않고 그 체인에서 그 섹션의 가장 큰 번호에서 오른다. 깨지는 시나리오:
    같은 체인에서 그 섹션 1.0.0 이 옛 내용과 새 내용 둘을 가리킨다."""
    new = [*_ROWS, _Row("memory_fact", "intro", "합성 복귀 문장.", order=1)]
    plan = plan_semver(_base(memory_fact=(1, 4, 2)), _contents(new), {"memory_fact": "minor"})
    assert plan.sections["memory_fact"] == ((1, 5, 0), "minor")

    fresh = plan_semver(_base(), _contents(new), {})
    assert fresh.sections["memory_fact"] == ((1, 0, 0), "patch")


def test_plan_counts_a_removed_section_in_the_chain_level() -> None:
    """빠진 섹션은 새 세트에 판 행이 없지만 고른 단계가 체인 상승에 들어가고 이름이 남는다."""
    plan = plan_semver(_base(), _contents(list(_ROWS[:2])), {"generation": "major"})
    assert (plan.number, plan.level) == ((2, 0, 0), "major")
    assert "generation" not in plan.sections
    assert plan.removed == ["generation"]


def test_plan_counts_a_dropped_section_without_a_number_row_as_removed() -> None:
    """기준판에 판 행 없이 내용만 있던 섹션을 지우면 그 섹션도 빠진 섹션이다 — 이름이 남고 고른 단계가 체인 상승에 들어간다.
    깨지는 시나리오: 번호가 없다는 이유로 기준판에 없던 섹션으로 쳐서, 지운 섹션이 결과에서 사라지고 그 단계는 거부된다."""
    base = replace(_base(), section_numbers={"system": (1, 1, 0), SPEAKER_LABELS: (1, 0, 0)})
    plan = plan_semver(base, _contents(list(_ROWS[:2])), {"generation": "major"})
    assert (plan.number, plan.level) == ((2, 0, 0), "major")
    assert plan.removed == ["generation"]


def test_plan_rejects_a_level_for_an_unchanged_or_unknown_section() -> None:
    """안 바뀐 섹션이나 없는 섹션에 단계를 고르면 거부한다. 깨지는 시나리오: 화면이 본 차이와 서버가 본 차이가 어긋났는데
    조용히 버려, 관리자가 major 로 고른 변경이 patch 로 나간다."""
    with pytest.raises(SemverLevelError) as unchanged:
        plan_semver(_base(), _contents(), {"system": "major", "nowhere": "patch"})
    assert unchanged.value.names == ["nowhere", "system"]


def test_plan_without_a_base_starts_everything_at_one_and_ignores_levels_for_present_sections() -> None:
    """기준판이 없는 체인의 첫 게시는 체인·섹션 전부 1.0.0 이고, 이 세트에 있는 섹션의 단계는 무시한다(바뀐 섹션 조회가
    시작판이라 알린 화면이 단계를 보내도 막히지 않게). 없는 섹션 이름은 거부한다."""
    plan = plan_semver(None, _contents(), {"system": "major"})
    assert (plan.number, plan.level, plan.base_set_id) == ((1, 0, 0), None, None)
    assert plan.sections == {channel: ((1, 0, 0), None) for channel in ("system", "generation", SPEAKER_LABELS)}

    with pytest.raises(SemverLevelError):
        plan_semver(None, _contents(), {"nowhere": "patch"})
