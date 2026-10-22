"""화 개정의 블록 — 본문 문단(`split_paragraphs`)마다 붙는 id 와 본문 해시. DB 를 타지 않는다.

블록 i 는 문단 i 다. id 는 개정이 바뀌어도 같은 문단을 가리키도록 앞 개정에서 이어받는다:
- 생성·다시 만들기: 전부 새 id(새 본문을 통째로 받았으니 이을 근거가 없다).
- 되돌리기·스냅숏 복원: 되돌린 원본 개정의 id 를 그대로 복제한다(지금 개정의 id 가 아니다).
- 범위 편집(직접 수정·AI 수정 적용): 글자가 같은 문단은 id 를 그대로 두고, 바뀐 구간마다 그 구간의 첫 새 문단이 그 구간의
  첫 옛 id 를 잇는다(나머지는 새 id). 오탈자 하나 고친 문단이 id 를 잃지 않고, 한 문단을 여럿으로 나누면 첫 문단이 잇는다.
  직접 수정은 화면이 문단마다 id 를 실어 보낼 수 있고, 싣지 않으면 서버가 옛 본문과 같은 앞부분·뒷부분을 걷어 바뀐 범위를
  되찾는다 — 화면의 편집은 연속 범위 하나를 바꾸므로 바깥 문단은 늘 제자리 id 를 받는다. 장 전체를 한 번에 정렬하지 않는
  이유는, 같은 글자 문단(`* * *` 같은 장면 구분)이 여럿이면 바깥 문단의 id 가 범위 안으로 옮겨 붙기 때문이다. AI 수정 적용은
  작업이 범위를 알아 위치로 계산한다.
이을 앞 개정에 id 가 없으면(이 칸이 생기기 전 이미지가 쓴 행) 전부 새 id 다.

개정 행은 `build_revision` 하나로만 만든다 — id 수 = 문단 수, id 가 겹치지 않음을 여기서 지키고 해시를 계산한다(테스트가
`src/` 의 다른 자리에서 개정을 만들지 않는지 구조로 검사한다)."""

import hashlib
import uuid
from collections.abc import Sequence
from difflib import SequenceMatcher

from api.db.models.novel import NovelChapterRevision, NovelRevisionSource
from api.novelize.text import split_paragraphs


class BlockIdsInvalidError(ValueError):
    """직접 수정 요청이 실은 블록 id 목록이 본문 문단이나 기준 개정과 맞지 않는다."""


def content_hash(body: str) -> str:
    """문단 배열을 빈 줄 하나로 다시 이은 글의 sha256 hex. 문단 배열이 같으면 해시도 같다 — 문단 사이 공백 차이는 들지
    않는다(문단은 빈 줄을 품을 수 없어 다시 이은 글에서 배열이 하나로 정해진다)."""
    return hashlib.sha256("\n\n".join(split_paragraphs(body)).encode("utf-8")).hexdigest()


