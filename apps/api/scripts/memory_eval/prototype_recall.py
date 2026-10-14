"""시제품 회상 — 오프라인 회상(`recall_offline`)에 꽂는 검색 함수 셋과 그 바탕의 순수 점수 함수.

명사 방식 셋을 같은 점수식으로 비교한다.
- ⓐ `substring`: 에피소드 명사 = 모델이 준 명사를 공백으로 쪼갠 조각. 질의 명사 = 에피소드 명사 중 글에 걸린 것(2자 이상은
  부분 문자열, 1자는 어절 경계 + 선택 조사). 형태소기가 없다.
- ⓑ `kiwi`: 에피소드 명사 = ⓐ 조각 ∪ 모델 명사를 형태소기로 다시 나눈 명사 ∪ 제목·본문의 형태소기 명사(쓰기 시점 보충).
  질의 명사 = 글의 형태소기 명사(일반·고유 명사, 외국어).
- ⓒ `kiwi_kw`: ⓑ + 키워드 유사도(사용자 메시지와 에피소드 키워드의 `pg_trgm` `word_similarity` 최댓값 — 값은 미리 계산한
  표로 받는다).

점수(운영 회상과 같은 식): 에피소드가 `min_episodes` 개 미만이면 회상하지 않는다. 명사 가중 `w = ln((N+1)/(df+1)) + 1`,
방 에피소드의 `common_ratio` 를 넘게 나오는 명사는 질의에서 뺀다. 임계용 점수는 드문 명사 하나를 1 로 둔 절대 척도(상한 1)이고
순위는 상한 없는 원점수다 — 상한 있는 값으로 순위를 매기면 드문 명사 하나와 셋을 가진 장면이 동점이 된다. 사용자 메시지에
질의 명사가 처음부터 없고 시간 단서가 있을 때만 직전 AI 응답 명사(가장 최근 스냅샷 두 개의 에피소드 명사를 뺀 것)로 찾는다.
사용자 명사가 흔한 명사 제외로만 비게 된 경우는 회상하지 않는다."""

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from api.chat.keyword_notes import normalize_keyword_text

from memory_eval.recall_offline import Episode, Ranked

# 질의에서 빼는 낱말 — 일반 대명사·때 표현과 회상 질문에 흔한 일반 명사.
STOPWORDS = frozenset(
    "사람 것 거 때 수 등 중 날 일 오늘 지금 우리 너 나 저 여기 거기 정말 진짜 뭐 무엇 "
    "예전 기억 처음 얘기 이야기 생각 기분 느낌 옛날 지난번 저번 그때".split()
)
TIME_CUE = re.compile(r"예전에|처음|지난번|저번|그때|옛날|전에\s|기억(나|해|하)")
# 회상 질문 표지 — 이 표지가 있는 턴만 최대 3개를 싣고, 없는 보통 턴은 임계를 넘는 최고점 1개만 싣는다. 시간 단서에 "기억 안·
# 뭐였·뭐더라·~였지?·~었지?·~였더라·전에 말한·~라고 했지·말한 적" 같은 되묻는 끝말을 더했다(개발 문항 질문으로 정함).
RECALL_CUE = re.compile(
    TIME_CUE.pattern
    + r"|기억\s?안|뭐였|뭐더라|(였|었)(지|더라)\s*[?？]|었더라|였더라|전에\s?말한|(라고|다고)\s?했(었)?지|(말|얘기|이야기)한\s?적"
)
PARTICLES = "이|가|을|를|은|는|도|만|에|에서|랑|이랑|하고|과|와|의"
KIWI_NOUN_TAGS = frozenset({"NNG", "NNP", "SL"})
MAX_EPISODE_NOUNS = 30
_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")
# 형태소기 없는 보충(e): 어절 끝의 흔한 조사 하나를 뗀다(긴 것부터). 같은 규칙을 저장·질의 양쪽에 쓰므로 "고양이 → 고양"처럼
# 잘못 떼도 양쪽이 같게 틀려 겹침은 유지된다.
_TRAILING_PARTICLE = re.compile(
    r"(에서|에게|한테|까지|부터|이랑|으로|처럼|보다|하고|은|는|이|가|을|를|에|로|와|과|도|만|의|랑)$"
)
_NON_WORD = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class EpisodeNouns:
    id: str
    nouns: frozenset[str]
    importance: int
    end_turn: int
    snapshot: int  # 접힌 순서(클수록 최근)
    kw_sim: float = 0.0


