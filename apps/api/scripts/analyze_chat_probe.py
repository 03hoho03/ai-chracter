"""`chat_probe.py` 대화록에서 되받기율·길이·출력 결함을 기계적으로 센다.

    uv run python scripts/analyze_chat_probe.py <probe.json> [<probe2.json> ...] [--json]

파일을 여러 개 주면 준 순서대로 열을 나란히 낸다(N개 모델 비교용). 열 라벨은 파일 메타의
model(없으면 파일명)이다. `--json` 은 표 대신 같은 수치를 기계가 읽을 JSON 으로 낸다
(HTML 리포트의 입력).

**지표 정의를 코드로 고정해 두는 것이 이 파일의 존재 이유다.** 눈대중으로 세면 회차마다
관대함이 달라져 비교가 무의미해지고, 실제로 다음 두 함정을 밟았다:

1. 처음엔 "첫 따옴표 발화"만 봤다가 따옴표를 안 쓰는 스토리(wuxia-oneform 등)를 통째로
   놓쳤다. 되받기는 "지문으로 열고 그 다음 대사에서" 나오므로 앞부분을 넉넉히 봐야 한다.
2. 응답 길이가 줄면 "앞 250자"가 글 전체에서 차지하는 비중이 커져 되받기율이 부풀려진다.
   그래서 길이에 중립적인 기준(앞 2문장 / 앞 30%)을 함께 낸다 — 세 기준이 같은 방향으로
   움직일 때만 진짜 변화로 본다.
3. 모델 비교 회차(2026-08-11)에서 max_output_tokens 절단이 표에는 "길이 중앙값이 길다"로만
   나타나 오히려 장점처럼 읽혔고, 직전 응답 전문을 통째로 복사한 턴이 되받기·길이 수치를
   함께 오염시켰다. 그래서 절단(문장 미종결)·자기복제·유실 턴 수를 함께 센다 — 429 로
   유실된 턴은 scored 분모에서 빠지므로, 유실 턴 수가 다른 모델끼리 비율(%)을 그대로
   비교하면 안 된다.

프로브 파일은 두 최상위 포맷이 공존한다: 2026-08-10 베이스라인까지는 리스트, 모델 비교
회차(2026-08-11~)부터는 메타(model 등)를 담은 객체다. 베이스라인 파일은 재수집이 불가능하므로
(당시의 프롬프트·모델 조합이 이미 없다) 리스트 포맷 읽기를 지우면 안 된다. 항목 키는
`label`(없으면 `slug` 폴백)이다 — 같은 스토리를 여러 시작설정/회차로 돌리면 slug 만으로는
항목이 안 갈려 뒤 회차가 앞 회차를 덮어쓰기 때문.

**대화록은 반드시 `/tmp` 밖에 저장할 것.** 스크래치패드에 뒀다가 며칠 뒤 정리되면서
베이스라인 원본을 잃은 적이 있다(수치만 남고 재분석이 불가능해졌다).
"""

import json
import re
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

# `chat_probe.TURNS` 의 고정 사용자 턴마다, 그 턴을 "되받았다"고 볼 표지.
# 프로브 대본을 바꾸면 여기도 같이 바꿔야 한다.
TURN_KEYWORDS = [
    ["상황"],
    ["좋은 생각", "생각이 아니", "별로"],
    ["왜", "생각"],
    ["느낌", "그냥"],
    ["무섭", "무서", "솔직"],
]

WINDOWS = ("chars250", "sent2", "pct30")

