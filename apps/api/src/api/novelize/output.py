"""생성 출력(묶음 하나)의 구분자 형식 파서. DB 를 타지 않는다.

형식은 생성 지시문의 「출력 형식」과 같은 글자다.

    ===소설 제목===          ← 그 묶음이 소설 제목을 쓸 때만
    <한 줄>
    ===1화===
    제목: <한 줄>
    요약: <한 줄>
    등장인물: <이름>, <이름>
    ---
    <본문 문단들>
    ===2화===
    …

파서는 경계에서 엄격하다. 1부터 이어지는 화 번호, 필드 세 줄의 이름과 순서, 구분 줄 중 하나라도 어긋나면
`MalformedOutputError` 다 — 형식이 어긋난 출력은 화 경계·제목·요약을 믿을 수 없어, 고쳐 읽다가 남의 화에 본문이 붙는
것보다 실패·환불이 낫다. 대신 경계 판단을 흐리지 않는 장식은 받는다. 모델이 흔히 붙이는데 어느 줄이 머리 줄인지는
그대로 드러나서, 장식 때문에 묶음 전체를 환불하면 원가만 버린다.
- 줄 앞뒤 공백, 구조 줄 사이의 빈 줄
- 출력 맨 앞·맨 뒤의 코드 펜스(```) 줄
- 구조 줄(머리 줄·구분 줄·필드 줄) 앞뒤의 `*`·`#`(굵게·제목 마크다운), 머리 줄 `=` 개수와 안쪽 공백(`=== 1 화 ===`)
- 필드 구분자 `:`·`：`, 필드 이름 앞뒤의 `**`
- 필드 이름(`제목:` 등)을 빼고 값만 쓴 필드 줄. gemini-3.8-flash 가 같은 입력에서 이따금 세 필드 모두 이렇게 쓴다. 머리
  줄과 구분 줄 사이의 세 줄이라 자리로 읽어도 경계는 그대로다. 다만 구조 줄이나 다른 필드 이름이 붙은 줄은 그 자리의
  값으로 받지 않고(필드가 빠졌거나 순서가 바뀐 것이다), 이름 없는 제목이 화 제목 상한보다 길면 본문 문단이 올라온
  것으로 본다
- 본문 안의 `---`·`***` 단독 줄(장면 전환 — 빈 줄로 바꾼다)
- 등장인물 목록이 빈 것(이름 없는 인물만 나온 화가 있다)

본문 후처리(턴 표시 걷기·문단 다시 잇기)와 최소 길이·거절 판정은 여기서 하지 않고 호출부가 화마다 한다 — 후처리가
빈 줄을 접기 전에 구조를 읽어야 한다."""

import re
from dataclasses import dataclass

from api.novelize.schemas import CHAPTER_TITLE_MAX_LENGTH

_NOVEL_TITLE_HEADER = re.compile(r"^=+\s*소설\s*제목\s*=+$")
_EPISODE_HEADER = re.compile(r"^=+\s*(\d+)\s*화\s*=+$")
_SEPARATOR = "---"
# 본문 안 장면 전환 줄. 구분 줄과 같은 글자라도 화 본문 안이면 경계가 아니다(경계는 머리 줄이 정한다).
_SCENE_BREAK = re.compile(r"^(?:-{3,}|\*{3,})$")
_FENCE = "```"
_DECORATION = "*# \t"
_FIELDS = ("제목", "요약", "등장인물")


class MalformedOutputError(Exception):
    """출력이 구분자 형식이 아니다. 메시지는 어디서 어긋났는지다(로그용 — 출력 본문은 싣지 않는다)."""


@dataclass(frozen=True)
class ParsedEpisode:
    """제목·요약이 None 인 것은 구분자 형식이 아닌 옛 형식 출력을 화 하나로 받은 경우뿐이다(`runner.py`)."""

    title: str | None
    summary: str | None
    characters: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class ParsedBatch:
    novel_title: str | None
    episodes: tuple[ParsedEpisode, ...]


def _bare(line: str) -> str:
    """구조 판정용 줄 — 앞뒤 공백과 마크다운 장식(`*`·`#`)을 걷는다."""
    return line.strip().strip(_DECORATION)


def _is_structural(line: str) -> bool:
    """본문에 나오면 안 되는 줄 — 지시문이 본문에 `===`·`---` 로 시작하는 줄을 쓰지 말라고 한다. 장면 전환 단독 줄은
    호출 전에 걸러진다."""
    return _bare(line).startswith("===") or line.strip().startswith(_SEPARATOR)


def has_structure_lines(text: str) -> bool:
    """`===` 로 시작하는 구조 줄이 하나라도 있는가. 하나도 없으면 모델이 구분자 형식을 아예 쓰지 않은 것이다."""
    return any(_bare(line).startswith("===") for line in text.splitlines())