@dataclass(frozen=True)
class Query:
    user: frozenset[str]  # 이름·불용어를 뺀 사용자 메시지 명사
    assistant: frozenset[str]  # 직전 AI 응답 명사(사용자 명사를 뺀 것)
    time_cue: bool


@dataclass(frozen=True)
class Params:
    tau: float = 0.35
    common_ratio: float = 0.3
    kw_threshold: float = 0.5
    use_kw: bool = False
    min_episodes: int = 5
    max_inject: int = 3
    max_inject_plain: int = 1  # 회상 단서가 없는 보통 턴(운영과 같은 1이 기본, 격자에서 2·3 도 잰다)
    # 조사 떼기(rule) 질의에서 붙은 어절("장비점검하던")이 그 앞머리의 2자 이상 장면 명사("장비")와 겹치게 할지. 운영은 아직 끔.
    prefix_match: bool = False
    w_noun: float = 0.7
    w_kw: float = 0.3
    w_importance: float = 0.05
    w_recency: float = 0.02


@dataclass(frozen=True)
class Scored:
    id: str
    s: float  # 임계용(상한 1)
    r: float  # 순위용(상한 없음)
    overlap: frozenset[str]
    end_turn: int = 0
    snapshot: int = 0
    kw: float = 0.0


def time_cue(text: str) -> bool:
    return TIME_CUE.search(text) is not None


def recall_cue(text: str) -> bool:
    return RECALL_CUE.search(text) is not None


def clean_noun(noun: str) -> str:
    return _EDGE_PUNCT.sub("", normalize_keyword_text(noun).strip())


def _keep(noun: str, names: Iterable[str]) -> bool:
    return bool(noun) and noun not in STOPWORDS and noun not in {normalize_keyword_text(n) for n in names}


def episode_nouns_substring(nouns: Iterable[str]) -> frozenset[str]:
    """모델이 준 명사를 공백으로 쪼갠 조각(쪼개기 전 원형은 넣지 않는다), 1자도 살린다."""
    out: list[str] = []
    for noun in nouns:
        for piece in noun.split():
            cleaned = clean_noun(piece)
            if cleaned and cleaned not in STOPWORDS and cleaned not in out:
                out.append(cleaned)
    return frozenset(out[:MAX_EPISODE_NOUNS])


def _one_char_pattern(noun: str) -> re.Pattern[str]:
    return re.compile(rf"(^|\s){re.escape(noun)}({PARTICLES})?(\s|$|[.,!?…~])")


def matches(noun: str, text: str) -> bool:
    if len(noun) >= 2:
        return noun in text
    return _one_char_pattern(noun).search(text) is not None


def query_nouns_substring(
    user_text: str, previous_assistant: str, *, episode_nouns: frozenset[str], names: Iterable[str]
) -> Query:
    user_norm = normalize_keyword_text(user_text)
    assistant_norm = normalize_keyword_text(previous_assistant)
    user = frozenset(n for n in episode_nouns if _keep(n, names) and matches(n, user_norm))
    assistant = frozenset(n for n in episode_nouns if _keep(n, names) and matches(n, assistant_norm)) - user
    return Query(user=user, assistant=assistant, time_cue=time_cue(user_text))


def rule_tokens(text: str) -> list[str]:
    """공백으로 나눈 어절에서 기호를 지우고 끝 조사 하나를 뗀 2자 이상 토큰(불용어 제외, 중복 제거, 나온 순서)."""
    out: list[str] = []
    for word in normalize_keyword_text(text).split():
        token = _TRAILING_PARTICLE.sub("", _NON_WORD.sub("", word))
        if len(token) >= 2 and token not in STOPWORDS and token not in out:
            out.append(token)
    return out


def episode_nouns_rule(llm_nouns: Iterable[str], title: str, detail: str) -> frozenset[str]:
    """(e) 쓰기 시점 명사 = 모델 명사의 공백 조각 ∪ 제목·본문의 조사 뗀 토큰(형태소기 없음)."""
    out = list(episode_nouns_substring(llm_nouns))
    for token in rule_tokens(f"{title} {detail}"):
        if token not in out:
            out.append(token)
    return frozenset(out[:MAX_EPISODE_NOUNS])