_SENTENCE = re.compile(r'(?<=[.!?…”"\'])\s+|\n+')
# 여는 괄호·따옴표·별표를 허용한다 — 줄머리만 보던 이전 버전은 `(서술자: 낡은 스테인리스…`
# 처럼 여는 괄호 뒤에 오는 라벨을 놓쳤다(2026-09-08 실측).
_LABEL = re.compile(r"(^|\n)[\s(\[\"“'*]*(사용자|서술자|진행자|캐릭터)\s*:")
_USER_TURN = re.compile(r"(^|\n)\s*사용자\s*:")
# 턴 열기 지표 4종 — 밥집(닫힘)·이도윤(열림) 두 방 실측으로 판정력을
# 확인한 것만 담는다. 물음표·따옴표 대사 후보는 항진명제/역방향으로 판정력이 없어 버렸다.
_SOLICIT = re.compile(
    r"(까요|나요|ㄹ까|을까|는지요|습니까|십시오|세요|주세요|보실|하실|드릴까)[.?…\"”\s]*(?:$|[.\"?…”])",
    re.M,
)
# 사용자 발화를 명시적으로 무시하는 표현 — 응답 앞 120자에서만 본다(호출부에서 슬라이스).
_IGNORE = re.compile(r"(대꾸 없이|대답(을)? (하지|않)|답하지 않|반응하지 않|아무 말(도)? 없)")
# 장면 이동형 열기 — 의문·청유(질문 형태)가 못 잡는 나머지 두 갈래(상황 변화·사실 노출)를
# "마지막 문장이 정적·종결 어휘로 끝나는가"의 반대로 잡는다. "진행 중" 을 직접 정의하려 하면
# `스쳐 지나가는 듯합니다` 처럼 여닫힘 양쪽에 다 나오는 표현이 섞여 판정력이 없다 — 종결
# 어휘를 걸러내는 쪽이 실측에서 갈렸다. 밥집 재현 A세트(09-09 아카이브) 마지막 문장
# 기준: 기준선은 4/12 가 "정적만이 가득하며"·"침묵합니다"·"눈치채지 못한"·"기대하지 않는"
# 로 끝나 닫힘, 처방(L0)은 0/12. 정답지(밥집 4턴·이도윤 6턴)도 같은 방향(3/4 vs 6/6).
_SCENE_CLOSE = re.compile(
    r"정적(만|이|은|을)?|고요(함|만|이|은)?|침묵(합니다|한다|을 지킵니다|이|만)?|"
    r"잠(이 )?(듭니다|들었|든|들어)|눈을 감|"
    r"(녹아|스며|잦아|가라앉)(듭니다|든다|들며|들어)|"
    r"아무(것도|말도) ?(없|남지 않|하지 않)|"
    r"기대하지 않|눈치채지 못"
)
_BRACKET = re.compile(r"\[[^\]]{2,12}\]")
# 한글 낱말 안에 라틴 문자가 섞인 것 = 모델이 한국어를 깨뜨린 자리(`길as`, `자C리`).
# 의도된 외래어(`지옥 CPU가`)도 걸리므로 눈으로 확인할 후보 목록으로만 쓴다.
_BROKEN = re.compile(r"[가-힣][A-Za-z]|[A-Za-z][가-힣]")

# 응답이 "문장으로 끝났다"고 볼 종결 문자 집합. 한국어 서술체 대화록이라 정상 응답은 전부
# 종결 부호(. ! ? …)나 그 뒤의 닫는 따옴표로 끝난다는 게 전 회차 실측이다 — 닫는 따옴표는
# 네 종(" ” ' ’)이 모두 실제로 나타나서 `_SENTENCE` 와 달리 ’ 도 포함한다. 마크다운
# 이탤릭(*…*)으로 감싼 지문은 종결 부호 뒤에 * 가 붙으므로(2026-08-10 베이스라인 실측)
# 판정 전에 꼬리의 * 를 벗겨낸다 — 형식 기호이지 문장 내용이 아니다. 이 기준은 2026-08-11
# 회차의 서버 로그(max_output_tokens 절단 경고 8건)와 정확히 같은 턴을 잡는 것으로 확정했다.
_TERMINAL_CHARS = set(".!?…\"”'’")

