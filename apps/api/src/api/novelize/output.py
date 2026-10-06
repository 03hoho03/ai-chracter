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

파서는 엄격하다. 머리 줄 꼴, 1부터 이어지는 화 번호, 필드 세 줄의 이름과 순서, `---` 구분 줄 중 하나라도 어긋나면
`MalformedOutputError` 다 — 형식이 어긋난 출력은 화 경계·제목·요약을 믿을 수 없어, 고쳐 읽다가 남의 화에 본문이 붙는
것보다 실패·환불이 낫다. 너그러운 곳은 셋뿐이다: 줄 앞뒤 공백, 구조 줄 사이의 빈 줄(모델이 흔히 넣고 뜻이 없다),
등장인물 목록이 빈 것(이름 없는 인물만 나온 화가 있다). 본문 후처리(턴 표시 걷기·문단 다시 잇기)와 최소 길이·거절
판정은 여기서 하지 않고 호출부가 화마다 한다 — 후처리가 빈 줄을 접기 전에 구조를 읽어야 한다."""

import re
from dataclasses import dataclass

_NOVEL_TITLE_HEADER = "===소설 제목==="
_EPISODE_HEADER = re.compile(r"^===(\d+)화===$")
_SEPARATOR = "---"
_FIELDS = ("제목", "요약", "등장인물")


class MalformedOutputError(Exception):
    """출력이 구분자 형식이 아니다. 메시지는 어디서 어긋났는지다(로그용 — 출력 본문은 싣지 않는다)."""


@dataclass(frozen=True)
class ParsedEpisode:
    title: str
    summary: str
    characters: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class ParsedBatch:
    novel_title: str | None
    episodes: tuple[ParsedEpisode, ...]


def _is_structural(line: str) -> bool:
    """본문에 나오면 안 되는 줄 — 지시문이 본문에 `===`·`---` 로 시작하는 줄을 쓰지 말라고 한다."""
    return line.startswith("===") or line.startswith(_SEPARATOR)


def _split_names(raw: str) -> tuple[str, ...]:
    names: list[str] = []
    for part in raw.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def parse_batch_output(text: str) -> ParsedBatch:
    raw_lines = text.splitlines()
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
    if pos < len(lines) and lines[pos] == _NOVEL_TITLE_HEADER:
        pos += 1
        novel_title = take("소설 제목")
        if not novel_title or _is_structural(novel_title):
            raise MalformedOutputError("소설 제목 줄이 비었거나 머리 줄이다")

    episodes: list[ParsedEpisode] = []
    skip_blank()
    while pos < len(lines):
        header = _EPISODE_HEADER.match(lines[pos])
        if header is None:
            raise MalformedOutputError(f"{len(episodes) + 1}화 머리 줄이 있어야 할 자리다")
        if int(header.group(1)) != len(episodes) + 1:
            raise MalformedOutputError(f"화 번호가 {len(episodes) + 1} 이어야 하는데 {header.group(1)} 이다")
        pos += 1
        values: list[str] = []
        for field in _FIELDS:
            line = take(field)
            name, colon, value = line.partition(":")
            if not colon or name.strip() != field:
                raise MalformedOutputError(f"{len(episodes) + 1}화의 {field} 줄이 아니다")
            values.append(value.strip())
        title, summary, characters = values
        if not title or not summary:
            raise MalformedOutputError(f"{len(episodes) + 1}화의 제목이나 요약이 비었다")
        if take("구분 줄") != _SEPARATOR:
            raise MalformedOutputError(f"{len(episodes) + 1}화 필드 뒤에 구분 줄이 없다")
        body_lines: list[str] = []
        while pos < len(lines) and _EPISODE_HEADER.match(lines[pos]) is None:
            if _is_structural(lines[pos]):
                raise MalformedOutputError(f"{len(episodes) + 1}화 본문에 머리 줄 꼴의 줄이 있다")
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