def prefix_hits(tokens: Iterable[str], nouns: Iterable[str]) -> set[str]:
    """질의 토큰이 2자 이상 장면 명사로 시작하면 그 명사. 1자 명사는 여기서 걸지 않는다 — 1자 명사가 앞머리로 걸리면
    "빵집"의 빵, "차례"의 차처럼 뜻이 다른 낱말까지 겹쳐, 1자는 어절 경계 규칙(`matches`)만 쓴다."""
    tokens = tuple(tokens)
    return {noun for noun in nouns if len(noun) >= 2 and any(token.startswith(noun) for token in tokens)}


def query_nouns_rule(
    user_text: str,
    previous_assistant: str,
    *,
    episode_nouns: frozenset[str],
    names: Iterable[str],
    prefix_match: bool = False,
) -> Query:
    """(e) 질의 = 같은 규칙의 토큰 ∪ 1자 에피소드 명사 중 어절 경계로 걸린 것. 사용자 쪽은 그중 방 에피소드에 한 번이라도
    나온 토큰(df > 0, `episode_nouns` 에 있는 것)만 남긴다 — 조사 떼기 토큰은 "그거·어디·뒀더라" 같은 어절도 남겨, 거르지
    않으면 대명사 후속 질문의 사용자 질의가 비지 않아 직전 AI 응답으로 찾는 경로에 들어가지 못한다. 흔한 명사 제외는 이
    뒤(점수 함수)에서 하므로, 흔한 명사만 있던 질의("그때 회의 어땠더라?")는 여기서 비지 않고 회상 없음이 된다.

    `prefix_match` 를 켜면 조사 하나로 끝나지 않아 통째로 남은 어절도 앞머리의 장면 명사로 겹친다(`prefix_hits`). 이렇게 더한
    명사도 장면 명사이므로 사용자 쪽 거르기를 지나고, 흔한 명사 제외·절대 척도 임계는 점수 함수가 똑같이 건다."""
    names = tuple(names)
    one_char = [n for n in episode_nouns if len(n) == 1]

    def side(text: str) -> frozenset[str]:
        norm = normalize_keyword_text(text)
        tokens = rule_tokens(text)
        hits = set(tokens) | {n for n in one_char if matches(n, norm)}
        if prefix_match:
            hits |= prefix_hits(tokens, episode_nouns)
        return frozenset(n for n in hits if _keep(n, names))

    user = side(user_text) & episode_nouns
    return Query(user=user, assistant=side(previous_assistant) - user, time_cue=time_cue(user_text))


@cache
def _kiwi() -> Any:
    from kiwipiepy import Kiwi  # type: ignore[import-untyped]  # 실험 가상환경에만 깐 형태소기(잠금 파일 밖)

    return Kiwi()


@cache
def _kiwi_nouns_cached(text: str, tags: frozenset[str], min_len: int) -> tuple[str, ...]:
    out: list[str] = []
    for token in _kiwi().tokenize(text):
        if token.tag in tags:
            noun = clean_noun(token.form)
            if len(noun) >= min_len and noun not in out:
                out.append(noun)
    return tuple(out)


def kiwi_nouns(text: str, *, tags: frozenset[str] = KIWI_NOUN_TAGS, min_len: int = 1) -> list[str]:
    return list(_kiwi_nouns_cached(text, tags, min_len))


def query_nouns_kiwi(user_text: str, previous_assistant: str, *, names: Iterable[str]) -> Query:
    names = tuple(names)
    user = frozenset(n for n in kiwi_nouns(user_text) if _keep(n, names))
    assistant = frozenset(n for n in kiwi_nouns(previous_assistant) if _keep(n, names)) - user
    return Query(user=user, assistant=assistant, time_cue=time_cue(user_text))


def episode_nouns_kiwi(llm_nouns: Iterable[str], title: str, detail: str, *, supplement: str = "all") -> frozenset[str]:
    """ⓑ 쓰기 시점 명사. `supplement` = 제목·본문에서 보충할 범위: all(일반·고유·외국어, 1자 포함) · nnp(고유·외국어만) ·
    nng2(고유·외국어 + 2자 이상 일반) · none(보충 없음 — 모델 명사의 재분석만)."""
    llm_nouns = list(llm_nouns)
    out = list(episode_nouns_substring(llm_nouns))
    for noun in llm_nouns:
        for piece in kiwi_nouns(noun):
            if piece not in STOPWORDS and piece not in out:
                out.append(piece)
    text = f"{title}\n{detail}"
    extra: list[str] = []
    if supplement == "all":
        extra = kiwi_nouns(text)
    elif supplement == "nnp":
        extra = kiwi_nouns(text, tags=frozenset({"NNP", "SL"}))
    elif supplement == "nng2":
        extra = kiwi_nouns(text, tags=frozenset({"NNP", "SL"})) + kiwi_nouns(text, tags=frozenset({"NNG"}), min_len=2)
    elif supplement != "none":
        raise ValueError(supplement)
    for noun in extra:
        if noun not in STOPWORDS and noun not in out:
            out.append(noun)
    return frozenset(out[:MAX_EPISODE_NOUNS])