# 코드 펜스 줄. 작품 규칙이 응답 끝에 상태창(장소·시간·함께·지금 네 줄)을 ``` 코드 블록으로 붙이게 하는 작품이 있어(튜토리얼
# 시드 `tutorial-filmclub.json` 의 규칙과 오프닝), 그 응답은 마지막 줄이 늘 닫는 펜스라 펜스째 보면 마지막 문장이 ``` 가 된다.
# 엔진의 장면 헤더(작가가 켜는 장소·시간 표시)는 응답 글에 들지 않고 따로 판정해 따로 보낸다 — 응답 글의 펜스는 모델이 쓴
# 것이다. 여닫는 모양은 웹 채팅 표기 처리가 코드 줄을 가리는 규칙(`apps/web` 의 `chatNotationSyntax.ts` `openFence`·
# `isFenceClose`)과 같다 — 줄 앞 공백 셋까지, 백틱이나 물결 셋 이상. 닫는 줄은 여는 줄과 같은 글자로 그 길이 이상이고 뒤에
# 공백만 온다.
_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,}).*")
_FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})\s*")

# 직전 진행자 발화(오프닝 포함)의 앞 N자를 그대로 앞머리에 다시 쓰면 자기 복제로 본다.
# 실측 사례(2026-08-11 gemini-2.5-flash)는 직전 응답 전문 600자를 통째로 앞에 붙이고 이어
# 썼다 — 전문 복사는 접두 비교만으로 확실히 잡히고, 50자가 우연히 일치할 일은 사실상 없어
# 유사도 알고리즘을 두지 않는다. 비교 전 양쪽을 strip() 하는 이유: 바로 그 실측 사례의
# 직전 응답이 선행 공백 한 칸으로 시작해서, raw 비교로는 놓친다(모델이 공백만 다듬고
# 본문을 복사할 수 있다).
_SELF_COPY_PREFIX = 50


def _narrative(reply: str) -> tuple[str, bool]:
    """응답에서 끝에 붙은 닫힌 펜스 블록을 뗀 본문과, 닫히지 않은 펜스가 있는가. 끝에 블록이 여럿 이어 붙었으면 모두 뗀다(블록
    사이·앞뒤의 빈 줄과 공백도 함께 떨어진다). 본문 중간의 닫힌 블록은 그대로 둔다 — 그 뒤에 본문이 이어지면 마지막 문장은 그
    본문에 있다. 닫히지 않은 펜스가 있으면 본문은 그 여는 줄 앞까지다. 뗀 것이 없으면 본문은 응답 그대로다(꼬리 공백도 남는다)."""
    lines = reply.split("\n")
    fence: tuple[str, int] | None = None
    opened_at = 0
    blocks: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if fence is None:
            opening = _FENCE_OPEN.fullmatch(line)
            if opening:
                fence = (opening.group(1)[0], len(opening.group(1)))
                opened_at = index
            continue
        closing = _FENCE_CLOSE.fullmatch(line)
        if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= fence[1]:
            blocks.append((opened_at, index))
            fence = None
    if fence is not None:
        return "\n".join(lines[:opened_at]).rstrip(), True
    end = len(lines)
    while blocks and not "".join(lines[blocks[-1][1] + 1 : end]).strip():
        end = blocks.pop()[0]
    return ("\n".join(lines[:end]).rstrip() if end < len(lines) else reply), False


def _is_truncated(body: str) -> bool:
    tail = body.rstrip().rstrip("*").rstrip()
    return not tail or tail[-1] not in _TERMINAL_CHARS


def _sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE.split(text) if part.strip()]


def _parroted(reply: str, turn_index: int, window: str) -> bool:
    """세 창은 응답 끝의 상태창 블록을 뗀 본문 위에 둔다(떼는 규칙은 길이·문장 수와 같은 `_narrative`). 본문이 짧으면 앞 250자·앞
    30% 창이 상태창까지 덮어, 상태창 줄의 낱말을 되받기로 셀 수 있다."""
    if turn_index >= len(TURN_KEYWORDS):
        return False
    body = _narrative(reply)[0]
    if window == "chars250":
        scope = body[:250]
    elif window == "sent2":
        scope = " ".join(_sentences(body)[:2])
    else:  # pct30 — 길이 변화에 중립적
        scope = body[: max(1, int(len(body) * 0.3))]
    return any(keyword in scope for keyword in TURN_KEYWORDS[turn_index])


