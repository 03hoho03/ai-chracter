"""조감독 응답 한 턴을 글자 규칙으로 재는 순수 함수 모음. LLM·DB·파일 없음.

정의는 스토리 가이드 런이 결과를 보기 전에 고정한 기계 지표 정의(상태창 4항목 형식과 지표 6종, 8어절 복제,
화자 라벨)를 그대로 옮긴 것이다. 그 런의 집계 결과(`mech.json`)를 정답지로 삼아 같은 값이 나오는지
`longturn_metrics.py regress` 로 확인한다 — 정의를 바꾸면 그 회귀가 깨진다.

장기 대화에서 새로 재는 것(본문 날수 문구, 상태창 `시간` 줄 요일)도 여기 둔다. 정규식은 결과를 보기 전에
고정한다 — 결과를 본 뒤 낱말을 더하면 사후 선택이 된다.
"""

import re
from dataclasses import dataclass, field

HEROINES = ("도희", "유나", "세빈")

# 상태창 4항목 형식: 빈 줄이 아닌 줄이 정확히 넷이고 이 순서로 맞아야 한다(`|` 는 ASCII 세로선).
STATUS_KEYS = ("장소", "시간", "함께", "지금")
_STATUS_LINE = tuple(re.compile(rf"^\s*{key}\s*\|\s*\S") for key in STATUS_KEYS)

_DIGIT = re.compile(r"[0-9０-９]")
_DIGIT_RUN = re.compile(r"[0-9０-９]+")
# 스탯 흉내 규칙 1: 런 바로 뒤(공백 0~1칸) 단위.
_AFTER_UNIT = re.compile(r"^ ?(%|％|점|포인트|pt|단계|/[0-9０-９])")
# 규칙 2: 런 바로 앞(공백 0~1칸) 기호.
_BEFORE_SIGN = re.compile(r"(\+|＋|Lv\.?|LV\.?|lv\.?|D-|D−) ?$")
# 규칙 3: 같은 줄의 스탯 낱말과 10자 이내.
_STAT_WORDS = ("호감", "스탯", "게이지", "점수", "수치", "친밀", "신뢰도", "상영회까지", "♥", "❤", "★")
# 규칙 4: 같은 줄 인물 이름과 10자 이내, 런 바로 뒤가 아래 단위가 아닐 때.
_NAME_SAFE_SUFFIX = ("학년", "테이크", "시", "분", "월", "일", "년", "층", "번", "호", "살", "컷", "씬", "신", "명")
_NEAR = 10
# 상태창 안 스탯 낱말(숫자 유무 무관).
_STATUS_STAT_WORDS = ("호감", "스탯", "게이지", "점수", "친밀도", "신뢰도")

# 화자 라벨: 본문 어느 줄이든 이름(또는 서술자) 뒤 콜론.
_LABEL = re.compile(
    r"^\s*(\[|【)?\s*(강도희|도희|민유나|유나|차세빈|세빈|오태민|태민|서술자|나레이션)\s*(\]|】)?\s*[:：]",
    re.MULTILINE,
)

DUP_WORDS = 8
_WORD_EDGE = re.compile(r"^[\W_*]+|[\W_*]+$")

# 본문 날수 문구 — 지난 날수를 말하는 표현. 값은 그 문구가 뜻하는 날수(모르면 None). 한글 수 + "일"("한 일 뒤")은
# "내가 한 일 뒤에"와 갈리지 않아 넣지 않는다 — 한글 날수는 하루·이틀… 꼴로 잡는다.
_KOREAN_DAYS = {"하루": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5, "엿새": 6, "이레": 7, "열흘": 10}
_DAY_PHRASE = re.compile(
    r"(?P<word>하루|이틀|사흘|나흘|닷새|엿새|이레|열흘)\s*(?:뒤|후|만에|가\s*지나|이\s*지나|째)"
    r"|(?P<nextday>다음\s*날|이튿날)"
    r"|(?P<week>일주일|한\s*주)\s*(?:뒤|후|만에|가\s*지나|이\s*지나)"
    r"|(?P<nextweek>다음\s*주)(?=[\s,.에가는도]|$)"
    r"|(?P<num>[0-9]+)\s*일\s*(?:뒤|후|만에|이\s*지나)"
    r"|(?P<some>며칠|몇\s*일)\s*(?:뒤|후|만에|이\s*지나|가\s*지나)"
)
_WEEKDAY = re.compile(r"([월화수목금토일])요일")
WEEKDAYS = "월화수목금토일"