def _fresh(count: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


def fresh_ids(body: str) -> list[uuid.UUID]:
    return _fresh(len(split_paragraphs(body)))


def copied_ids(source: NovelChapterRevision) -> list[uuid.UUID]:
    if source.block_ids is None:
        return fresh_ids(source.body)
    return list(source.block_ids)


def _inherit_runs(
    base_paragraphs: Sequence[str], base_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> list[uuid.UUID]:
    """글자가 같은 문단은 id 를 잇고, 바뀐 구간마다 첫 새 문단이 그 구간의 첫 옛 id 를 잇는다. 범위 안끼리만 부른다."""
    ids: list[uuid.UUID] = []
    matcher = SequenceMatcher(None, list(base_paragraphs), list(paragraphs), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ids.extend(base_ids[i1:i2])
        elif tag == "replace":
            ids.append(base_ids[i1])
            ids.extend(_fresh(j2 - j1 - 1))
        elif tag == "insert":
            ids.extend(_fresh(j2 - j1))
    return ids


def inherit_by_text(
    base_paragraphs: Sequence[str], base_ids: Sequence[uuid.UUID], paragraphs: Sequence[str]
) -> list[uuid.UUID]:
    """옛 문단·id 와 새 문단에서 새 id. 같은 앞부분·뒷부분(서로 겹치지 않게)을 걷어 바뀐 범위를 되찾고 그 안만 맞춘다."""
    limit = min(len(base_paragraphs), len(paragraphs))
    head = 0
    while head < limit and base_paragraphs[head] == paragraphs[head]:
        head += 1
    tail = 0
    while tail < limit - head and base_paragraphs[-1 - tail] == paragraphs[-1 - tail]:
        tail += 1
    base_end = len(base_paragraphs) - tail
    middle = _inherit_runs(base_paragraphs[head:base_end], base_ids[head:base_end], paragraphs[head : len(paragraphs) - tail])
    return [*base_ids[:head], *middle, *base_ids[base_end:]]


def inherit_range(
    base_paragraphs: Sequence[str], base_ids: Sequence[uuid.UUID], first: int, last: int, paragraphs: Sequence[str]
) -> list[uuid.UUID]:
    """옛 문단 `first..last`(양 끝 포함)를 바꾼 새 문단에서 새 id. 범위 밖은 위치 그대로다."""
    after = len(base_paragraphs) - last - 1
    middle = _inherit_runs(
        base_paragraphs[first : last + 1], base_ids[first : last + 1], paragraphs[first : len(paragraphs) - after]
    )
    return [*base_ids[:first], *middle, *base_ids[last + 1 :]]


def succeeding_ids(base: NovelChapterRevision, body: str) -> list[uuid.UUID]:
    """직접 수정에서 화면이 id 를 싣지 않았을 때 — 기준 개정과 글자로 맞춘다."""
    if base.block_ids is None:
        return fresh_ids(body)
    return inherit_by_text(split_paragraphs(base.body), base.block_ids, split_paragraphs(body))


def succeeding_range_ids(base: NovelChapterRevision, first: int, last: int, body: str) -> list[uuid.UUID]:
    """AI 수정 적용 — 잠근 현재 개정(`base`)의 id 와 작업의 문단 범위로 계산한다."""
    if base.block_ids is None:
        return fresh_ids(body)
    return inherit_range(split_paragraphs(base.body), base.block_ids, first, last, split_paragraphs(body))


def requested_ids(base: NovelChapterRevision, requested: Sequence[uuid.UUID | None], body: str) -> list[uuid.UUID]:
    """직접 수정 요청이 문단마다 실은 id(`None` = 새 문단)를 검증해 새 id 로 바꾼다. 문단 수와 다르거나, 기준 개정에 없는
    id 이거나, 같은 id 가 둘이면 `BlockIdsInvalidError`."""
    known = set(base.block_ids or [])
    sent = [block_id for block_id in requested if block_id is not None]
    if len(requested) != len(split_paragraphs(body)) or len(set(sent)) != len(sent) or not known.issuperset(sent):
        raise BlockIdsInvalidError
    return [block_id if block_id is not None else uuid.uuid4() for block_id in requested]


def build_revision(
    *,
    body: str,
    source: NovelRevisionSource,
    block_ids: Sequence[uuid.UUID],
    chapter_id: uuid.UUID | None = None,
    revision_no: int | None = None,
    reverted_from_revision_id: uuid.UUID | None = None,
) -> NovelChapterRevision:
    """개정 행 하나(세션에 넣는 것은 호출자, 화·번호는 나중에 정해도 된다). id 수가 문단 수와 다르거나 겹치면 `ValueError`."""
    ids = list(block_ids)
    if len(ids) != len(split_paragraphs(body)) or len(set(ids)) != len(ids):
        raise ValueError("블록 id 는 문단마다 하나씩, 겹치지 않아야 한다")
    return NovelChapterRevision(
        chapter_id=chapter_id,
        revision_no=revision_no,
        body=body,
        source=source,
        reverted_from_revision_id=reverted_from_revision_id,
        block_ids=ids,
        content_hash=content_hash(body),
    )
