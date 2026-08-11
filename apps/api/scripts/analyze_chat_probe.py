"""`chat_probe.py` 대화록에서 되받기율·길이·출력 결함을 기계적으로 센다.

    uv run python scripts/analyze_chat_probe.py <probe.json> [<baseline.json>]

두 번째 인자를 주면 전후를 나란히 낸다.

**지표 정의를 코드로 고정해 두는 것이 이 파일의 존재 이유다.** 눈대중으로 세면 회차마다
관대함이 달라져 비교가 무의미해지고, 실제로 다음 두 함정을 밟았다:

1. 처음엔 "첫 따옴표 발화"만 봤다가 따옴표를 안 쓰는 스토리(wuxia-oneform 등)를 통째로
   놓쳤다. 되받기는 "지문으로 열고 그 다음 대사에서" 나오므로 앞부분을 넉넉히 봐야 한다.
2. 응답 길이가 줄면 "앞 250자"가 글 전체에서 차지하는 비중이 커져 되받기율이 부풀려진다.
   그래서 길이에 중립적인 기준(앞 2문장 / 앞 30%)을 함께 낸다 — 세 기준이 같은 방향으로
   움직일 때만 진짜 변화로 본다.

**대화록은 반드시 `/tmp` 밖에 저장할 것.** 스크래치패드에 뒀다가 며칠 뒤 정리되면서
베이스라인 원본을 잃은 적이 있다(수치만 남고 재분석이 불가능해졌다).
"""

import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field

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
    scored: int = 0
    hits: Counter[str] = field(default_factory=Counter)
    median_len: float = 0.0
    median_sentences: float = 0.0
    spread: float = 0.0
    per_story: dict[str, tuple[int, int]] = field(default_factory=dict)
    defects: list[str] = field(default_factory=list)

    def rate(self, window: str) -> str:
        hit = self.hits[window]
        return f"{hit}/{self.scored} ({round(100 * hit / max(1, self.scored))}%)"


def summarize(path: str) -> Summary:
    with open(path, encoding="utf-8") as handle:
        stories = json.load(handle)

    out = Summary()
    lengths: list[int] = []
    sentence_counts: list[int] = []

    for story in stories:
        if "error" in story:
            out.defects.append(f"{story['slug']}: {story['error']}")
            continue
        replies = [t["text"] for t in story["transcript"][1:] if t["role"] == "진행자" and t["text"]]
        story_hits = 0
        for index, reply in enumerate(replies):
            out.scored += 1
            lengths.append(len(reply))
            sentence_counts.append(len(_sentences(reply)))
            for window in WINDOWS:
                if _parroted(reply, index, window):
                    out.hits[window] += 1
                    if window == "chars250":
                        story_hits += 1
            if _LABEL.search(reply):
                out.defects.append(f"{story['slug']} t{index + 1}: 화자 라벨 누출")
            if _USER_TURN.search(reply):
                out.defects.append(f"{story['slug']} t{index + 1}: 사용자 턴 대신 씀")
            broken = _BROKEN.search(reply)
            if broken:
                out.defects.append(f"{story['slug']} t{index + 1}: 한글깨짐 후보 '{broken.group()}'")
            for token in _BRACKET.findall(reply):
                out.defects.append(f"{story['slug']} t{index + 1}: 대괄호 출력 {token}")
        if replies:
            out.per_story[story["slug"]] = (story_hits, int(statistics.median(len(r) for r in replies)))

    if lengths:
        out.median_len = statistics.median(lengths)
        out.median_sentences = statistics.median(sentence_counts)
    medians = [value[1] for value in out.per_story.values()]
    if medians:
        out.spread = max(medians) / min(medians)
    return out


def _row(label: str, base: str, after: str | None) -> None:
    print(f"  {label:24} {base}" if after is None else f"  {label:24} {base:>14}  ->  {after}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    after = summarize(sys.argv[1])
    before = summarize(sys.argv[2]) if len(sys.argv) > 2 else None
    base = before or after

    print(f"턴 수: {after.scored}" + (f" (기준 {before.scored})" if before else ""))
    for window, label in zip(WINDOWS, ("되받기 앞250자", "되받기 앞2문장", "되받기 앞30%")):
        _row(label, base.rate(window), after.rate(window) if before else None)
    _row("길이 중앙값", f"{base.median_len:.0f}자", f"{after.median_len:.0f}자" if before else None)
    _row("문장 수 중앙값", f"{base.median_sentences:.0f}", f"{after.median_sentences:.0f}" if before else None)
    _row("스토리 간 길이 편차", f"{base.spread:.1f}배", f"{after.spread:.1f}배" if before else None)

    print("\n스토리별 되받기(앞250자) / 길이 중앙값")
    for slug, (hit, length) in sorted(after.per_story.items(), key=lambda item: -item[1][0]):
        prior = before.per_story.get(slug) if before else None
        shift = f"  (기준 {prior[0]}/5, {prior[1]}자)" if prior else ""
        print(f"  {slug:24} {hit}/5   {length:>5}자{shift}")

    if after.defects:
        print(f"\n결함 후보 {len(after.defects)}건")
        for line in after.defects:
            print(f"  · {line}")


if __name__ == "__main__":
    main()
