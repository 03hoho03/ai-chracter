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


# 본문형 거절 판정. 모델이 장 대신 거절·안내문을 쓰면 사용자에게 말을 건네는 높임말 문장(-니다·-요)에 "할 수 없다"
# 류의 말이 함께 나온다. 장 본문은 3인칭 과거형 서술(-었다)이라 높임말은 보통 따옴표 대사 안에만 있지만, 따옴표 없이
# 옮긴 문자·편지·방송 멘트처럼 서술 속에 높임말이 나오는 것도 흔한 소설 관례다. 놓친 거절은 사용자가 재생성·삭제로
# 처리할 수 있지만, 오탐은 몇 분 기다린 결과를 버리고 같은 원문에서 되풀이해 실패하므로 판정은 오탐을 더 피한다.
# 규칙은 `looks_like_refusal` docstring 에 있다.
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”|\'[^\']*\'|‘[^’]*’|「[^」]*」|『[^』]*』')
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…~])\s+|\n")
_POLITE_SENTENCE_END = re.compile(r"(?:니다|세요|까요|어요|아요|해요|에요|예요|죠)[.!?…~]*$")
# 높임이 아닌 "-다" 로 끝나는 문장(-었다·-했다). "-니다" 는 높임이라 빼낸다.
_PLAIN_SENTENCE_END = re.compile(r"(?<!니)다[.!?…~]*$")
_CANNOT = re.compile(r"수\s*(?:가\s*)?없|어렵습니다|어려워요|못\s*합니다|않겠습니다|드리기\s*어렵")
_ENGLISH_REFUSAL = re.compile(r"^\s*(?:I'm sorry|I am sorry|I can(?:no|')t|As an AI)", re.IGNORECASE)


def _is_refusal_paragraph(paragraph: str) -> bool:
    if _ENGLISH_REFUSAL.search(paragraph):
        return True
    narration = _QUOTED.sub("", paragraph)
    sentences = [sentence.strip() for sentence in _SENTENCE_BREAK.split(narration) if sentence.strip()]
    if any(_PLAIN_SENTENCE_END.search(sentence) for sentence in sentences):
        return False
    return any(_POLITE_SENTENCE_END.search(sentence) and _CANNOT.search(sentence) for sentence in sentences)


def looks_like_refusal(paragraphs: Sequence[str]) -> bool:
    """처음 또는 끝 문단이 거절·안내문으로 보이면 참. 한 문단은 다음일 때 거절이다.

    - 영어 거절 머리(I'm sorry·I can't·As an AI)로 시작하면 거절이다.
    - 아니면 따옴표·낫표 대사를 지운다. 대사가 문단 안에서 줄을 바꿔도 짝을 맞춰 통째로 지운다.
    - 남은 서술을 문장으로 나눈다(문장부호 뒤 공백, 또는 줄바꿈). 높임이 아닌 "-다" 로 끝나는 문장이 하나라도 있으면
      소설 서술 문단으로 보고 거절이 아니다 — 따옴표 없이 옮긴 편지·멘트가 섞여 있어도 3인칭 서술이 곁에 있으면
      소설이다.
    - 남은 문장 중 하나가 높임 어미로 끝나고(어미 바로 뒤가 문장부호나 문장 끝일 때만 — "떠돌아다니다 지친" 의
      "니다" 는 세지 않는다) **같은 문장 안에** "수 없"·"어렵습니다" 류가 있으면 거절이다. 높임 문장과 "참을 수
      없었다" 서술이 다른 문장에 따로 있는 것은 세지 않는다.

    가운데 문단은 보지 않는다 — 거절은 장 대신(첫머리) 또는 본문 뒤 안내(끝)로 오고, 가운데까지 보면 따옴표가 빠진
    문단 하나로 멀쩡한 장을 버리게 된다. 놓치는 것: "-다" 서술 뒤에 같은 문단으로 붙인 안내, 높임말이 아닌 거절."""
    if not paragraphs:
        return False
    return _is_refusal_paragraph(paragraphs[0]) or _is_refusal_paragraph(paragraphs[-1])