def score_episodes(rows: Sequence[EpisodeNouns], query: Query, *, current_turn: int, params: Params) -> list[Scored]:
    """임계 점수·순위 점수를 모든 에피소드에 매겨 순위 순으로 돌려준다. 회상하지 않는 경우는 빈 목록."""
    n = len(rows)
    if n < params.min_episodes:
        return []
    df: dict[str, int] = {}
    for row in rows:
        for noun in row.nouns:
            df[noun] = df.get(noun, 0) + 1

    def plus(nouns: frozenset[str]) -> frozenset[str]:
        return frozenset(x for x in nouns if 0 < df.get(x, 0) and df[x] / n <= params.common_ratio)

    if query.user:
        q = plus(query.user)
    elif query.time_cue:
        recent = sorted({row.snapshot for row in rows}, reverse=True)[:2]
        recent_nouns = frozenset(x for row in rows if row.snapshot in recent for x in row.nouns)
        q = plus(query.assistant - recent_nouns)
    else:
        return []
    if not q:
        return []

    def w(noun: str) -> float:
        return math.log((n + 1) / (df[noun] + 1)) + 1

    w_rare = math.log((n + 1) / 2) + 1
    scored = []
    for row in rows:
        overlap = q & row.nouns
        weight = sum(w(x) for x in overlap)
        s_q = min(1.0, weight / w_rare)
        s_kw = row.kw_sim if params.use_kw and row.kw_sim >= params.kw_threshold else 0.0
        extra = params.w_importance * (min(max(row.importance, 1), 5) - 1) / 4
        if not query.time_cue:
            extra += params.w_recency * row.end_turn / max(current_turn, 1)
        s = params.w_noun * s_q + params.w_kw * s_kw + extra
        r = weight + w_rare * (params.w_kw * s_kw + extra) / params.w_noun
        scored.append(Scored(row.id, s, r, overlap, row.end_turn, row.snapshot, s_kw))
    scored.sort(key=lambda x: (-x.r, -x.end_turn, -x.snapshot, x.id))
    return scored


def select_injected(scored: Sequence[Scored], params: Params, *, recall_cue: bool) -> list[str]:
    cap = params.max_inject if recall_cue else params.max_inject_plain
    return [x.id for x in scored if x.s >= params.tau][:cap]


# 회상 줄 끝의 화자 꼬리표. 인물·섞임은 운영 회상 섹션과 같은 낱말이고, 사용자 꼬리표는 운영에 아직 없다 — 사용자가 스스로
# 말한 장면이 꼬리표 없이 실리면 꼬리표 없는 지문 장면과 줄 모양이 같아, 누가 한 말인지가 줄에서 사라진다.
USER_TAIL = " (사용자의 말)"
ASSERTION_TAILS = {"character": " (인물의 말)", "mixed": " (인물의 말 포함)", "user": USER_TAIL}


def recall_line(title: str, detail: str, asserted_by: str, *, user_tail: bool = True) -> str:
    """회상 섹션 한 줄. `user_tail=False` 는 지금 운영과 같은 줄(사용자 장면에 꼬리표 없음)이다."""
    tails = ASSERTION_TAILS if user_tail else {k: v for k, v in ASSERTION_TAILS.items() if k != "user"}
    return f"- {title}: {detail}{tails.get(asserted_by, '')}"


# ---------------------------------------------------------------- 오프라인 회상 어댑터


