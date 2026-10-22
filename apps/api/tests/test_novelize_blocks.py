"""화 개정 블록 id 의 승계 규칙과 쓰기 함수 — DB 를 타지 않는다.

범위 편집(직접 수정·AI 수정 적용)은 글자가 같은 문단의 id 를 그대로 두고, 바뀐 구간마다 그 구간의 첫 새 문단이 그 구간의 첫
옛 id 를 잇는다(나머지는 새 id). 직접 수정에서 화면이 id 를 싣지 않으면 서버가 옛 본문과 새 본문의 같은 앞부분·뒷부분을
걷어 바뀐 범위를 되찾는다 — 바깥 문단 id 는 제자리다(범위 가장자리의 새 글이 바로 바깥 문단과 글자가 같을 때만 글자로
가를 수 없다). AI 수정 적용은 작업이 범위를 알아 위치로 계산한다.

맨 끝의 구조 검사는 개정 행을 만드는 길이 `blocks.py` 하나뿐인지 본다 — 다른 곳에서 개정을 만들면 블록 칸 불변식(문단 수 =
id 수, id 가 겹치지 않음)을 거치지 않는다."""

import ast
import hashlib
import random
import uuid
from pathlib import Path

import pytest

from api.db.models import NovelChapterRevision
from api.novelize import blocks
from api.novelize.text import split_paragraphs

_SRC = Path(__file__).resolve().parents[1] / "src" / "api"


def _ids(count: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


def _revision(body: str, block_ids: list[uuid.UUID]) -> NovelChapterRevision:
    return NovelChapterRevision(body=body, source="generate", block_ids=block_ids)


# ── 글자로 잇기(직접 수정, 화면이 id 를 싣지 않을 때) ─────────────────────────
@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        pytest.param("ABC", "ABC", [0, 1, 2], id="unchanged"),
        pytest.param("ABC", "AbC", [0, 1, 2], id="one-paragraph-rewritten-keeps-its-id"),
        pytest.param("ABCD", "AXYD", [0, 1, None, 3], id="run-of-two-first-inherits-second-is-new"),
        pytest.param("ABC", "AXYZC", [0, 1, None, None, 2], id="one-into-three"),
        pytest.param("ABC", "AC", [0, 2], id="deleted"),
        pytest.param("AC", "ABC", [0, None, 1], id="inserted-is-new"),
        pytest.param("ABCDE", "AbCdE", [0, 1, 2, 3, 4], id="unchanged-paragraph-inside-the-range-keeps-its-id"),
        pytest.param("BCD", "BcD", [0, 1, 2], id="range-wider-than-the-change"),
        pytest.param("SXS", "SSSS", [0, 1, None, 2], id="scene-breaks-stay-outside"),
        pytest.param("ASBSC", "ASBC", [0, 1, 2, 4], id="one-of-two-same-paragraphs-deleted"),
        pytest.param("SS", "SSS", [0, 1, None], id="prefix-and-suffix-do-not-overlap-on-growth"),
        pytest.param("SSS", "SS", [0, 1], id="prefix-and-suffix-do-not-overlap-on-shrink"),
        pytest.param("ABC", "XYZ", [0, None, None], id="everything-rewritten"),
    ],
)
def test_inherit_by_text_keeps_outside_ids_in_place_and_gives_each_changed_run_its_first_old_id(
    old: str, new: str, expected: list[int | None]
) -> None:
    """문자 하나가 문단 하나다(같은 문자 = 같은 글). `expected` 는 옛 id 의 위치, None 은 새 id.

    깨지는 시나리오: 장 전체를 한 번에 정렬하면 `SXS→SSSS` 에서 뒤쪽 장면 구분의 id 가 범위 안으로 옮겨 붙고, 같은 글자 첫
    문단 사전 매칭은 같은 문단 둘 중 하나를 지울 때 순서를 뒤집는다. 바뀐 구간에서 승계를 빼면 오탈자만 고친 문단도 id 를
    잃는다."""
    base_ids = _ids(len(old))

    result = blocks.inherit_by_text(list(old), base_ids, list(new))

    assert len(result) == len(new)
    for got, position in zip(result, expected, strict=True):
        if position is None:
            assert got not in base_ids
        else:
            assert got == base_ids[position]
    assert len(set(result)) == len(result)


