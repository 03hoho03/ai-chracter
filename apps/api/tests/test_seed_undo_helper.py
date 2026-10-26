"""`seed_revisions_above`·`undo_seeded_rows_above` 의 검증.

프롬프트 시드 리비전 테스트는 "이 리비전 직후 상태"를 보려고 그 위에 쌓인 시드 리비전들의 `delete_seeded_rows` 를 실제
downgrade 순서(head 쪽부터)로 먼저 부른다. 예전에는 파일마다 그 목록을 손으로 들고 있어 새 시드 리비전이 생길 때마다 여러
파일을 고쳐야 했다. 헬퍼는 alembic 리비전 그래프에서 그 목록을 계산한다.

DB 없이 목록만 본다 — 헬퍼가 그 목록대로 실제로 되돌리는지는 각 시드 리비전 테스트의 "되돌린 뒤 활성 세트" 단언이 잡는다."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from factories import seed_revisions_above

_API_DIR = Path(__file__).resolve().parents[1]
_SCRIPTS = ScriptDirectory.from_config(Config(str(_API_DIR / "alembic.ini")))
# head 에서 base 쪽으로 — 실제 downgrade 순서.
_DOWNGRADE_ORDER = [script.revision for script in _SCRIPTS.walk_revisions()]
# 시드 되돌리기 함수가 있는 리비전 — 모듈을 들여다보지 않고 파일 글자로 찾아, 헬퍼와 다른 길로 구한다.
_SEED_REVISIONS = {
    path.name.split("_", 1)[0]
    for path in (_API_DIR / "migrations" / "versions").glob("*.py")
    if "\ndef delete_seeded_rows(" in path.read_text(encoding="utf-8")
}

# 헬퍼로 바꾸기 직전 각 시드 리비전 테스트가 손으로 들고 있던 "위 리비전 되돌리기" 목록(키는 그 파일이 시험하는 리비전).
# 헬퍼 목록은 이것을 순서째 품어야 한다 — 손 목록이 되돌리던 리비전을 헬퍼가 빠뜨리거나 순서를 바꾸면 그 파일의 "이 리비전
# 직후 상태"가 달라진다. 헬퍼 목록에만 있는 리비전(채팅 테스트의 소설 레인 시드, 소설 레인 테스트의 채팅 레인 시드, 손 목록이
# 빠뜨린 것)은 되돌려도 그 파일이 보는 체인이 바뀌지 않거나 원래 되돌려야 했던 것이다. 위에 새 시드 리비전이 쌓여도 이
# 포함 관계는 그대로라 이 표는 고치지 않는다.
_HAND_LISTS: dict[str, list[str]] = {
    "0f82ea9f9fa5": ["6558ab4d3dbc"],
    "0c1a85bc5c2f": ["6558ab4d3dbc", "0f82ea9f9fa5"],
    "c1f3945cb802": ["6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f"],
    "eb8d3cc6d5c2": ["6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802"],
    "0346abdbcc92": ["6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2"],
    "0aeadefcf159": ["6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"],
    "e4e407a62d03": [
        *("6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"),
        "0aeadefcf159",
    ],
    "726aad108167": [
        *("6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"),
        *("0aeadefcf159", "e4e407a62d03"),
    ],
    "5cab2abe4e7b": [
        *("6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"),
        *("0aeadefcf159", "e4e407a62d03", "726aad108167"),
    ],
    "fc6f0e134782": [
        *("6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"),
        *("0aeadefcf159", "e4e407a62d03", "726aad108167", "5cab2abe4e7b"),
    ],
    "1a843a0b2d8f": [
        *("6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"),
        *("0aeadefcf159", "e4e407a62d03", "726aad108167", "5cab2abe4e7b", "fc6f0e134782"),
    ],
    "d9768bc0cfee": [
        *("6558ab4d3dbc", "0f82ea9f9fa5", "0c1a85bc5c2f", "c1f3945cb802", "eb8d3cc6d5c2", "0346abdbcc92"),
        *("0aeadefcf159", "e4e407a62d03", "726aad108167", "5cab2abe4e7b", "fc6f0e134782"),
    ],
    "b389c2317149": ["174f78b92e5c"],
    "a7a87e3ba631": ["174f78b92e5c", "b389c2317149"],
}


def _is_subsequence(part: list[str], whole: list[str]) -> bool:
    remaining = iter(whole)
    return all(item in remaining for item in part)


def test_subsequence_check_rejects_a_missing_or_reordered_revision() -> None:
    assert _is_subsequence(["a", "c"], ["a", "b", "c"])
    assert not _is_subsequence(["c", "a"], ["a", "b", "c"])
    assert not _is_subsequence(["a", "d"], ["a", "b", "c"])


@pytest.mark.parametrize("revision", sorted(_HAND_LISTS))
def test_helper_list_keeps_every_hand_listed_revision_in_downgrade_order(revision: str) -> None:
    assert _is_subsequence(_HAND_LISTS[revision], seed_revisions_above(revision))


@pytest.mark.parametrize("revision", _DOWNGRADE_ORDER)
def test_helper_lists_exactly_the_seed_revisions_above_head_first(revision: str) -> None:
    above = _DOWNGRADE_ORDER[: _DOWNGRADE_ORDER.index(revision)]
    assert seed_revisions_above(revision) == [rev for rev in above if rev in _SEED_REVISIONS]


def test_the_seed_revision_scan_finds_the_known_revisions() -> None:
    """파일 글자로 찾는 쪽이 아무것도 못 찾으면 위 전수 비교가 빈 목록끼리 통과한다 — 손 목록에 나온 리비전은 모두 찾아야
    한다."""
    assert {rev for revs in _HAND_LISTS.values() for rev in revs} <= _SEED_REVISIONS
