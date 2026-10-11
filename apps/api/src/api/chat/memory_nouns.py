"""장면 기억의 명사 토큰 — 형태소기 없이 어절 끝 조사 하나를 떼는 규칙.

장면을 저장할 때(이 모듈의 `episode_nouns`)와 회상 질의를 만들 때 같은 `rule_tokens` 를 써야 두 쪽 토큰이 겹친다. 규칙:
NFC·casefold(`normalize_keyword_text`) → 공백으로 어절을 나눔 → 어절의 기호(`\\W`·`_`)를 전부 지움 → 끝 조사 하나를 뗌(한
번만, 긴 조사부터) → 2자 이상이고 불용어가 아니며 앞에 나오지 않은 것만, 나온 순서대로. 어미는 떼지 않아 동사 어절은 그대로
토큰이 된다.

조사를 하나만 떼므로 끝 글자가 조사와 같은 낱말은 맨 꼴과 조사 붙은 꼴이 갈린다("회의" → `회`(1자라 버림), "회의를" →
`회의`). 형태소기를 쓰면 이 비대칭이 없어지지만 워커마다 수백 MB 를 더 올려야 해서 쓰지 않는다. 1자 명사(빵·차·꽃)는 이
토큰화로는 남지 않고, 모델이 준 명사로만 저장된다.

평가 하네스의 시제품 구현과 같은 결과를 내야 한다 — 테스트가 하네스가 낸 기준 벡터(`tests/fixtures/memory_recall_vectors.json`)
와 견준다. 이 모듈은 하네스를 import 하지 않는다."""

import re
from collections.abc import Iterable

from api.chat.keyword_notes import normalize_keyword_text
from api.db.models.chat import EPISODE_NOUNS_MAX

# 질의에도 장면 명사에도 넣지 않는 낱말 — 대명사·때 표현, 그리고 회상 질문에 흔히 붙는 일반 명사("기억·예전·얘기").
STOPWORDS = frozenset(
    "사람 것 거 때 수 등 중 날 일 오늘 지금 우리 너 나 저 여기 거기 정말 진짜 뭐 무엇 "
    "예전 기억 처음 얘기 이야기 생각 기분 느낌 옛날 지난번 저번 그때".split()
)
# 끝(`$`)에 붙은 조사만 뗀다. 가장 왼쪽에서 시작하는 일치가 이기므로 "에서"·"이랑"처럼 두 글자 조사가 한 글자 조사보다 먼저
# 떨어진다(대안의 순서와는 무관하다).
_TRAILING_PARTICLE = re.compile(
    r"(에서|에게|한테|까지|부터|이랑|으로|처럼|보다|하고|은|는|이|가|을|를|에|로|와|과|도|만|의|랑)$"
)
_NON_WORD = re.compile(r"[\W_]+")
_EDGE_NON_WORD = re.compile(r"^[\W_]+|[\W_]+$")


def rule_tokens(text: str) -> list[str]:
    """`text` 의 조사 뗀 토큰(2자 이상, 불용어 제외, 중복 제거, 나온 순서)."""
    tokens: list[str] = []
    for word in normalize_keyword_text(text).split():
        token = _TRAILING_PARTICLE.sub("", _NON_WORD.sub("", word))
        if len(token) >= 2 and token not in STOPWORDS and token not in tokens:
            tokens.append(token)
    return tokens


def episode_nouns(model_nouns: Iterable[str], title: str, detail: str) -> list[str]:
    """장면 하나의 검색용 명사. 모델이 준 명사를 공백으로 쪼갠 조각(앞뒤 기호를 떼고, 불용어는 버리고, 1자는 남긴다)이
    먼저이고, 그 뒤에 제목·본문의 `rule_tokens` 를 더한다. 중복 없이 앞 `EPISODE_NOUNS_MAX` 개까지.

    조각만 남기고 쪼개기 전 원형("렌즈 케이스")은 넣지 않는다 — 질의 쪽 토큰은 어절 단위라 원형은 겹칠 일이 없고, 같은
    장면이 조각 수만큼 이중으로 세지기만 한다."""
    nouns: list[str] = []
    for noun in model_nouns:
        for piece in noun.split():
            cleaned = _EDGE_NON_WORD.sub("", normalize_keyword_text(piece).strip())
            if cleaned and cleaned not in STOPWORDS and cleaned not in nouns:
                nouns.append(cleaned)
    for token in rule_tokens(f"{title} {detail}"):
        if token not in nouns:
            nouns.append(token)
    return nouns[:EPISODE_NOUNS_MAX]
