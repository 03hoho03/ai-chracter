"""미디어 북 이미지 태그를 읽고 바꾸는 순수 함수.

태그는 두 형태다.
- 이름 형태 `{{img::인물/장면}}` — 작성자가 빌더 글(시작상황·프롤로그·에필로그·등록 설명)에 쓰는 형태.
  인물·장면 이름에는 `/` 가 들어갈 수 없어 슬래시가 정확히 하나다.
- id 형태 `{{img::<칸 entity_id>}}` — 화면으로 나가는 글과 방에 복사된 첫 메시지의 형태. 칸 id 는 버전이
  바뀌어도 유지되므로 방이 새 발행본으로 옮겨 가도 같은 칸을 가리킨다.

둘 중 어느 것도 아닌 `{{…}}`(슬래시 없는 이름, 슬래시 둘, 닫히지 않은 태그, `{{user}}` 같은 다른 문법)는
태그가 아니라 글이다 — 손대지 않는다.

태그를 지운 자리: 태그가 지워져 공백만 남은 줄은 줄째 없앤다. 그 줄 때문에 빈 줄이 겹치면 하나로 접고, 글의
처음·끝에 닿으면 빈 줄도 함께 없앤다. 태그와 무관하게 원래 있던 빈 줄 연속은 그대로 둔다 — 작성자가 일부러
띄운 간격까지 바꾸면 안 된다.
"""

import re
import unicodedata
import uuid
from collections.abc import Callable, Mapping

_TAG = re.compile(r"\{\{img::([^{}]*)\}\}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _normalize_name(name: str) -> str:
    """빌더가 이름을 저장할 때와 같은 규칙(앞뒤 공백 제거 + NFC) — 맥 파일명처럼 NFD 로 온 이름도 같게 본다."""
    return unicodedata.normalize("NFC", name.strip())


def _id_tag(cell_id: uuid.UUID) -> str:
    return "{{img::" + str(cell_id) + "}}"


def _parse(body: str) -> uuid.UUID | tuple[str, str] | None:
    """태그 본문을 칸 id 또는 (인물, 장면) 이름 쌍으로 읽는다. 태그가 아니면 None."""
    stripped = body.strip()
    if _UUID.fullmatch(stripped):
        return uuid.UUID(stripped)
    if body.count("/") == 1:
        person, scene = body.split("/")
        return _normalize_name(person), _normalize_name(scene)
    return None


def _rewrite(text: str, replace: Callable[[uuid.UUID | tuple[str, str]], str | None]) -> str:
    """태그마다 `replace` 를 불러 바꾼다(None 이면 지운다). 지워서 비게 된 줄은 모듈 docstring 의 규칙으로 정리한다."""
    if "{{img::" not in text:
        return text

    lines: list[tuple[str, bool]] = []  # (줄, 태그를 지워서 비게 된 줄인가)
    for line in text.split("\n"):
        deleted = False

        def substitute(match: re.Match[str]) -> str:
            nonlocal deleted
            parsed = _parse(match.group(1))
            if parsed is None:
                return match.group(0)
            replacement = replace(parsed)
            if replacement is None:
                deleted = True
                return ""
            return replacement

        rewritten = _TAG.sub(substitute, line)
        lines.append((rewritten, deleted and rewritten.strip() == ""))

    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index][0]
        if line.strip() != "":
            result.append(line)
            index += 1
            continue
        end = index
        while end < len(lines) and lines[end][0].strip() == "":
            end += 1
        run = lines[index:end]
        if not any(emptied for _, emptied in run):
            result.extend(line for line, _ in run)
        elif index != 0 and end != len(lines) and any(not emptied for _, emptied in run):
            result.append("")
        index = end
    return "\n".join(result)


def normalize_media_tags(
    text: str, cells_by_name: Mapping[tuple[str, str], uuid.UUID]
) -> tuple[str, set[uuid.UUID]]:
    """이름 형태 태그를 칸 id 형태로 바꾸고, 글이 가리키는 칸 id 집합을 함께 돌려준다.

    `cells_by_name` 은 (인물 이름, 장면 이름) → 칸 entity_id 이다. 없는 이름의 태그는 지운다 — 화면은 원문
    대신 빈칸을 보여 준다. id 형태 태그는 그 칸이 `cells_by_name` 에 있으면 정규형으로 남기고 없으면 지운다
    (작성자가 id 형태를 붙여 넣었더라도 없는 칸은 이름 형태와 같게 다룬다)."""
    by_name = {(_normalize_name(person), _normalize_name(scene)): cell_id for (person, scene), cell_id in cells_by_name.items()}
    known_ids = set(by_name.values())
    referenced: set[uuid.UUID] = set()

    def replace(parsed: uuid.UUID | tuple[str, str]) -> str | None:
        cell_id = parsed if isinstance(parsed, uuid.UUID) else by_name.get(parsed)
        if cell_id is None or cell_id not in known_ids:
            return None
        referenced.add(cell_id)
        return _id_tag(cell_id)

    return _rewrite(text, replace), referenced


def strip_media_tags(text: str) -> str:
    """두 형태의 태그를 모두 지운다 — 모델로 가는 사본과 맵 없이 나가는 화면 글에 쓴다."""
    return _rewrite(text, lambda _: None)


def media_tag_refs(text: str) -> set[uuid.UUID]:
    """글에 든 id 형태 태그의 칸 id 집합. 이름 형태는 세지 않는다."""
    refs: set[uuid.UUID] = set()
    for match in _TAG.finditer(text):
        parsed = _parse(match.group(1))
        if isinstance(parsed, uuid.UUID):
            refs.add(parsed)
    return refs