def _field(line: str, name: str) -> str | None:
    """`name: 값` 꼴이면 값, 아니면 None. 구분자는 `:`·`：` 둘 다, 이름 앞뒤의 `**` 와 값 앞뒤의 `*` 는 걷는다."""
    head, colon, value = line.strip().strip("#").partition(":")
    if not colon:
        head, colon, value = line.strip().strip("#").partition("：")
    if not colon or head.strip().strip("*").strip() != name:
        return None
    return value.strip().strip("*").strip()


def _unlabeled_field(line: str, name: str) -> str | None:
    """필드 이름 없이 값만 쓴 줄이면 그 값, 아니면 None(모듈 docstring 의 장식 목록 참고)."""
    if _is_structural(line) or any(_field(line, other) is not None for other in _FIELDS):
        return None
    value = _bare(line)
    if name == "제목" and len(value) > CHAPTER_TITLE_MAX_LENGTH:
        return None
    return value


def _shape(line: str) -> str:
    """어긋난 줄의 모양 — 로그에 싣는 값이라 줄의 글자는 담지 않는다."""
    if _is_structural(line):
        return "구조 줄"
    if any(_field(line, other) is not None for other in _FIELDS):
        return "다른 필드 줄"
    return f"이름 없는 {len(_bare(line))}자 줄"


def _split_names(raw: str) -> tuple[str, ...]:
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def parse_batch_output(text: str) -> ParsedBatch:
    raw_lines = text.splitlines()
    # 출력 맨 앞·맨 뒤의 코드 펜스 줄은 버린다(빈 줄을 건너 첫·마지막 줄만).
    nonblank = [i for i, line in enumerate(raw_lines) if line.strip()]
    if nonblank and raw_lines[nonblank[-1]].strip().startswith(_FENCE):
        raw_lines = raw_lines[: nonblank[-1]]
    if nonblank and nonblank[0] < len(raw_lines) and raw_lines[nonblank[0]].strip().startswith(_FENCE):
        raw_lines = raw_lines[nonblank[0] + 1 :]
    # 구조 판정은 앞뒤 공백을 걷은 줄로 하고, 본문은 원래 줄을 그대로 모은다.
    lines = [line.strip() for line in raw_lines]
    pos = 0

    def skip_blank() -> None:
        nonlocal pos
        while pos < len(lines) and not lines[pos]:
            pos += 1

    def take(what: str) -> str:
        nonlocal pos
        skip_blank()
        if pos >= len(lines):
            raise MalformedOutputError(f"{what} 자리에서 출력이 끝났다")
        line = lines[pos]
        pos += 1
        return line

    novel_title: str | None = None
    skip_blank()
    if pos < len(lines) and _NOVEL_TITLE_HEADER.match(_bare(lines[pos])):
        pos += 1
        novel_title = _bare(take("소설 제목"))
        if not novel_title or _is_structural(novel_title):
            raise MalformedOutputError("소설 제목 줄이 비었거나 머리 줄이다")

    episodes: list[ParsedEpisode] = []
    skip_blank()
    while pos < len(lines):
        header = _EPISODE_HEADER.match(_bare(lines[pos]))
        if header is None:
            raise MalformedOutputError(f"{len(episodes) + 1}화 머리 줄이 있어야 할 자리다")
        if int(header.group(1)) != len(episodes) + 1:
            raise MalformedOutputError(f"화 번호가 {len(episodes) + 1} 이어야 하는데 {header.group(1)} 이다")
        pos += 1
        values: list[str] = []
        for field in _FIELDS:
            line = take(field)
            value = _field(line, field)
            if value is None:
                value = _unlabeled_field(line, field)
            if value is None:
                raise MalformedOutputError(f"{len(episodes) + 1}화의 {field} 줄이 아니다({_shape(line)})")
            values.append(value)
        title, summary, characters = values
        if not title or not summary:
            raise MalformedOutputError(f"{len(episodes) + 1}화의 제목이나 요약이 비었다")
        if _bare(take("구분 줄")) != _SEPARATOR:
            raise MalformedOutputError(f"{len(episodes) + 1}화 필드 뒤에 구분 줄이 없다")
        body_lines: list[str] = []
        while pos < len(lines) and _EPISODE_HEADER.match(_bare(lines[pos])) is None:
            if _SCENE_BREAK.match(lines[pos]):
                body_lines.append("")
            elif _is_structural(lines[pos]):
                raise MalformedOutputError(f"{len(episodes) + 1}화 본문에 머리 줄 꼴의 줄이 있다")
            else:
                body_lines.append(raw_lines[pos])
            pos += 1
        episodes.append(
            ParsedEpisode(
                title=title,
                summary=summary,
                characters=_split_names(characters),
                body="\n".join(body_lines).strip(),
            )
        )
    if not episodes:
        raise MalformedOutputError("화가 하나도 없다")
    return ParsedBatch(novel_title=novel_title, episodes=tuple(episodes))