@dataclass(frozen=True)
class StatusBlock:
    lines: tuple[str, ...]
    end_index: int  # 닫는 펜스 줄의 끝 위치(본문 문자열 기준)
    start_index: int


@dataclass
class StatusResult:
    present: bool
    other_blocks: int = 0
    pos_end: bool = False
    fmt_ok: bool = False
    lines: list[str] = field(default_factory=list)
    digit: bool = False
    digit_lines: list[str] = field(default_factory=list)
    mimic_status: list[tuple[str, list[tuple[str, int]]]] = field(default_factory=list)
    statword: bool = False


def fenced_blocks(text: str) -> list[StatusBlock]:
    """``` 또는 ~~~ 로 여닫는 코드 블록. 여는 줄과 같은 펜스 문자로 시작하는 줄이 닫는다. 닫히지 않은 블록은 세지
    않는다."""
    blocks: list[StatusBlock] = []
    lines = text.split("\n")
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        fence = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if fence is None:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip().startswith(fence):
            j += 1
        if j >= len(lines):
            break
        blocks.append(
            StatusBlock(
                lines=tuple(lines[i + 1 : j]),
                end_index=offsets[j] + len(lines[j]),
                start_index=offsets[i],
            )
        )
        i = j + 1
    return blocks


def split_status(text: str) -> tuple[StatusBlock | None, str]:
    """(상태창, 상태창을 뺀 본문). 상태창은 마지막 코드 블록이다."""
    blocks = fenced_blocks(text)
    if not blocks:
        return None, text
    last = blocks[-1]
    return last, text[: last.start_index] + text[last.end_index :]


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """두 구간 사이 글자 수(겹치면 0)."""
    if a[1] <= b[0]:
        return b[0] - a[1]
    if b[1] <= a[0]:
        return a[0] - b[1]
    return 0


def _words_near(line: str, words: tuple[str, ...], span: tuple[int, int]) -> bool:
    for word in words:
        for match in re.finditer(re.escape(word), line):
            if _gap((match.start(), match.end()), span) <= _NEAR:
                return True
    return False


def mimic_runs(line: str) -> list[tuple[str, int]]:
    """한 줄의 숫자 런 중 스탯 흉내인 것과 맞은 첫 규칙 번호(1~4)."""
    found: list[tuple[str, int]] = []
    for match in _DIGIT_RUN.finditer(line):
        run = match.group()
        before, after = line[: match.start()], line[match.end() :]
        span = (match.start(), match.end())
        if _AFTER_UNIT.match(after):
            found.append((run, 1))
        elif _BEFORE_SIGN.search(before):
            found.append((run, 2))
        elif _words_near(line, _STAT_WORDS, span):
            found.append((run, 3))
        elif _words_near(line, HEROINES, span) and not after.startswith(_NAME_SAFE_SUFFIX):
            found.append((run, 4))
    return found


def status_metrics(reply: str) -> StatusResult:
    blocks = fenced_blocks(reply)
    if not blocks:
        return StatusResult(present=False)
    block = blocks[-1]
    lines = [line for line in block.lines if line.strip()]
    fmt_ok = len(lines) == 4 and all(p.match(line) for p, line in zip(_STATUS_LINE, lines, strict=True))
    digit_lines = [line for line in lines if _DIGIT.search(line)]
    mimic = [(line, runs) for line in lines if (runs := mimic_runs(line))]
    return StatusResult(
        present=True,
        other_blocks=len(blocks) - 1,
        pos_end=reply[block.end_index :].strip() == "",
        fmt_ok=fmt_ok,
        lines=lines,
        digit=bool(digit_lines),
        digit_lines=digit_lines,
        mimic_status=mimic,
        statword=any(word in line for line in lines for word in _STATUS_STAT_WORDS),
    )