# ── 위치로 잇기(AI 수정 적용) ────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("old", "first", "last", "replacement", "expected"),
    [
        pytest.param("ABCDE", 1, 2, "X", [0, 1, 3, 4], id="two-into-one"),
        pytest.param("ABCDE", 1, 1, "PQR", [0, 1, None, None, 2, 3, 4], id="one-into-three-tail-moves"),
        pytest.param("ABCDE", 1, 3, "BYD", [0, 1, 2, 3, 4], id="unchanged-inside-the-range"),
        pytest.param("SXS", 1, 1, "SS", [0, 1, None, 2], id="same-text-as-outside"),
        pytest.param("ABC", 0, 0, "X", [0, 1, 2], id="first-paragraph"),
        pytest.param("ABC", 2, 2, "XY", [0, 1, 2, None], id="last-paragraph"),
        pytest.param("ABC", 0, 2, "XYZW", [0, None, None, None], id="whole-chapter"),
    ],
)
def test_inherit_range_keeps_ids_outside_the_jobs_range_by_position(
    old: str, first: int, last: int, replacement: str, expected: list[int | None]
) -> None:
    """깨지는 시나리오: 꼬리 위치를 `last` 하나 어긋나게 잡으면 범위 뒤 문단 id 가 한 칸씩 밀리고, 범위 안을 글자로 맞추지
    않으면 범위를 넉넉히 잡고 한 곳만 고친 수정이 고치지 않은 문단의 id 까지 버린다."""
    base_ids = _ids(len(old))
    paragraphs = [*old[:first], *replacement, *old[last + 1 :]]

    result = blocks.inherit_range(list(old), base_ids, first, last, paragraphs)

    assert len(result) == len(paragraphs)
    for got, position in zip(result, expected, strict=True):
        if position is None:
            assert got not in base_ids
        else:
            assert got == base_ids[position]
    assert len(set(result)) == len(result)


def test_succession_invariants_hold_for_random_range_edits() -> None:
    """무작위 문단(같은 글이 자주 겹치게 작은 글자 모음)과 무작위 연속 범위 교체로 두 승계 함수를 돌린다. 늘 성립해야 하는
    것: id 수 = 새 문단 수, id 가 겹치지 않음, 이어받은 옛 id 는 옛 순서 그대로, 위치 승계는 범위 밖 id 가 제자리. 시드를
    고정해 실패가 재현된다."""
    rng = random.Random(20261022)
    alphabet = "SABC"
    for _ in range(2000):
        old = [rng.choice(alphabet) for _ in range(rng.randint(1, 8))]
        first = rng.randrange(len(old))
        last = rng.randrange(first, len(old))
        replacement = [rng.choice(alphabet) for _ in range(rng.randint(0 if len(old) > 1 else 1, 4))]
        new = [*old[:first], *replacement, *old[last + 1 :]]
        base_ids = _ids(len(old))

        for result in (
            blocks.inherit_by_text(old, base_ids, new),
            blocks.inherit_range(old, base_ids, first, last, new) if replacement else None,
        ):
            if result is None:
                continue
            assert len(result) == len(new), (old, first, last, replacement)
            assert len(set(result)) == len(result), (old, first, last, replacement)
            kept = [base_ids.index(i) for i in result if i in base_ids]
            assert kept == sorted(kept), (old, first, last, replacement)
        if replacement:
            positional = blocks.inherit_range(old, base_ids, first, last, new)
            assert positional[:first] == base_ids[:first]
            assert positional[len(new) - (len(old) - last - 1) :] == base_ids[last + 1 :]


# ── 개정 단위 도우미 ────────────────────────────────────────────────────────
def test_copied_ids_take_the_source_ids() -> None:
    """깨지는 시나리오: 되돌리기가 원본 id 대신 새 id 를 매긴다."""
    source_ids = _ids(2)

    copied = blocks.copied_ids(_revision("가.\n\n나.", source_ids))

    assert copied == source_ids and copied is not source_ids