@dataclass(frozen=True)
class ReplyFlags:
    """응답 하나에 대한 판정 전부 — 되받기만 뺐다(되받기는 고정 대본의 턴 순번에 묶여 `_parroted` 에 남는다)."""

    # 길이·문장 수는 끝의 상태창 블록을 뗀 본문으로 센다. 뗀 꼬리의 글자 수가 `status_block_length` 다(규칙은 `reply_flags`).
    length: int
    sentence_count: int
    status_block_length: int
    truncated: bool
    self_copy: bool
    solicit: bool
    ignored: bool
    # 마지막 문장이 정적·종결 어휘(_SCENE_CLOSE)로 끝나지 않았다 — 장면 이동형 열기.
    scene_open: bool
    label_leak: bool
    user_turn: bool
    # 한글 낱말에 라틴 문자가 섞인 첫 자리(없으면 None). 눈으로 확인할 후보라 글자를 그대로 낸다.
    broken: str | None
    brackets: tuple[str, ...]


def reply_flags(reply: str, previous: str) -> ReplyFlags:
    """응답 하나와 `previous` 만으로 판정한다. `previous` 는 이 응답보다 앞선, 비어 있지 않은 진행자 응답 가운데 마지막 것이다 —
    `summarize()` 는 유실 턴(빈 응답)을 건너뛰므로 바로 앞 턴이 유실됐으면 그보다 앞의 응답을 넘기고, 앞선 응답이 하나도 없으면
    (첫 턴, 또는 첫 턴부터 유실이 이어진 경우) 대화록 첫 항목인 오프닝 메시지를 넘긴다. 대화록 형식을 모르게 둔 것은 chat_probe
    대화록이 아닌 기록(드라이버 로그 등)에서도 같은 판정을 쓰게 하려는 것이다. 빈 응답(유실 턴)은 판정 대상이 아니라 부르는
    쪽이 먼저 거른다 — 빈 응답은 절단으로 판정된다.

    길이·문장 수와 마지막 문장을 보는 두 판정(절단·장면 이동형 열기)은 응답 끝의 코드 펜스 블록(`_FENCE_OPEN`)을 뗀 본문으로
    본다. 상태창은 문장이 아니라 형식 블록이라, 그것을 본문으로 읽으면 마지막 문장이 늘 닫는 펜스가 되어 완결 응답이 전부
    절단·열림으로 잡히고, 문장 수는 블록 줄 수만큼, 길이는 블록 글자만큼 는다.

    - 끝에 붙은 닫힌 블록(뒤에 빈 줄만 오는 것, 여럿이면 모두)을 떼고 남은 본문의 마지막 문장을 판정한다. 블록 앞 문장이 잘렸으면
      절단이다. 떼고 남은 본문이 비면 빈 응답과 같이 절단이다.
    - 본문 중간의 닫힌 블록은 떼지 않는다 — 블록 뒤에 본문이 이어지면 마지막 문장은 그 본문에 있다.
    - 닫히지 않은 펜스가 있으면 절단이다. 상태창 규칙은 블록을 닫고 끝내라는 것이라, 닫는 줄 없이 끝난 응답은 블록을 쓰다 멈춘
      것으로 본다(채팅 화면도 그 뒤를 끝까지 코드로 그린다). 장면 이동형 열기와 길이·문장 수는 그 여는 줄 앞의 본문으로 본다.

    뗀 꼬리(블록과 그 앞뒤 빈 줄·공백, 닫히지 않은 블록이면 여는 줄부터 끝까지)의 글자 수는 `status_block_length` 로 따로 내고,
    뗀 것이 없으면 0 이다. 길이와 그 수를 더하면 응답 전체 글자 수다. 나머지 판정(자기복제·의문·청유 어미·무시 표현·라벨
    누출·사용자 턴 대필·한글 깨짐·대괄호)은 펜스를 포함한 응답 전체로 본다."""
    body, unclosed_fence = _narrative(reply)
    sentences = _sentences(body)
    last_sentence = sentences[-1] if sentences else body
    prev_head = previous.strip()[:_SELF_COPY_PREFIX]
    broken = _BROKEN.search(reply)
    return ReplyFlags(
        length=len(body),
        sentence_count=len(sentences),
        status_block_length=len(reply) - len(body),
        truncated=unclosed_fence or _is_truncated(body),
        self_copy=len(prev_head) == _SELF_COPY_PREFIX and reply.strip().startswith(prev_head),
        solicit=bool(_SOLICIT.search(reply)),
        ignored=bool(_IGNORE.search(reply[:120])),
        scene_open=not _SCENE_CLOSE.search(last_sentence),
        label_leak=bool(_LABEL.search(reply)),
        user_turn=bool(_USER_TURN.search(reply)),
        broken=broken.group() if broken else None,
        brackets=tuple(_BRACKET.findall(reply)),
    )


