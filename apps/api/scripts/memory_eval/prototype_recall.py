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
    max_inject_plain: int = 1  # 회상 단서가 없는 보통 턴
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


# ---------------------------------------------------------------- 오프라인 회상 어댑터


@dataclass
class Retriever:
    """`recall_offline.Retriever` 모양. 에피소드 명사는 처음 볼 때 한 번 계산해 둔다."""

    method: str  # substring · kiwi · kiwi_kw
    params: Params = field(default_factory=Params)
    supplement: str = "all"
    names: tuple[str, ...] = ()
    kw_table: Mapping[tuple[str, str], float] | None = None  # (에피소드 id, 정규화한 사용자 글) → 유사도
    _nouns: dict[str, frozenset[str]] = field(default_factory=dict)
    log: list[dict[str, Any]] | None = None

    def episode_nouns(self, episode: Episode) -> frozenset[str]:
        if episode.id not in self._nouns:
            if self.method == "substring":
                self._nouns[episode.id] = episode_nouns_substring(episode.nouns)
            else:
                self._nouns[episode.id] = episode_nouns_kiwi(
                    episode.nouns, episode.title, episode.detail, supplement=self.supplement
                )
        return self._nouns[episode.id]

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
        if self.method == "substring":
            pool = frozenset(x for row in rows for x in row.nouns)
            query = query_nouns_substring(user_text, previous_assistant, episode_nouns=pool, names=self.names)
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


# 개발 절반 튜닝 결과(격자 τ 0.20~0.60 × 흔한 명사 비율 0.2·0.3·0.4 에서 직접 형식 recall@3 → 대명사 → 보통 턴 주입률 → τ 순).
SELECTED = Params(tau=0.60, common_ratio=0.2)
_DEFAULTS: dict[str, Retriever] = {
    "a": Retriever("substring", params=SELECTED),
    "b": Retriever("kiwi", params=SELECTED),
}