def test_succession_reads_the_paragraphs_of_the_base_body() -> None:
    """도우미는 본문을 같은 나누기로 나눠 글자·위치 승계에 넘긴다. 공백만 다른 본문은 같은 문단이다."""
    base_ids = _ids(3)
    base = _revision("가.\n\n  \n나.\n\n다.", base_ids)

    assert blocks.succeeding_ids(base, "가.\n\n나.\n\n다.") == base_ids
    assert blocks.succeeding_range_ids(base, 1, 1, "가.\n\n새 나.\n\n또 나.\n\n다.")[::3] == [base_ids[0], base_ids[2]]


def test_requested_ids_are_used_as_sent_and_null_means_a_new_paragraph() -> None:
    base_ids = _ids(3)
    base = _revision("가.\n\n나.\n\n다.", base_ids)

    result = blocks.requested_ids(base, [base_ids[2], None, base_ids[0]], "다.\n\n새.\n\n가.")

    assert (result[0], result[2]) == (base_ids[2], base_ids[0])
    assert result[1] not in base_ids


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("too_short", id="fewer-ids-than-paragraphs"),
        pytest.param("too_long", id="more-ids-than-paragraphs"),
        pytest.param("foreign", id="id-not-in-the-base-revision"),
        pytest.param("duplicate", id="same-id-twice"),
    ],
)
def test_requested_ids_reject_a_list_that_does_not_fit_the_body_or_the_base(case: str) -> None:
    """깨지는 시나리오: 화면이 낡은 목록을 보내 id 가 엉뚱한 문단에 붙거나, 다른 화의 id 가 이 화에 섞이거나, 한 id 가
    두 문단에 붙는다."""
    base_ids = _ids(2)
    base = _revision("가.\n\n나.", base_ids)
    body = "가.\n\n나."
    cases: dict[str, list[uuid.UUID | None]] = {
        "too_short": [base_ids[0]],
        "too_long": [base_ids[0], base_ids[1], None],
        "foreign": [base_ids[0], uuid.uuid4()],
        "duplicate": [base_ids[0], base_ids[0]],
    }
    requested = cases[case]

    with pytest.raises(blocks.BlockIdsInvalidError):
        blocks.requested_ids(base, requested, body)


# ── 쓰기 함수 ───────────────────────────────────────────────────────────────
def test_build_revision_fills_ids_and_the_hash_of_the_normalized_paragraphs() -> None:
    """해시는 문단 배열을 빈 줄 하나로 다시 이은 글의 sha256 이다 — 문단 사이 공백만 다른 본문은 같은 해시다.

    깨지는 시나리오: 원래 본문으로 해시하면 공백만 다른 두 개정이 다른 글로 판정된다."""
    ids = _ids(2)

    revision = blocks.build_revision(body="가.\n\n  \n나.", source="manual_edit", block_ids=ids)

    assert revision.block_ids == ids
    assert revision.content_hash == hashlib.sha256("가.\n\n나.".encode()).hexdigest()
    assert blocks.content_hash("가.\n\n나.") == revision.content_hash


@pytest.mark.parametrize(
    "block_ids",
    [
        pytest.param("short", id="fewer-ids-than-paragraphs"),
        pytest.param("long", id="more-ids-than-paragraphs"),
        pytest.param("duplicate", id="duplicate-id"),
    ],
)
def test_build_revision_refuses_ids_that_break_the_invariant(block_ids: str) -> None:
    """깨지는 시나리오: 새 개정 경로가 문단 수와 다른 id 를 쓰면 블록 i 가 문단 i 가 아니게 된다."""
    one = uuid.uuid4()
    ids = {"short": [one], "long": [one, uuid.uuid4(), uuid.uuid4()], "duplicate": [one, one]}[block_ids]

    with pytest.raises(ValueError):
        blocks.build_revision(body="가.\n\n나.", source="manual_edit", block_ids=ids)


def test_fresh_ids_give_one_new_id_per_paragraph() -> None:
    ids = blocks.fresh_ids("가.\n\n\n나.\n\n다.")

    assert len(ids) == len(split_paragraphs("가.\n\n\n나.\n\n다.")) == len(set(ids))


