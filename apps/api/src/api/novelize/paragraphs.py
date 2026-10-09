"""새로 생성한 화 본문의 긴 문단 재분할 — 글자는 그대로 두고 문단 경계만 옮긴다. DB 를 타지 않는다.

모델은 같은 입력에서도 가끔 대사와 서술을 한 문단에 몰아 쓴 빽빽한 화를 낸다. 문안으로는 이 모드를 확률적으로만 줄일
수 있어서, 생성 직후 코드로 긴 문단만 다시 나눈다. 바꾸는 것은 문단 사이 공백뿐이다 — 공백(스페이스·줄바꿈)을 뺀
글자열은 입력과 언제나 같다.

생성·다시 만들기 결과에만 건다. 직접 수정·AI 수정·되돌리기·스냅숏 복원은 사용자가 고른 문단 모양이나 옛 판을 그대로
옮기는 기능이라 다시 나누면 그 뜻이 깨진다. 이미 저장된 개정에도 소급하지 않는다 — 읽은 자리·판 비교·AI 수정 범위가
문단 번호에 묶여 있다."""

import math
import re

from api.novelize.text import split_paragraphs

# 이 길이(공백 포함 글자 수)를 넘는 문단만 다시 나눈다. 모델이 문단을 잘 나눠 쓴 화에서는 문단의 90% 넘게가 이 길이
# 안에 들어서(시험 생성 표본 실측), 문턱을 낮추면 잘 나뉜 화의 서너 문장짜리 문단까지 쪼개게 된다. 나눈 결과도 이 길이
# 아래를 목표로 한다.
LONG_PARAGRAPH_CHARS = 200

_SENTENCE_END = ".!?…~"
# 여는 따옴표 → 닫는 따옴표. 작은따옴표(속마음)는 대사로 떼어 내지 않지만 그 안에서도 자르지 않는다. 곧은 큰따옴표는
# 여닫는 모양이 같아 따로 다룬다.
_CLOSER = {"“": "”", "「": "」", "『": "』", "‘": "’"}
_DIALOGUE_OPENERS = {"“", "「", "『", '"'}
# 닫는 따옴표 뒤 다음 어절이 이것으로 시작하면 대사와 한 문장이다("…" 하고 말했다). 여기서 자르면 화법 동사가 주어 없이
# 홀로 남는다. 따옴표에 붙여 쓴 조사("…"라며)는 공백이 없어 애초에 자를 자리가 아니다.
_ATTRIBUTION = (
    "하고",
    "하며",
    "하면서",
    "하자",
    "하는",
    "하던",
    "하듯",
    "했다",
    "라고",
    "라며",
    "라는",
    "라던",
    "이라고",
    "이라며",
    "이라는",
    "이라던",
)
_WHITESPACE_RUN = re.compile(r"\s+")


def resplit_long_paragraphs(body: str) -> str:
    """`clean_chapter_body` 결과(문단 사이 빈 줄 하나)에서 `LONG_PARAGRAPH_CHARS` 를 넘는 문단만 다시 나눈다.

    - 따옴표 대사 문장은 홀로 한 문단이 된다. 닫는 따옴표 뒤에 화법 동사·조사가 이어지면 대사와 그 꼬리를 떼지 않는다.
    - 대사 사이 서술이 여전히 문턱보다 길면 문장 끝에서 나눠 조각이 문턱을 넘지 않게 하되, 조각 길이를 고르게 한다.
    - 따옴표 안에서는 자르지 않는다. 짝이 안 맞는 따옴표가 있으면 그 뒤로는 자르지 않는다(대사 한가운데를 자를 수
      있어서다). 문장 끝이 없는 긴 문장·긴 대사는 문턱을 넘은 채 남는다.
    - 문턱 이하 문단과 문단 경계(장면 전환 포함)는 그대로다. 문단 사이를 합치는 일은 없다."""
    paragraphs = split_paragraphs(body)
    if all(len(paragraph) <= LONG_PARAGRAPH_CHARS for paragraph in paragraphs):
        return body
    out: list[str] = []
    for paragraph in paragraphs:
        out.extend(_resplit(paragraph) if len(paragraph) > LONG_PARAGRAPH_CHARS else [paragraph])
    return "\n\n".join(out)


def _resplit(paragraph: str) -> list[str]:
    units = _sentence_units(paragraph)
    pieces: list[str] = []
    narration: list[tuple[int, int]] = []
    for start, end in units:
        if _is_dialogue(paragraph[start:end]):
            pieces.extend(_pack(paragraph, narration))
            narration = []
            pieces.append(paragraph[start:end])
        else:
            narration.append((start, end))
    pieces.extend(_pack(paragraph, narration))
    return pieces


def _sentence_units(paragraph: str) -> list[tuple[int, int]]:
    """문단을 자를 수 있는 자리(따옴표 밖 공백 중 문장 끝 뒤·줄바꿈)에서 나눈 (시작, 끝) 구간들. 구간은 공백으로 시작하거나
    끝나지 않고, 구간 사이에는 공백만 있다."""
    units: list[tuple[int, int]] = []
    start = 0
    open_quotes: list[str] = []
    position = 0
    for match in _WHITESPACE_RUN.finditer(paragraph):
        for char in paragraph[position : match.start()]:
            _track_quote(open_quotes, char)
        position = match.start()
        if not open_quotes and _can_cut(paragraph, match.start(), match.group(), paragraph[match.end() :]):
            units.append((start, match.start()))
            start = match.end()
    units.append((start, len(paragraph)))
    return units


def _track_quote(open_quotes: list[str], char: str) -> None:
    if open_quotes and char == open_quotes[-1]:
        open_quotes.pop()
    elif char in _CLOSER:
        open_quotes.append(_CLOSER[char])
    elif char == '"':
        open_quotes.append('"')


def _can_cut(paragraph: str, gap_start: int, gap: str, rest: str) -> bool:
    before = paragraph[:gap_start]
    closes_quote = before[-1:] in {"”", "」", "』", '"'}
    ends_sentence = before[-1:] in _SENTENCE_END or (closes_quote and before[-2:-1] in _SENTENCE_END)
    if not (ends_sentence or "\n" in gap):
        return False
    return not (closes_quote and rest.startswith(_ATTRIBUTION))


def _is_dialogue(unit: str) -> bool:
    opener = unit[:1]
    if opener not in _DIALOGUE_OPENERS:
        return False
    return unit[-1:] == _CLOSER.get(opener, '"') and len(unit) > 1


def _pack(paragraph: str, units: list[tuple[int, int]]) -> list[str]:
    """이어진 서술 문장 구간들을 문턱 이하 조각으로 묶는다. 조각 수를 최소로 잡고 그 수로 고르게 나눈 길이에 닿으면 끊어,
    문턱 바로 아래 조각 뒤에 짧은 꼬리가 남는 것을 줄인다. 조각 안의 원래 공백은 그대로 둔다."""
    if not units:
        return []
    total = units[-1][1] - units[0][0]
    target = total / math.ceil(total / LONG_PARAGRAPH_CHARS)
    pieces: list[str] = []
    piece_start: int | None = None
    previous_end = units[0][0]
    for start, end in units:
        if piece_start is None:
            piece_start = start
        elif end - piece_start > LONG_PARAGRAPH_CHARS:
            pieces.append(paragraph[piece_start:previous_end])
            piece_start = start
        previous_end = end
        if end - piece_start >= target:
            pieces.append(paragraph[piece_start:end])
            piece_start = None
    if piece_start is not None:
        pieces.append(paragraph[piece_start:previous_end])
    return pieces