def status_field(status: StatusResult, key: str) -> str | None:
    """상태창에서 `key | 값` 줄의 값. 줄이 없으면 None."""
    pattern = re.compile(rf"^\s*{key}\s*\|(.*)$")
    for line in status.lines:
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return None


def together(status: StatusResult) -> dict[str, bool]:
    value = status_field(status, "함께") or ""
    return {name: name in value for name in HEROINES}


def mimic_body(reply: str) -> list[tuple[str, list[tuple[str, int]]]]:
    """상태창 밖 본문 줄의 스탯 흉내 수치."""
    _, body = split_status(reply)
    return [(line, runs) for line in body.split("\n") if (runs := mimic_runs(line))]


def labels(reply: str) -> list[str]:
    return [match.group(0).strip() for match in _LABEL.finditer(reply)]


def words(text: str) -> list[str]:
    """어절 — 공백으로 자르고 앞뒤 문장부호·별표를 지운다. 지우고 빈 어절은 버린다."""
    out = []
    for raw in text.split():
        word = _WORD_EDGE.sub("", raw)
        if word:
            out.append(word)
    return out


def _grams(seq: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(seq[i : i + n]) for i in range(len(seq) - n + 1)]


def strip_status(text: str) -> str:
    return split_status(text)[1]


def duplicate_spans(reply: str, user_text: str, sources: dict[str, str]) -> list[dict[str, str]]:
    """응답 본문(상태창 제외)이 비교 대상 글(상태창 제외)과 어절 8개 이상 연속으로 같으면 대상마다 첫 일치 하나.
    사용자 발화에 있는 8어절은 세지 않는다(사용자의 말을 되받아 인용한 것)."""
    reply_words = words(strip_status(reply))
    user_grams = set(_grams(words(user_text), DUP_WORDS))
    found: list[dict[str, str]] = []
    for name, text in sources.items():
        source_grams = set(_grams(words(strip_status(text)), DUP_WORDS))
        for gram in _grams(reply_words, DUP_WORDS):
            if gram in source_grams and gram not in user_grams:
                found.append({"src": name, "sample": " ".join(gram)})
                break
    return found


def day_phrases(reply: str) -> list[dict[str, object]]:
    """상태창 밖 본문의 날수 문구와 그 날수(정할 수 없으면 None)."""
    body = strip_status(reply)
    found: list[dict[str, object]] = []
    for match in _DAY_PHRASE.finditer(body):
        days: int | None
        if match.group("word"):
            days = _KOREAN_DAYS[match.group("word")]
        elif match.group("nextday"):
            days = 1
        elif match.group("week"):
            days = 7
        elif match.group("nextweek"):
            days = None  # 다음 주는 며칠 뒤인지 정해지지 않는다
        elif match.group("num"):
            days = int(match.group("num"))
        else:
            days = None
        found.append({"text": match.group(0), "days": days})
    return found


def weekday(status: StatusResult) -> str | None:
    """상태창 `시간` 줄의 요일 한 글자(없으면 None). 둘 이상이면 첫 것."""
    value = status_field(status, "시간")
    if value is None:
        return None
    match = _WEEKDAY.search(value)
    return match.group(1) if match else None


def weekday_step(before: str | None, after: str | None) -> int | None:
    """요일이 앞으로 몇 날 움직였나(0~6). 7의 배수는 0 으로 보이므로 날 바뀜의 보조 근거로만 쓴다."""
    if before is None or after is None:
        return None
    return (WEEKDAYS.index(after) - WEEKDAYS.index(before)) % 7