@dataclass
class Retriever:
    """`recall_offline.Retriever` 모양. 에피소드 명사는 처음 볼 때 한 번 계산해 둔다."""

    method: str  # substring(ⓐ) · kiwi(ⓑ) · kiwi_write(쓰기만 Kiwi, 질의는 부분 문자열) · rule(형태소기 없는 조사 떼기)
    params: Params = field(default_factory=Params)
    supplement: str = "all"
    names: tuple[str, ...] = ()
    kw_table: Mapping[tuple[str, str], float] | None = None  # (에피소드 id, 정규화한 사용자 글) → 유사도
    _nouns: dict[tuple[str, str, str, tuple[str, ...]], frozenset[str]] = field(default_factory=dict)
    log: list[dict[str, Any]] | None = None

    def episode_nouns(self, episode: Episode) -> frozenset[str]:
        # id 만으로 캐시하면 같은 id 의 다른 에피소드(다른 추출 판·테스트)가 앞 내용을 물려받는다.
        key = (episode.id, episode.title, episode.detail, tuple(episode.nouns))
        if key not in self._nouns:
            if self.method == "substring":
                self._nouns[key] = episode_nouns_substring(episode.nouns)
            elif self.method == "rule":
                self._nouns[key] = episode_nouns_rule(episode.nouns, episode.title, episode.detail)
            else:
                self._nouns[key] = episode_nouns_kiwi(
                    episode.nouns, episode.title, episode.detail, supplement=self.supplement
                )
        return self._nouns[key]

    def __call__(
        self, episodes: Sequence[Episode], *, user_text: str, previous_assistant: str, current_turn: int
    ) -> list[Ranked]:
        snapshots = {t: i for i, t in enumerate(sorted({e.available_from_turn or 0 for e in episodes}))}
        user_key = normalize_keyword_text(user_text)
        rows = [
            EpisodeNouns(
                id=e.id,
                nouns=self.episode_nouns(e),
                importance=e.importance,
                end_turn=e.end_turn,
                snapshot=snapshots[e.available_from_turn or 0],
                kw_sim=(self.kw_table or {}).get((e.id, user_key), 0.0),
            )
            for e in episodes
        ]
        pool = frozenset(x for row in rows for x in row.nouns)
        if self.method in ("substring", "kiwi_write"):
            query = query_nouns_substring(user_text, previous_assistant, episode_nouns=pool, names=self.names)
        elif self.method == "rule":
            query = query_nouns_rule(
                user_text,
                previous_assistant,
                episode_nouns=pool,
                names=self.names,
                prefix_match=self.params.prefix_match,
            )
        else:
            query = query_nouns_kiwi(user_text, previous_assistant, names=self.names)
        scored = score_episodes(rows, query, current_turn=current_turn, params=self.params)
        injected = set(select_injected(scored, self.params, recall_cue=recall_cue(user_text)))
        if self.log is not None:
            self.log.append({"user": sorted(query.user), "assistantN": len(query.assistant), "timeCue": query.time_cue})
        # 순위 목록에는 무엇이든 겹친 에피소드만 싣는다(겹침 없이 중요도·최근성만 받은 장면은 후보가 아니다).
        return [Ranked(x.id, x.s, x.id in injected) for x in scored if x.overlap or x.kw > 0]


def make_retriever(method: str, **kwargs: Any) -> Callable[..., list[Ranked]]:
    return Retriever(method=method, **kwargs)


def retrieve_a(episodes: Sequence[Episode], **kw: Any) -> list[Ranked]:
    return _DEFAULTS["a"](episodes, **kw)


def retrieve_b(episodes: Sequence[Episode], **kw: Any) -> list[Ranked]:
    return _DEFAULTS["b"](episodes, **kw)


def retrieve_e(episodes: Sequence[Episode], **kw: Any) -> list[Ranked]:
    """확정 방식: 형태소기 없이 조사 떼기 토큰을 쓰기·질의 양쪽에 쓴다. 운영 회상 구현은 이 함수와 같은 토큰·점수·순위를
    내야 한다(기준 벡터로 대조)."""
    return _DEFAULTS["e"](episodes, **kw)


# 개발 절반 튜닝 결과(격자 τ 0.20~0.60 × 흔한 명사 비율 0.2·0.3·0.4 에서 직접 형식 recall@3 → 대명사 → 보통 턴 주입률 → τ 순).
SELECTED = Params(tau=0.60, common_ratio=0.2)
_DEFAULTS: dict[str, Retriever] = {
    "a": Retriever("substring", params=SELECTED),
    "b": Retriever("kiwi", params=SELECTED),
    "e": Retriever("rule", params=SELECTED),
}