def is_monotonic_shrinking(lengths: Sequence[int]) -> bool:
    """방 하나의 응답 길이 수열이 끝까지 늘지 않았는가(같은 길이가 이어져도 참). 턴 단위가 아니라 방 단위 판정이다."""
    return all(b <= a for a, b in pairwise(lengths))


def length_spread(medians: Sequence[float]) -> float:
    """항목별 길이 중앙값의 최댓값 ÷ 최솟값. 항목이 하나뿐이면 늘 1.0 이라 무의미하다 — 0.0 을 내고 출력에서 생략한다."""
    if len(medians) < 2:
        return 0.0
    return max(medians) / min(medians)


@dataclass
class Summary:
    label: str = ""
    scored: int = 0
    # 429 등으로 응답이 비어 있던 진행자 턴 — scored 분모에서 빠지므로, 이 수가 다른
    # 모델끼리는 비율(%)을 그대로 비교하면 안 된다(docstring 함정 3).
    empty_replies: int = 0
    truncated: int = 0
    self_copies: int = 0
    hits: Counter[str] = field(default_factory=Counter)
    # 턴 열기 지표 4종. solicit/ignored/scene_open은 턴 단위라
    # scored로 나눈다. monotonic_rooms/total_rooms는 **방 단위**(길이 수열이 끝까지 비증가인가)라
    # scored를 분모로 섞지 않는다 — 별도 분모를 갖는다.
    solicit: int = 0
    ignored: int = 0
    # 마지막 문장이 정적·종결 어휘(_SCENE_CLOSE)로 끝나지 **않은** 턴의 수 — 장면 이동형 열기.
    scene_open: int = 0
    monotonic_rooms: int = 0
    total_rooms: int = 0
    median_len: float = 0.0
    median_sentences: float = 0.0
    spread: float = 0.0
    # (되받기 히트, 길이 중앙값, 채점된 턴 수) — 턴 수는 대본마다 다르므로(4턴/5턴) 항목별
    # 출력에서 분모로 써야 한다("/5" 하드코딩은 4턴 대본에서 거짓 정보가 된다).
    per_story: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    defects: list[str] = field(default_factory=list)

    def rate(self, window: str) -> str:
        hit = self.hits[window]
        return f"{hit}/{self.scored} ({round(100 * hit / max(1, self.scored))}%)"

    # rate() 와 같은 표기 — 되받기 창 밖의 카운터(절단·자기복제·솔직청유·무시)용.
    def ratio(self, hit: int) -> str:
        return f"{hit}/{self.scored} ({round(100 * hit / max(1, self.scored))}%)"

    # ratio()와 달리 분모가 scored(턴 수)가 아니라 total_rooms(방 수)다.
    def room_ratio(self) -> str:
        return (
            f"{self.monotonic_rooms}/{self.total_rooms} "
            f"({round(100 * self.monotonic_rooms / max(1, self.total_rooms))}%)"
        )


