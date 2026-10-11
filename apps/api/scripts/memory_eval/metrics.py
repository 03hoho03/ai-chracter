"""평가 지표의 순수 계산. LLM·DB 없음.

- 정답 일치: 정답 키는 묶음 목록이다. 묶음마다 표기 하나 이상이 글에 있어야 하고, 묶음 전부를 채워야 맞다. 비교는 NFC ·
  casefold · 공백 제거 · 숫자 정규화(단위 앞 한글 수사·`H:MM`·`N시반` → 아라비아 숫자) 뒤 부분 문자열이다. 숫자가 든 표기는 앞뒤 글자가 숫자가 아닐 때만 맞는다 — `1월15일` 이
  `11월15일` 안에서 맞으면 다른 날짜를 맞혔다고 세게 된다.
- 비율은 늘 표본 수와 윌슨 95% 구간을 함께 낸다. 두 갈래 짝 비교는 불일치 쌍의 정확 이항 검정(단측)이다.
- 개발/시험 분할은 층마다 id 를 문자열 순으로 정렬해 같은 시드로 섞고, 앞 ceil(n/2) 개를 개발로 보낸다."""

import math
import random
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

# 표준정규 0.975 분위수 — 양측 95% 구간.
Z_95 = 1.959963984540054

_SPACE = re.compile(r"\s+")
_COLON_TIME = re.compile(r"(\d{1,2}):(\d{2})")
# 고유어 시각 수사(긴 것부터 — `열한` 이 `열` 보다 먼저 걸리게). 바로 뒤에 `시` 가 올 때만 바꾼다.
_NATIVE_HOURS = {
    "열한": 11, "열두": 12, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9,
    "한": 1, "두": 2, "세": 3, "네": 4, "열": 10,
}  # fmt: skip
_NATIVE_HOUR = re.compile("(" + "|".join(sorted(_NATIVE_HOURS, key=len, reverse=True)) + ")(?=시)")
_SINO_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
# 한자어 수사 1~59. 바로 뒤에 분·월·일이 올 때만 바꾼다(`일`(하루)·`이`(조사)를 숫자로 오인하지 않게).
_SINO = re.compile(r"((?:[이삼사오]?십)?[일이삼사오육칠팔구]|[이삼사오]?십)(?=[분월일])")
_HALF_HOUR = re.compile(r"(\d{1,2})시반")


def _sino_value(numeral: str) -> int:
    if "십" not in numeral:
        return _SINO_DIGITS[numeral]
    tens, _, ones = numeral.partition("십")
    return (_SINO_DIGITS[tens] if tens else 1) * 10 + (_SINO_DIGITS[ones] if ones else 0)


def normalize_numbers(text: str) -> str:
    """정규화된 글(공백 없음)의 날짜·시각 표기를 아라비아 숫자로: `H:MM` → `H시MM분`, 단위 앞 한글 수사 → 숫자,
    `N시반` → `N시30분`. 응답과 정답 키 양쪽에 같은 순서로 건다."""
    text = _COLON_TIME.sub(lambda m: f"{int(m.group(1))}시{m.group(2)}분", text)
    text = _NATIVE_HOUR.sub(lambda m: str(_NATIVE_HOURS[m.group(1)]), text)
    text = _SINO.sub(lambda m: str(_sino_value(m.group(1))), text)
    return _HALF_HOUR.sub(lambda m: f"{m.group(1)}시30분", text)


def normalize_match_text(text: str) -> str:
    return normalize_numbers(_SPACE.sub("", unicodedata.normalize("NFC", text).casefold()))


def _spelling_in(spelling: str, text: str) -> bool:
    needle = normalize_match_text(spelling)
    if not needle:
        return False
    if not any(ch.isdigit() for ch in needle):
        return needle in text
    start = text.find(needle)
    while start != -1:
        end = start + len(needle)
        before_ok = start == 0 or not text[start - 1].isdigit()
        after_ok = end == len(text) or not text[end].isdigit()
        if before_ok and after_ok:
            return True
        start = text.find(needle, start + 1)
    return False


def answer_matches(text: str, bundles: Sequence[Sequence[str]]) -> bool:
    """묶음이 하나도 없으면 맞힐 것이 없으므로 거짓이다(빈 정답 키는 대본 결함으로 본다)."""
    if not bundles:
        return False
    normalized = normalize_match_text(text)
    return all(any(_spelling_in(spelling, normalized) for spelling in bundle) for bundle in bundles)


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """표본이 비면 아는 것이 없으므로 [0, 1]."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact_one_sided(b_only: int, a_only: int) -> float:
    """B 만 맞힌 쌍 수 `b_only`, A 만 맞힌 쌍 수 `a_only`. 귀무가설(두 갈래 같음)에서 불일치 쌍은 반반이므로,
    불일치 n = b + a 중 B 편이 b 이상일 확률 P(X ≥ b), X ~ Bin(n, 1/2). 불일치가 없으면 1."""
    n = b_only + a_only
    if n == 0:
        return 1.0
    return sum(math.comb(n, i) for i in range(b_only, n + 1)) / float(2**n)


def recall_at_k(ranked: Sequence[str], gold: set[str], k: int) -> bool:
    return any(item in gold for item in ranked[:k])


def ols_slope(points: Sequence[tuple[float, float]]) -> float:
    """최소제곱 기울기. x 가 두 값 이상이 아니면 기울기가 정의되지 않아 NaN."""
    if len({x for x, _ in points}) < 2:
        return math.nan
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in points)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return float(sxy / sxx)


def stratified_split(strata: Mapping[Any, Sequence[str]], seed: int) -> dict[str, str]:
    """층마다 새 `random.Random(seed)` 로 섞는다 — 층의 처리 순서가 결과를 바꾸지 않게."""
    split: dict[str, str] = {}
    for ids in strata.values():
        order = sorted(ids)
        random.Random(seed).shuffle(order)
        n_dev = math.ceil(len(order) / 2)
        for k, item in enumerate(order):
            split[item] = "dev" if k < n_dev else "test"
    return split
