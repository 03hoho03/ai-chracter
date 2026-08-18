"""`chat_probe.py` 대화록에서 되받기율·길이·출력 결함을 기계적으로 센다.

    uv run python scripts/analyze_chat_probe.py <probe.json> [<probe2.json> ...] [--json]

파일을 여러 개 주면 준 순서대로 열을 나란히 낸다(N개 모델 비교용). 열 라벨은 파일 메타의
model(없으면 파일명)이다. `--json` 은 표 대신 같은 수치를 기계가 읽을 JSON 으로 낸다
(다음 단계 HTML 리포트의 입력).

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
from dataclasses import dataclass, field
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
_LABEL = re.compile(r"(^|\n)\s*(사용자|서술자|진행자|캐릭터)\s*:")
_USER_TURN = re.compile(r"(^|\n)\s*사용자\s*:")
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

# 직전 진행자 발화(오프닝 포함)의 앞 N자를 그대로 앞머리에 다시 쓰면 자기 복제로 본다.
# 실측 사례(2026-08-11 gemini-2.5-flash)는 직전 응답 전문 600자를 통째로 앞에 붙이고 이어
# 썼다 — 전문 복사는 접두 비교만으로 확실히 잡히고, 50자가 우연히 일치할 일은 사실상 없어
# 유사도 알고리즘을 두지 않는다. 비교 전 양쪽을 strip() 하는 이유: 바로 그 실측 사례의
# 직전 응답이 선행 공백 한 칸으로 시작해서, raw 비교로는 놓친다(모델이 공백만 다듬고
# 본문을 복사할 수 있다).
_SELF_COPY_PREFIX = 50


def _is_truncated(reply: str) -> bool:
    tail = reply.rstrip().rstrip("*").rstrip()
    return not tail or tail[-1] not in _TERMINAL_CHARS


def _sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE.split(text) if part.strip()]


def _parroted(reply: str, turn_index: int, window: str) -> bool:
    if turn_index >= len(TURN_KEYWORDS):
        return False
    if window == "chars250":
        scope = reply[:250]
    elif window == "sent2":
        scope = " ".join(_sentences(reply)[:2])
    else:  # pct30 — 길이 변화에 중립적
        scope = reply[: max(1, int(len(reply) * 0.3))]
    return any(keyword in scope for keyword in TURN_KEYWORDS[turn_index])


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
    median_len: float = 0.0
    median_sentences: float = 0.0
    spread: float = 0.0
    per_story: dict[str, tuple[int, int]] = field(default_factory=dict)
    defects: list[str] = field(default_factory=list)

    def rate(self, window: str) -> str:
        hit = self.hits[window]
        return f"{hit}/{self.scored} ({round(100 * hit / max(1, self.scored))}%)"

    # rate() 와 같은 표기 — 되받기 창 밖의 카운터(절단·자기복제)용.
    def ratio(self, hit: int) -> str:
        return f"{hit}/{self.scored} ({round(100 * hit / max(1, self.scored))}%)"


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
            out.scored += 1
            lengths.append(len(reply))
            scored_lengths.append(len(reply))
            sentence_counts.append(len(_sentences(reply)))
            if _is_truncated(reply):
                out.truncated += 1
            prev_head = previous.strip()[:_SELF_COPY_PREFIX]
            if len(prev_head) == _SELF_COPY_PREFIX and reply.strip().startswith(prev_head):
                out.self_copies += 1
            previous = reply
            for window in WINDOWS:
                if _parroted(reply, index, window):
                    out.hits[window] += 1
                    if window == "chars250":
                        story_hits += 1
            if _LABEL.search(reply):
                out.defects.append(f"{key} t{index + 1}: 화자 라벨 누출")
            if _USER_TURN.search(reply):
                out.defects.append(f"{key} t{index + 1}: 사용자 턴 대신 씀")
            broken = _BROKEN.search(reply)
            if broken:
                out.defects.append(f"{key} t{index + 1}: 한글깨짐 후보 '{broken.group()}'")
            for token in _BRACKET.findall(reply):
                out.defects.append(f"{key} t{index + 1}: 대괄호 출력 {token}")
        if scored_lengths:
            out.per_story[key] = (story_hits, int(statistics.median(scored_lengths)))

    if lengths:
        out.median_len = statistics.median(lengths)
        out.median_sentences = statistics.median(sentence_counts)
    medians = [value[1] for value in out.per_story.values()]
    # 항목이 하나뿐이면 편차는 항상 1.0 이라 무의미하다 — 0.0 으로 두고 출력에서 생략한다.
    if len(medians) >= 2:
        out.spread = max(medians) / min(medians)
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
            for path, s in zip(paths, summaries)
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    width = max(14, max(len(s.label) for s in summaries)) + 2
    _row("", [s.label for s in summaries], width)
    _row("턴 수", [str(s.scored) for s in summaries], width)
    _row("유실 턴 수", [str(s.empty_replies) for s in summaries], width)
    for window, label in zip(WINDOWS, ("되받기 앞250자", "되받기 앞2문장", "되받기 앞30%")):
        _row(label, [s.rate(window) for s in summaries], width)
    _row("길이 중앙값", [f"{s.median_len:.0f}자" for s in summaries], width)
    _row("문장 수 중앙값", [f"{s.median_sentences:.0f}" for s in summaries], width)
    _row("절단(문장 미종결)", [s.ratio(s.truncated) for s in summaries], width)
    _row("자기복제(직전 복사)", [s.ratio(s.self_copies) for s in summaries], width)
    # 스토리 하나를 여러 회차로 돌리는 실험부터 "스토리 간"이 아니라 "항목 간"(스토리 ×
    # 시작설정 × 회차) 편차다. 항목이 1개면 항상 1.0 이라 표시하지 않는다.
    _row("항목 간 길이 편차", [f"{s.spread:.1f}배" if s.spread else "-" for s in summaries], width)

    for s in summaries:
        print(f"\n[{s.label}] 항목별 되받기(앞250자) / 길이 중앙값")
        for key, (hit, length) in sorted(s.per_story.items(), key=lambda item: -item[1][0]):
            print(f"  {key:24} {hit}/5   {length:>5}자")
        if s.defects:
            print(f"  결함 후보 {len(s.defects)}건")
            for line in s.defects:
                print(f"  · {line}")


if __name__ == "__main__":
    main()
