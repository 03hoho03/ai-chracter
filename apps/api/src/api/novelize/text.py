"""소설 본문 텍스트 처리 — 문단 나누기, 직전 장 끝 발췌, 장 본문 후처리, 본문형 거절 판정. DB 를 타지 않는다.

문단은 빈 줄로 나눈 덩어리다. 화면의 문단 선택·AI 수정의 문단 범위·직전 장 발췌가 모두 이 나누기 하나를 쓴다 — 서로
다르게 나누면 사용자가 고른 문단과 모델이 고친 문단이 어긋난다."""

import re
from collections.abc import Sequence

_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")
# 원문 줄 앞에 붙였던 턴 표시. 모델이 본문에 옮겨 적으면 표시만 걷어 낸다 — 그 줄의 글은 장 본문이다.
_TURN_MARKER = re.compile(r"\[턴\s*\d+\][ \t]*")


def split_paragraphs(body: str) -> list[str]:
    """빈 줄(공백만 있는 줄 포함)로 나눈 문단 목록. 앞뒤 공백을 걷고 빈 문단은 버린다. 문단 안의 줄바꿈 하나는 둔다."""
    return [paragraph.strip() for paragraph in _BLANK_LINE.split(body) if paragraph.strip()]


def ending_excerpt(body: str, target_chars: int) -> str:
    """직전 장의 끝 발췌 — 마지막 문단부터 거꾸로 문단을 더해, 이은 길이가 `target_chars` 에 가장 가까운 묶음.
    문단 중간에서 자르지 않는다(마지막 문단 하나가 목표보다 길어도 통째로 낸다). 문장 중간에서 끊긴 발췌는 다음 장이
    그 문장을 이어 쓰려 들 수 있다."""
    paragraphs = split_paragraphs(body)
    best = ""
    best_gap: int | None = None
    for count in range(1, len(paragraphs) + 1):
        candidate = "\n\n".join(paragraphs[-count:])
        gap = abs(len(candidate) - target_chars)
        if best_gap is None or gap < best_gap:
            best, best_gap = candidate, gap
    return best


def clean_chapter_body(text: str) -> str:
    """모델이 낸 장 본문의 후처리 — 새어 나온 턴 표시를 걷고 문단을 빈 줄 하나로 다시 잇는다. 턴 표시가 나온 것은
    실패로 보지 않는다(글은 쓸 만하고, 표시만 원문 입력 형식이 묻어난 것이다)."""
    without_markers = _TURN_MARKER.sub("", text)
    return "\n\n".join(split_paragraphs(_EXTRA_BLANK_LINES.sub("\n\n", without_markers)))


# 본문형 거절 판정. 모델이 장 대신 거절·안내문을 쓰면 문장이 사용자에게 말을 건네는 높임말(-니다·-요)로 끝나고
# "할 수 없다" 류의 말이 함께 나온다. 장 본문은 3인칭 과거형 서술(-었다)이고 높임말은 큰따옴표 대사 안에만 나오므로,
# 대사를 지운 서술 부분에 "높임말 문장 + 불가 표현"이 함께 있으면 거절로 본다. 거절은 장의 첫머리(장 대신 거절)나
# 끝(본문 뒤에 붙인 안내)에 오므로 처음과 끝 문단만 본다 — 가운데 문단까지 보면 대사 따옴표가 빠진 문단 하나로
# 멀쩡한 장을 버리게 된다.
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|\'[^\'\n]*\'|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』')
_POLITE_SENTENCE_END = re.compile(r"(?:니다|세요|까요|어요|아요|해요|에요|예요|죠)[.!?…~]*(?=\s|$)")
_CANNOT = re.compile(r"수\s*(?:가\s*)?없|어렵습니다|어려워요|못\s*합니다|않겠습니다|드리기\s*어렵")
_ENGLISH_REFUSAL = re.compile(r"^\s*(?:I'm sorry|I am sorry|I can(?:no|')t|As an AI)", re.IGNORECASE)


def _is_refusal_paragraph(paragraph: str) -> bool:
    if _ENGLISH_REFUSAL.search(paragraph):
        return True
    narration = _QUOTED.sub("", paragraph)
    return bool(_POLITE_SENTENCE_END.search(narration) and _CANNOT.search(narration))


def looks_like_refusal(paragraphs: Sequence[str]) -> bool:
    """처음 또는 끝 문단이 거절·안내문으로 보이면 참."""
    if not paragraphs:
        return False
    return _is_refusal_paragraph(paragraphs[0]) or _is_refusal_paragraph(paragraphs[-1])