def summarize(path: str) -> Summary:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    # 구 포맷(최상위 리스트, ~2026-08-10)과 신 포맷(메타 객체)을 모두 받는다 — docstring 참고.
    if isinstance(data, dict):
        stories = data["results"]
        label = data.get("model") or Path(path).stem
    else:
        stories = data
        label = Path(path).stem

    out = Summary(label=label)
    lengths: list[int] = []
    sentence_counts: list[int] = []

    for story in stories:
        key = story.get("label") or story["slug"]
        if "error" in story:
            out.defects.append(f"{key}: {story['error']}")
            continue
        # 턴 인덱스는 transcript 에서의 위치로 센다: chat_probe 는 429 로 응답을 못 받아도
        # 사용자·진행자 쌍을 대본 턴마다 무조건 append 하므로, 오프닝([0]) 뒤 i번째 진행자
        # 항목은 항상 i번째 사용자 발화(TURNS[i])에 대한 응답이다. 빈 응답을 먼저 걸러낸 뒤
        # enumerate 하면 유실 턴 뒤 응답이 전부 한 칸씩 당겨져 엉뚱한 TURN_KEYWORDS 행과
        # 대조된다(2026-08-11/14 회차에서 실측) — 그래서 유실 턴도 인덱스는 소비하게 두고,
        # 채점 제외(scored/길이/되받기 분모)만 빈 응답에 적용한다.
        replies = [t["text"] for t in story["transcript"][1:] if t["role"] == "진행자"]
        out.empty_replies += sum(1 for reply in replies if not reply)
        # 자기 복제 판정의 "직전 발화" — 첫 응답의 직전은 오프닝 메시지다.
        previous = story["transcript"][0]["text"] if story["transcript"] else ""
        story_hits = 0
        scored_lengths: list[int] = []
        for index, reply in enumerate(replies):
            if not reply:
                continue  # 유실 턴 — 채점만 건너뛰고 인덱스는 그대로 지나간다
            flags = reply_flags(reply, previous)
            previous = reply
            out.scored += 1
            lengths.append(flags.length)
            scored_lengths.append(flags.length)
            sentence_counts.append(flags.sentence_count)
            out.truncated += flags.truncated
            out.solicit += flags.solicit
            out.ignored += flags.ignored
            out.scene_open += flags.scene_open
            out.self_copies += flags.self_copy
            for window in WINDOWS:
                if _parroted(reply, index, window):
                    out.hits[window] += 1
                    if window == "chars250":
                        story_hits += 1
            if flags.label_leak:
                out.defects.append(f"{key} t{index + 1}: 화자 라벨 누출")
            if flags.user_turn:
                out.defects.append(f"{key} t{index + 1}: 사용자 턴 대신 씀")
            if flags.broken is not None:
                out.defects.append(f"{key} t{index + 1}: 한글깨짐 후보 '{flags.broken}'")
            for token in flags.brackets:
                out.defects.append(f"{key} t{index + 1}: 대괄호 출력 {token}")
        if scored_lengths:
            out.per_story[key] = (
                story_hits,
                int(statistics.median(scored_lengths)),
                len(scored_lengths),
            )
            out.total_rooms += 1
            out.monotonic_rooms += is_monotonic_shrinking(scored_lengths)

    if lengths:
        out.median_len = statistics.median(lengths)
        out.median_sentences = statistics.median(sentence_counts)
    out.spread = length_spread([value[1] for value in out.per_story.values()])
    return out


def _row(label: str, values: list[str], width: int) -> None:
    print(f"  {label:24}" + "".join(f"{value:>{width}}" for value in values))