# ── 개정 행을 만드는 길은 하나 ───────────────────────────────────────────────
_REVISION_COLUMNS_WITH_BODY = {"body", "block_ids", "content_hash"}
_BLOCK_ATTRIBUTES = {"block_ids", "content_hash"}


def _names_revision(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "NovelChapterRevision") or (
        isinstance(node, ast.Attribute) and node.attr == "NovelChapterRevision"
    )


def _targets_revision(call: ast.Call) -> bool:
    return any(_names_revision(arg) for arg in call.args)


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _revision_writes_outside_blocks(source: str) -> list[str]:
    """개정 행을 만들거나 본문·블록 칸을 고치는 코드 자리. `reverted_from_revision_id` 만 비우는 UPDATE 는 허용한다.
    원시 UPDATE 문은 고치는 칸을 가리지 않고 모두 잡는다(허용할 일이 생기면 그 자리를 이 검사에서 따로 뺀다)."""
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = " ".join(node.value.lower().split())
            if "insert into novel_chapter_revisions" in sql or "update novel_chapter_revisions" in sql:
                found.append(f"{node.lineno}: raw SQL")
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Attribute) and t.attr in _BLOCK_ATTRIBUTES for t in targets):
                found.append(f"{node.lineno}: block attribute assignment")
        if not isinstance(node, ast.Call):
            continue
        callee = _callee(node)
        if callee == "NovelChapterRevision":
            found.append(f"{node.lineno}: NovelChapterRevision(...)")
        elif callee in {"insert", "pg_insert"} and _targets_revision(node):
            found.append(f"{node.lineno}: insert(NovelChapterRevision)")
        elif (
            callee == "insert"
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "__table__"
            and _names_revision(node.func.value.value)
        ):
            found.append(f"{node.lineno}: NovelChapterRevision.__table__.insert()")
        elif callee == "values":
            inner = node.func.value if isinstance(node.func, ast.Attribute) else None
            while isinstance(inner, (ast.Call, ast.Attribute)):
                if isinstance(inner, ast.Call) and _callee(inner) == "update" and _targets_revision(inner):
                    keys = {kw.arg for kw in node.keywords}
                    if node.args or None in keys or keys & _REVISION_COLUMNS_WITH_BODY:
                        found.append(f"{node.lineno}: update(NovelChapterRevision).values(...)")
                    break
                inner = inner.func if isinstance(inner, ast.Call) else inner.value
    return found


def test_the_guard_sees_every_way_of_writing_a_revision() -> None:
    """검사 자체의 신호 — 우회 꼴마다 하나씩 잡고, 되돌리기 원본 칸만 비우는 UPDATE 는 통과시킨다."""
    sample = """
NovelChapterRevision(body=b)
models.NovelChapterRevision(body=b)
insert(NovelChapterRevision).values(body=b)
sa.insert(NovelChapterRevision)
update(NovelChapterRevision).where(x).values(body=b)
update(NovelChapterRevision).values(block_ids=None)
update(NovelChapterRevision).values(**changes)
text("INSERT INTO  novel_chapter_revisions (id) VALUES (1)")
pg_insert(models.NovelChapterRevision).values(id=1)
NovelChapterRevision.__table__.insert()
text("UPDATE novel_chapter_revisions SET body = ''")
revision.block_ids = []
update(NovelChapterRevision).where(x).values(reverted_from_revision_id=None)
"""
    lines = sorted(int(line.split(":")[0]) for line in _revision_writes_outside_blocks(sample))
    assert lines == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_only_the_blocks_module_makes_revision_rows() -> None:
    """깨지는 시나리오: 새 경로가 생성자·코어 INSERT·본문을 고치는 UPDATE 로 개정을 쓰면 블록 칸이 비거나 문단과 어긋난다."""
    offenders = {
        str(path.relative_to(_SRC)): found
        for path in sorted(_SRC.rglob("*.py"))
        if path != _SRC / "novelize" / "blocks.py"
        and (found := _revision_writes_outside_blocks(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}