def main() -> None:
    as_json = "--json" in sys.argv[1:]
    paths = [arg for arg in sys.argv[1:] if arg != "--json"]
    if not paths:
        raise SystemExit(__doc__)

    summaries = [summarize(path) for path in paths]

    if as_json:
        payload = [
            {
                "path": path,
                "label": s.label,
                "scored": s.scored,
                "empty_replies": s.empty_replies,
                "truncated": s.truncated,
                "self_copies": s.self_copies,
                # 턴 열기 지표: solicit/ignored/scene_open은 scored(턴 단위) 분모,
                # monotonic_rooms는 total_rooms(방 단위) 분모 — 서로 섞지 않는다.
                "solicit": s.solicit,
                "ignored": s.ignored,
                "scene_open": s.scene_open,
                "monotonic_rooms": s.monotonic_rooms,
                "total_rooms": s.total_rooms,
                # Counter 는 0인 키를 안 담으므로 세 창을 항상 전부 채워서 낸다.
                "parrot_hits": {window: s.hits[window] for window in WINDOWS},
                "median_len": s.median_len,
                "median_sentences": s.median_sentences,
                # 항목 1개짜리 파일은 편차가 정의되지 않는다 — 1.0 으로 내면 "편차 없음"과
                # 구분이 안 되므로 null 로 낸다.
                "spread": s.spread if s.spread else None,
                "per_story": s.per_story,
                "defects": s.defects,
            }
            # summaries 는 paths 위의 리스트 컴프리헨션이라 길이가 항상 같다.
            for path, s in zip(paths, summaries, strict=True)
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    width = max(14, max(len(s.label) for s in summaries)) + 2
    _row("", [s.label for s in summaries], width)
    _row("턴 수", [str(s.scored) for s in summaries], width)
    _row("유실 턴 수", [str(s.empty_replies) for s in summaries], width)
    # WINDOWS 와 라벨은 짝을 이루는 상수라 길이가 어긋나면 그 자체가 버그다.
    for window, label in zip(WINDOWS, ("되받기 앞250자", "되받기 앞2문장", "되받기 앞30%"), strict=True):
        _row(label, [s.rate(window) for s in summaries], width)
    _row("길이 중앙값", [f"{s.median_len:.0f}자" for s in summaries], width)
    _row("문장 수 중앙값", [f"{s.median_sentences:.0f}" for s in summaries], width)
    _row("절단(문장 미종결)", [s.ratio(s.truncated) for s in summaries], width)
    _row("자기복제(직전 복사)", [s.ratio(s.self_copies) for s in summaries], width)
    _row("의문·청유 어미", [s.ratio(s.solicit) for s in summaries], width)
    _row("무시 표현(앞120자)", [s.ratio(s.ignored) for s in summaries], width)
    _row("장면 이동형 열기", [s.ratio(s.scene_open) for s in summaries], width)
    # 턴 단위가 아니라 방 단위(길이 수열이 끝까지 비증가인가) — 분모가 다르다.
    _row("길이 단조감소(방 단위)", [s.room_ratio() for s in summaries], width)
    # 스토리 하나를 여러 회차로 돌리는 실험부터 "스토리 간"이 아니라 "항목 간"(스토리 ×
    # 시작설정 × 회차) 편차다. 항목이 1개면 항상 1.0 이라 표시하지 않는다.
    _row("항목 간 길이 편차", [f"{s.spread:.1f}배" if s.spread else "-" for s in summaries], width)

    for s in summaries:
        print(f"\n[{s.label}] 항목별 되받기(앞250자) / 길이 중앙값")
        for key, (hit, length, scored) in sorted(
            s.per_story.items(), key=lambda item: -item[1][0]
        ):
            print(f"  {key:24} {hit}/{scored}   {length:>5}자")
        if s.defects:
            print(f"  결함 후보 {len(s.defects)}건")
            for line in s.defects:
                print(f"  · {line}")


if __name__ == "__main__":
    main()
