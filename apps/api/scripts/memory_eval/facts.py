"""사실 계층의 순수 계산 — 키 정규화, 키별 최신 읽기, 렌더 순서와 글자 상한. LLM·DB 없음.

행 칸: `kind`(relation·fact), `subject`, `object`(관계만), `attribute`(사실만), `fact_key`, `value`, `truth_status`(confirmed·claimed·
disproved), `asserted_by`(user·character·narration), `speaker`, `known_by`(배열, 없으면 공개·불명), `importance` 1~5, 원문 범위.
행은 접힌 창마다 덧붙기만 한다(append-only) — 행 목록의 순서가 곧 쓴 순서다.

- 키 = 종류 + 주어 + (관계는 대상, 사실은 속성). 칸마다 키워드 정규화(NFC·casefold) 뒤 공백을 한 칸으로 줄이고 앞뒤를 지운다.
- 키별 최신: 같은 키의 마지막 행이 이긴다. 단 반증된 값은 뒤의 주장으로 되살아나지 않는다 — 같은 키에 같은 값의 반증 행이
  앞에 있으면 마지막 행이 반증이 아니어도 그 반증 행이 이긴다. 값이 다른 옛 주장의 반증 행은 새 값을 가리지 않는다(정정).
- 렌더 순서: 관계 → 아는 사람이 정해진 사실 → 반증 → 그 밖의 사실. 묶음 안은 중요도가 높은 쪽, 같으면 최근 쪽이 먼저다.
- 렌더 상한: 줄을 순서대로 이어 붙이다 다음 줄이 상한(줄바꿈 포함 글자 수)을 넘으면 거기서 멈추고 나머지는 모두 탈락이다.
- 섹션 선택(`select_section`): `constant` 는 위 렌더 순서로만 자르고, `mixed` 는 상한의 앞 몫을 렌더 순서로, 나머지를 이번 턴
  사용자 메시지와 명사가 겹치는 행으로 채운다(질의가 없으면 둘이 같다).
  줄 모양은 운영 사실 섹션의 줄 꼴을 따른다(`render_line`)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from api.chat.keyword_notes import normalize_keyword_text

from memory_eval.metrics import answer_matches, normalize_match_text, wilson_interval
from memory_eval.prototype_recall import EpisodeNouns, Params, query_nouns_rule, rule_tokens, score_episodes

KINDS = ("relation", "fact")
TRUTH_STATUSES = ("confirmed", "claimed", "disproved")
RENDER_MAX_CHARS = 700
# 사실 섹션 선택 방식. `mixed` = 상한의 앞 몫은 렌더 순서(상시), 나머지는 이번 턴 사용자 메시지와 명사가 겹치는 행(관련).
SECTION_MODES = ("constant", "mixed")
# 상시 몫(상한 대비)과 관련 행의 점수 임계 — 개발 절반 오프라인 격자(`section-grid`)로 정한 값.
CONSTANT_RATIO = 0.3
RELEVANCE_TAU = 0.6
# 관련 점수에서 질의로 쓰지 않는 흔한 명사의 문턱(방 행 가운데 이 비율을 넘게 나오는 명사) — 장면 회상과 같은 값.
RELEVANCE_COMMON_RATIO = 0.2
# 추출 입력에 주는 기존 키 목록의 줄 수 상한.
EXISTING_KEYS_MAX = 40


def normalize_part(text: str | None) -> str:
    return " ".join(normalize_keyword_text(text or "").split())


def fact_key(kind: str, subject: str | None, target: str | None) -> str:
    return "|".join(normalize_part(part) for part in (kind, subject, target))


def target_of(row: Mapping[str, Any]) -> str | None:
    return row.get("object") if row.get("kind") == "relation" else row.get("attribute")


def row_key(row: Mapping[str, Any]) -> str:
    return fact_key(str(row.get("kind", "")), row.get("subject"), target_of(row))


def latest_by_key(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """키마다 이긴 행 하나씩, 이긴 행이 쓰인 순서대로. 돌려주는 행에는 쓴 순번(`_order`)을 붙인다."""
    groups: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for order, row in enumerate(rows):
        groups.setdefault(row_key(row), []).append((order, row))
    winners: list[tuple[int, Mapping[str, Any]]] = []
    for members in groups.values():
        order, winner = members[-1]
        if winner.get("truth_status") != "disproved":
            value = normalize_part(winner.get("value"))
            disproved_rows = [
                (o, r)
                for o, r in members
                if r.get("truth_status") == "disproved" and normalize_part(r.get("value")) == value
            ]
            if disproved_rows:
                order, winner = disproved_rows[-1]
        winners.append((order, winner))
    return [{**row, "_order": order} for order, row in sorted(winners, key=lambda pair: pair[0])]


def _group(row: Mapping[str, Any]) -> int:
    if row.get("kind") == "relation":
        return 0
    if row.get("known_by"):
        return 1
    if row.get("truth_status") == "disproved":
        return 2
    return 3


def render_order(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """키별 최신 행(`_order` 가 붙은 것)을 렌더 순서로."""
    return sorted(rows, key=lambda r: (_group(r), -int(r.get("importance") or 0), -int(r.get("_order") or 0)))


def _is_user_speaker(row: Mapping[str, Any]) -> bool:
    if row.get("asserted_by") == "user":
        return True
    return normalize_part(row.get("speaker")) == normalize_part(USER_PLACEHOLDER)


def render_line(row: Mapping[str, Any]) -> str:
    """운영 사실 섹션과 같은 줄 꼴. 반증은 줄 머리에, 주장 꼬리표 → 아는 사람 꼬리표 순으로 끝에 붙고 확정은 꼬리표가 없다.
    화자가 사용자인지는 `asserted_by` 나 자리표시로 바뀐 `speaker`(`alias_user`)로 가린다."""
    if row.get("kind") == "relation":
        body = f"{row.get('subject')} → {row.get('object')}: {row.get('value')}"
    else:
        body = f"{row.get('subject')} · {row.get('attribute')}: {row.get('value')}"
    status = row.get("truth_status")
    line = f"- (사실 아님으로 밝혀짐) {body}" if status == "disproved" else f"- {body}"
    if status == "claimed":
        speaker = row.get("speaker")
        if speaker and not _is_user_speaker(row):
            line += f" ({speaker}의 말)"
        else:
            line += " (사용자의 말)" if _is_user_speaker(row) else " (인물의 말)"
    if row.get("known_by"):
        line += f" ({'·'.join(str(n) for n in row['known_by'])}만 앎)"
    return line


def row_nouns(row: Mapping[str, Any]) -> frozenset[str]:
    """관련 점수에 쓰는 행 명사: 주어·대상(관계)이나 속성(사실)·값을 이은 글의 조사 뗀 토큰(장면 회상과 같은 `rule_tokens`)."""
    return frozenset(rule_tokens(f"{row.get('subject') or ''} {target_of(row) or ''} {row.get('value') or ''}"))


def relevant_rows(
    latest: Sequence[Mapping[str, Any]],
    query: str,
    *,
    names: Sequence[str] = (),
    tau: float = RELEVANCE_TAU,
    current_turn: int | None = None,
) -> list[Mapping[str, Any]]:
    """`latest`(키별 최신 행) 가운데 `query`(이번 턴 사용자 메시지)와 명사가 겹치고 점수가 `tau` 이상인 행, 순위 순.

    토큰·점수는 장면 회상의 확정 규칙을 그대로 쓴다(`prototype_recall.query_nouns_rule`·`score_episodes`): 질의 = 사용자
    메시지의 조사 뗀 토큰에서 이름·불용어를 빼고 방 행에 한 번이라도 나온 것만, 방 행의 `RELEVANCE_COMMON_RATIO` 를 넘게
    나오는 명사는 뺀다, 명사 가중 `ln((N+1)/(df+1)) + 1` 을 드문 명사 하나 = 1 로 둔 절대 척도(상한 1)에 중요도·최근성
    (끝 턴 / 지금 턴, 시간 단서가 있으면 끔)을 조금 더한 값이 임계, 순위는 상한 없는 원점수. 행이 `min_episodes`(5) 개 미만이면
    관련 행은 없다. 직전 AI 응답 쪽 질의는 쓰지 않는다."""
    nouns = [row_nouns(r) for r in latest]
    turn = current_turn or max((int(r.get("end_turn") or 0) for r in latest), default=1)
    candidates = [
        EpisodeNouns(
            id=str(i),
            nouns=nouns[i],
            importance=int(r.get("importance") or 1),
            end_turn=int(r.get("end_turn") or 0),
            snapshot=0,
        )
        for i, r in enumerate(latest)
    ]
    pool = frozenset(n for ns in nouns for n in ns)
    q = query_nouns_rule(query, "", episode_nouns=pool, names=names)
    params = Params(tau=tau, common_ratio=RELEVANCE_COMMON_RATIO)
    scored = score_episodes(candidates, q, current_turn=turn, params=params)
    return [latest[int(x.id)] for x in scored if x.overlap and x.s >= tau]


@dataclass(frozen=True)
class Section:
    """사실 섹션 하나. `kept` 는 렌더 순서, `relevant` 는 관련 쪽이 실은 행(상시 쪽과 겹친 행은 빠진다)."""

    kept: list[Mapping[str, Any]]
    dropped: list[Mapping[str, Any]]
    relevant: list[Mapping[str, Any]]
    text: str


def select_section(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_chars: int = RENDER_MAX_CHARS,
    mode: str = "mixed",
    query: str = "",
    names: Sequence[str] = (),
    constant_ratio: float = CONSTANT_RATIO,
    tau: float = RELEVANCE_TAU,
    current_turn: int | None = None,
) -> Section:
    """덧붙은 행 전부에서 사실 섹션을 고른다. 줄 비용 = 줄 글자 수 + 줄바꿈(첫 줄 빼고 1).

    - `constant`: 렌더 순서대로 이어 붙이다 다음 줄이 상한을 넘으면 멈춘다.
    - `mixed`: 렌더 순서 전부가 상한 안이면 `constant` 와 같다. 아니면 ① 상시 — 렌더 순서대로 `constant_ratio × 상한` 까지
      (다음 줄이 넘으면 멈춤), ② 관련 — `relevant_rows` 순위대로 상시에 없는 행을 상한까지(다음 줄이 넘으면 멈춤), ③ 남은
      자리는 ①이 멈춘 곳부터 렌더 순서대로 다시 채운다(관련 행이 없으면 결과가 `constant` 와 같다). 실린 행은 렌더 순서로 쓴다."""
    ordered = render_order(latest_by_key(rows))
    lines = [render_line(r) for r in ordered]
    chosen: list[int] = []
    used = 0

    def fits(i: int, limit: float) -> bool:
        return used + len(lines[i]) + (1 if chosen else 0) <= limit

    def take(i: int) -> None:
        nonlocal used
        used += len(lines[i]) + (1 if chosen else 0)
        chosen.append(i)

    def fill(limit: float, start: int = 0) -> int:
        for i in range(start, len(ordered)):
            if i in chosen:
                continue
            if not fits(i, limit):
                return i
            take(i)
        return len(ordered)

    relevant: list[int] = []
    if mode == "constant":
        fill(max_chars)
    elif mode == "mixed":
        stop = fill(constant_ratio * max_chars)
        if stop < len(ordered):
            index = {id(r): i for i, r in enumerate(ordered)}
            for row in relevant_rows(ordered, query, names=names, tau=tau, current_turn=current_turn):
                i = index[id(row)]
                if i in chosen:
                    continue
                if not fits(i, max_chars):
                    break
                take(i)
                relevant.append(i)
            fill(max_chars, stop)
    else:
        raise ValueError(f"사실 섹션 선택 방식은 {SECTION_MODES} 중 하나다: {mode}")
    picked = sorted(chosen)
    return Section(
        kept=[ordered[i] for i in picked],
        dropped=[r for i, r in enumerate(ordered) if i not in chosen],
        relevant=[ordered[i] for i in sorted(relevant)],
        text="\n".join(lines[i] for i in picked),
    )


def render(
    rows: Sequence[Mapping[str, Any]], *, max_chars: int = RENDER_MAX_CHARS, **selection: Any
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], str]:
    """덧붙은 행 전부를 받아 키별 최신으로 줄이고 렌더한다. (실린 행, 상한에 잘린 행, 렌더 글). 선택 인자는 `select_section`
    과 같다 — 질의가 없으면 어느 방식이든 렌더 순서대로 자른다."""
    section = select_section(rows, max_chars=max_chars, **selection)
    return section.kept, section.dropped, section.text


def existing_key_lines(rows: Sequence[Mapping[str, Any]], *, limit: int = EXISTING_KEYS_MAX) -> list[str]:
    """추출 입력의 기존 키 목록: 앞 창들의 행을 키별 최신으로 줄여 최근 `limit` 개를 `키 = 값 (진실 상태)` 줄로."""
    latest = latest_by_key(rows)[-limit:] if limit > 0 else []
    return [f"{row_key(r)} = {r.get('value')} ({r.get('truth_status')})" for r in latest]


# ---------------------------------------------------------------- 오프라인 지표

# 정답 묶음이 지금 값을 묻는 범주(정답 = 기대 사실의 값). 나머지 범주의 묶음은 질문의 답(귀속·거절·비밀 지킴)이라 값 비교에 쓰지 않는다.
_VALUE_BUNDLE_CATEGORIES = ("relation", "correction", "detail")


def expected_key(expected: Mapping[str, Any]) -> str:
    return row_key(expected)


def _names(value: Any) -> frozenset[str]:
    return frozenset(normalize_part(str(n)) for n in (value or []) if normalize_part(str(n)))


def _old_values(entry: Mapping[str, Any], want: str) -> list[str]:
    """그 사실의 옛 값(관계의 옛 태도, 뒤집힌 옛 주장)을 같은 정규화로. 지금 값과 같은 옛 값은 뺀다(옛 태도로 돌아간 관계)."""
    expected = entry.get("expected_fact") or {}
    raw = list(expected.get("history") or []) + [
        s.get("value") for s in expected.get("superseded") or [] if isinstance(s, Mapping)
    ]
    olds = [normalize_match_text(str(v)) for v in raw if v]
    return [o for o in olds if o and o != want]


def holds_old_value(row_value: str | None, entry: Mapping[str, Any]) -> bool:
    """행 값이 지금 값이 아니라 옛 값을 담는가. 새 값이 옛 값을 품는 꼴(`6월` → `6월 9일`)에서 옛 값 행이 느슨한 비교로 새 값
    안에 들어 맞는 것을 막는다. 옛 값과 같거나, 옛 값을 품되 지금 값은 품지 않거나, 옛 값 묶음(`reject_bundles`)을 채우되 지금
    값·정답 묶음은 채우지 않으면 옛 값이다."""
    expected = (entry.get("expected_fact") or {}).get("value")
    got = normalize_match_text(str(row_value or ""))
    want = normalize_match_text(str(expected or ""))
    has_new = bool(want) and want in got
    olds = _old_values(entry, want)
    if any(got == o for o in olds) or (any(o in got for o in olds) and not has_new):
        return True
    answer_key = entry.get("answer_key") or {}
    rejects = answer_key.get("reject_bundles") or []
    bundles = answer_key.get("bundles") or []
    if rejects and answer_matches(str(row_value or ""), rejects):
        return not has_new and not (bundles and answer_matches(str(row_value or ""), bundles))
    return False


def value_matches(row_value: str | None, entry: Mapping[str, Any]) -> bool:
    """값은 느슨히 본다: 정답 일치와 같은 정규화(NFC·casefold·공백 제거·숫자 표기) 뒤 기대 값과 행 값 가운데 한쪽이 다른
    쪽에 들어 있거나, 정답 묶음이 지금 값을 묻는 범주(관계·정정·디테일)에서 행 값이 그 묶음을 채우면 맞다. 단 옛 값을 담은
    행(`holds_old_value`)은 어느 범주든 맞지 않는다."""
    if holds_old_value(row_value, entry):
        return False
    expected = (entry.get("expected_fact") or {}).get("value")
    got = normalize_match_text(str(row_value or ""))
    want = normalize_match_text(str(expected or ""))
    if got and want and (want in got or got in want):
        return True
    bundles = (entry.get("answer_key") or {}).get("bundles") or []
    return (
        entry.get("category") in _VALUE_BUNDLE_CATEGORIES and bool(bundles) and answer_matches(str(row_value), bundles)
    )


def row_matches(row: Mapping[str, Any], entry: Mapping[str, Any], *, check_key: bool = True) -> bool:
    """행이 항목의 기대 사실을 담는가: 키(정규화 뒤 같음) · 진실 상태(같음) · 아는 사람(정규화한 이름 집합이 같음,
    기대가 공개면 행도 비어야 함) · 값(`value_matches`)."""
    expected = entry.get("expected_fact") or {}
    if check_key and row_key(row) != expected_key(expected):
        return False
    if row.get("truth_status") != expected.get("truth_status"):
        return False
    if _names(row.get("known_by")) != _names(expected.get("known_by")):
        return False
    return value_matches(row.get("value"), entry)


# 기대 사실이 사용자 쪽 인물을 가리키는 자리표시 이름.
USER_PLACEHOLDER = "사용자"


def alias_user(rows: Sequence[Mapping[str, Any]], user_name: str | None) -> list[dict[str, Any]]:
    """행의 주어·대상·화자·아는 사람에서 사용자의 이야기 속 이름을 기대 사실의 자리표시(`사용자`)로 바꾼다. 추출은 이야기 속 이름으로
    쓰고 기대 사실은 자리표시로 적으므로, 바꾸지 않으면 사용자에 관한 항목은 키·아는 사람이 늘 어긋난다."""
    if not user_name:
        return [dict(r) for r in rows]
    name = normalize_part(user_name)

    def swap(text: Any) -> Any:
        return USER_PLACEHOLDER if isinstance(text, str) and normalize_part(text) == name else text

    out = []
    for row in rows:
        known = row.get("known_by")
        out.append(
            {
                **row,
                "subject": swap(row.get("subject")),
                "object": swap(row.get("object")),
                "speaker": swap(row.get("speaker")),
                "known_by": [swap(n) for n in known] if known else known,
            }
        )
    return out


# 근사 일치의 값 문턱(글자 2-그램 다이스 계수).
NEAR_DICE = 0.5


def _bigrams(text: str) -> set[str]:
    t = normalize_match_text(text)
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _dice(a: str, b: str) -> float:
    x, y = _bigrams(a), _bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0


def _state_words(value: str) -> set[str]:
    """관계 값의 머리(`상태 낱말 — 근거` 의 앞, `·` 로 이은 낱말들)."""
    head = value.split("—", 1)[0] if "—" in value else ""
    return {normalize_part(w) for w in head.split("·") if normalize_part(w)}


def near_matches(row: Mapping[str, Any], entry: Mapping[str, Any]) -> bool:
    """키를 묻지 않는 근사 일치(진단): 진실 상태·아는 사람은 `row_matches` 와 같게 보고, 값은 관계면 상태 낱말이 하나라도
    겹치고, 사실이면 `value_matches` 이거나 글자 2-그램 다이스가 `NEAR_DICE` 이상이다. 옛 값을 담은 행은 맞지 않는다."""
    expected = entry.get("expected_fact") or {}
    if row.get("kind") != expected.get("kind") or row.get("truth_status") != expected.get("truth_status"):
        return False
    if _names(row.get("known_by")) != _names(expected.get("known_by")):
        return False
    value = str(row.get("value") or "")
    if holds_old_value(value, entry):
        return False
    if expected.get("kind") == "relation":
        return bool(_state_words(value) & _state_words(str(expected.get("value") or "")))
    return value_matches(value, entry) or _dice(value, str(expected.get("value") or "")) >= NEAR_DICE


def _rate(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson": wilson_interval(k, n)}


def fact_metrics(
    items: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    checkpoint: int | None = None,
    max_chars: int = RENDER_MAX_CHARS,
    with_rows: bool = False,
) -> dict[str, Any]:
    """사실 계층 오프라인 지표. 체크포인트를 주면 그때 읽을 수 있던 행(`available_from_turn` ≤ 체크포인트 + 1)과 그때 심기가
    모두 접힌 항목만 센다.

    항목 단위(기대 사실이 있는 항목, 범주별·전체):
    - `preserved`(사실 보존율): 덧붙은 행 가운데 `row_matches` 인 행이 하나라도 있다.
    - `preservedInRead`: 그 키의 키별 최신 행(읽기가 실제로 내놓는 행)이 `row_matches` 다.
    - `droppedByCap`(분모 = `preservedInRead` 인 항목): 그 최신 행이 렌더 상한에서 잘렸다.
    - 진단: `keyFound`(그 키의 행이 있다), `matchedIgnoringKey`(키만 빼고 맞는 행이 있다 — 키 이름이 갈려 놓친 것).
    - `readIgnoringKey`: 키만 빼고 맞는 행이 있고 그 행의 키별 최신 행도 키만 빼고 맞는다(속성 이름을 묻지 않는 읽기 보존 —
      같은 키의 뒤 행이 덮어써 읽기에서 사라진 것은 빠진다). `droppedByCapIgnoringKey`(분모 = `readIgnoringKey`): 그런 키가
      모두 렌더 상한에서 잘렸다.
    - `nearInRead`(진단): `near_matches` 인 행이 있고 그 키의 최신 행도 그렇다 — 관계는 기대 키(주어 → 대상)에서만 센다.
      값의 글자 그대로 포함만 보는 위 지표가 바꿔 쓴 값을 모두 놓치므로 함께 낸다. `nearDroppedByCap`: 그런 키가 모두 잘렸다.

    행 단위:
    - `duplicateKeyRate`: 같은 스냅샷(같은 추출 호출)에서 같은 키가 두 번 이상 나온 행 / 전체 행.
    - `restatedRate`: 앞 스냅샷에 같은 키·같은 값·같은 진실 상태 행이 이미 있는데 다시 쓴 행 / 전체 행(바뀐 것 없는 재진술).
    - `duplicateRelationRate`: 같은 스냅샷에서 같은 키가 두 번 이상 나온 관계 행 / 전체 관계 행.
    - `capDropRate`: 키별 최신 행 가운데 렌더 상한에서 잘린 행 / 키별 최신 행.

    `with_rows` 면 항목마다 기대 사실과, 그 키의 행·키만 빼고 맞는 행만 붙인다(문안을 고칠 때 보는 개발 보기 — 다른 행은 내지
    않는다)."""
    visible = [
        r
        for r in rows
        if checkpoint is None or r.get("available_from_turn") is None or int(r["available_from_turn"]) <= checkpoint + 1
    ]
    targets = [
        e
        for e in items
        if e.get("expected_fact")
        and (checkpoint is None or checkpoint in (e.get("probeCheckpoints") or {}).get("offline", []))
    ]
    kept, dropped, _ = render(visible, max_chars=max_chars)
    latest = {row_key(r): r for r in kept + dropped}
    kept_keys = {row_key(r) for r in kept}
    dropped_keys = {row_key(r) for r in dropped}
    per_item = []
    for entry in targets:
        key = expected_key(entry["expected_fact"])
        resolved = latest.get(key)
        in_read = resolved is not None and row_matches(resolved, entry)
        # 키 이름을 묻지 않는 읽기: 키만 빼고 맞는 행이 있고, 그 행의 키에서 키별 최신 행도 키만 빼고 맞는가.
        read_keys = {
            row_key(r)
            for r in visible
            if row_matches(r, entry, check_key=False) and row_matches(latest[row_key(r)], entry, check_key=False)
        }
        near_keys = {row_key(r) for r in visible if near_matches(r, entry) and near_matches(latest[row_key(r)], entry)}
        if entry["expected_fact"].get("kind") == "relation":
            near_keys &= {key}
        per_item.append(
            {
                "item": entry["id"],
                "category": entry.get("category"),
                "split": entry.get("split"),
                "key": key,
                "preserved": any(row_matches(r, entry) for r in visible),
                "preservedInRead": in_read,
                "droppedByCap": in_read and key in dropped_keys,
                "keyFound": resolved is not None,
                "matchedIgnoringKey": any(row_matches(r, entry, check_key=False) for r in visible),
                "readIgnoringKey": bool(read_keys),
                "droppedByCapIgnoringKey": bool(read_keys) and not (read_keys & kept_keys),
                "nearInRead": bool(near_keys),
                "nearDroppedByCap": bool(near_keys) and not (near_keys & kept_keys),
            }
        )
        if with_rows:
            shown = ("kind", "subject", "object", "attribute", "value", "truth_status", "asserted_by", "speaker",
                     "known_by", "importance", "snapshot_id", "start_turn", "end_turn")  # fmt: skip
            per_item[-1]["expected_fact"] = entry["expected_fact"]
            per_item[-1]["keyRows"] = [
                {**{f: r.get(f) for f in shown}, "matches": row_matches(r, entry)} for r in visible if row_key(r) == key
            ]
            per_item[-1]["matchedIgnoringKeyRows"] = [
                {f: r.get(f) for f in shown}
                for r in visible
                if row_key(r) != key and row_matches(r, entry, check_key=False)
            ]
            # 값만 맞고 진실 상태·아는 사람이 갈린 행 — 값은 다른 내용이 섞였을 수 있어 내지 않고 칸만 낸다.
            per_item[-1]["valueOnlyRows"] = [
                {f: r.get(f) for f in shown if f != "value"}
                for r in visible
                if value_matches(r.get("value"), entry) and not row_matches(r, entry, check_key=False)
            ]

    def summary(members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        read = [m for m in members if m["preservedInRead"]]
        read_ik = [m for m in members if m["readIgnoringKey"]]
        near = [m for m in members if m["nearInRead"]]
        return {
            "preserved": _rate(sum(1 for m in members if m["preserved"]), len(members)),
            "preservedInRead": _rate(len(read), len(members)),
            "droppedByCap": _rate(sum(1 for m in read if m["droppedByCap"]), len(read)),
            "keyFound": _rate(sum(1 for m in members if m["keyFound"]), len(members)),
            "matchedIgnoringKey": _rate(sum(1 for m in members if m["matchedIgnoringKey"]), len(members)),
            "readIgnoringKey": _rate(len(read_ik), len(members)),
            "droppedByCapIgnoringKey": _rate(sum(1 for m in read_ik if m["droppedByCapIgnoringKey"]), len(read_ik)),
            "nearInRead": _rate(len(near), len(members)),
            "nearDroppedByCap": _rate(sum(1 for m in near if m["nearDroppedByCap"]), len(near)),
        }

    by_category: dict[str, list[Mapping[str, Any]]] = {}
    for m in per_item:
        by_category.setdefault(str(m["category"]), []).append(m)
    seen_in_snapshot: dict[tuple[str, str], int] = {}
    for r in visible:
        pair = (str(r.get("snapshot_id")), row_key(r))
        seen_in_snapshot[pair] = seen_in_snapshot.get(pair, 0) + 1
    duplicates = sum(1 for r in visible if seen_in_snapshot[(str(r.get("snapshot_id")), row_key(r))] > 1)
    relations = [r for r in visible if r.get("kind") == "relation"]
    duplicate_relations = sum(1 for r in relations if seen_in_snapshot[(str(r.get("snapshot_id")), row_key(r))] > 1)
    restated = 0
    earlier: dict[tuple[str, str, str], set[str]] = {}
    for r in visible:
        sig = (row_key(r), normalize_part(r.get("value")), str(r.get("truth_status")))
        snapshots = earlier.setdefault(sig, set())
        if snapshots - {str(r.get("snapshot_id"))}:
            restated += 1
        snapshots.add(str(r.get("snapshot_id")))
    n_rows = len(visible)
    n_latest = len(kept) + len(dropped)
    return {
        "checkpoint": checkpoint,
        "maxChars": max_chars,
        "rows": n_rows,
        "latestRows": n_latest,
        "duplicateKeyRate": _rate(duplicates, n_rows),
        "duplicateRelationRate": _rate(duplicate_relations, len(relations)),
        "restatedRate": _rate(restated, n_rows),
        "capDropRate": _rate(len(dropped), n_latest),
        "overall": summary(per_item),
        "byCategory": {name: summary(members) for name, members in sorted(by_category.items())},
        "items": per_item,
    }


# ---------------------------------------------------------------- 섹션 적중(선택 방식 비교)

# 격자 목적함수의 주 지표 범주(최종 판정의 주 지표 범주와 같다).
SECTION_PRIMARY_CATEGORIES = ("relation", "secret", "false_premise", "correction")
ABSTAIN_CATEGORY = "abstain"


def _near_in(rows: Sequence[Mapping[str, Any]], entry: Mapping[str, Any]) -> bool:
    """`rows` 에 근사 일치하는 행이 있는가 — 관계는 기대 키(주어 → 대상)의 행만 센다(`fact_metrics` 의 `nearInRead` 와 같은 꼴)."""
    expected = entry.get("expected_fact") or {}
    key = expected_key(expected)
    relation = expected.get("kind") == "relation"
    return any(near_matches(r, entry) and (not relation or row_key(r) == key) for r in rows)


def section_metrics(
    items: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    checkpoint: int,
    names: Sequence[str] = (),
    max_chars: int = RENDER_MAX_CHARS,
    **selection: Any,
) -> dict[str, Any]:
    """선택 방식 하나의 섹션 적중(체크포인트 하나). 질의 = 항목 질문(두 턴 프로브는 질문 턴이 둘째라 `question` 그대로).

    - 기대 사실 항목(그때 심기가 모두 접힌 것): `hit` = 섹션에 근사 일치(`near_matches`) 행이 실렸다. `reachable` = 키별 최신
      행 어딘가에 있다(상한이 없으면 실렸을 것 — 적중의 천장). `viaRelevant` = 맞힌 행이 관련 쪽으로 실렸다.
    - 기권 항목(묻는 체크포인트와 상관없이 이 체크포인트에서): `misinjected` = 관련 쪽이 한 줄이라도 실었다(기권 질문엔 실을
      사실이 없다)."""
    visible = [
        r for r in rows if r.get("available_from_turn") is None or int(r["available_from_turn"]) <= checkpoint + 1
    ]
    latest = latest_by_key(visible)
    per_item: list[dict[str, Any]] = []
    for entry in items:
        category = str(entry.get("category"))
        is_abstain = category == ABSTAIN_CATEGORY
        if not is_abstain and not (
            entry.get("expected_fact") and checkpoint in (entry.get("probeCheckpoints") or {}).get("offline", [])
        ):
            continue
        section = select_section(
            visible,
            max_chars=max_chars,
            query=str(entry.get("question") or ""),
            names=names,
            current_turn=checkpoint,
            **selection,
        )
        result: dict[str, Any] = {"item": entry["id"], "category": category, "relevantLines": len(section.relevant)}
        if is_abstain:
            result["misinjected"] = bool(section.relevant)
        else:
            result["hit"] = _near_in(section.kept, entry)
            result["reachable"] = _near_in(latest, entry)
            result["viaRelevant"] = result["hit"] and not _near_in(
                [r for r in section.kept if all(r is not x for x in section.relevant)], entry
            )
        per_item.append(result)
    by_category: dict[str, dict[str, int]] = {}
    for m in per_item:
        c = by_category.setdefault(
            m["category"], {"n": 0, "hit": 0, "reachable": 0, "viaRelevant": 0, "misinjected": 0}
        )
        c["n"] += 1
        for field in ("hit", "reachable", "viaRelevant", "misinjected"):
            c[field] += int(bool(m.get(field)))
    return {"checkpoint": checkpoint, "byCategory": dict(sorted(by_category.items())), "items": per_item}


# 고르는 순서의 기본값(목적함수 파일 꼴과 같다): 주 지표 4범주(관계·비밀·거짓 전제·정정) 섹션 적중 합(모든 체크포인트) 큰 쪽 →
# 비밀 적중 큰 쪽 → 기권 오주입 작은 쪽 → 상시 비율 큰 쪽 → 관련 임계 큰 쪽(덜 싣는 쪽). 격자 명령은 커밋된 목적함수 파일의 순서를 쓴다.
DEFAULT_SECTION_ORDER: tuple[tuple[str, int], ...] = (
    ("primaryHits", 1),
    ("secretHits", 1),
    ("abstainMisinjected", -1),
    ("constant_ratio", 1),
    ("tau", 1),
)


def section_grid(
    items: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    checkpoints: Sequence[int],
    ratios: Sequence[float],
    taus: Sequence[float],
    names: Sequence[str] = (),
    max_chars: int = RENDER_MAX_CHARS,
    order: Sequence[tuple[str, int]] = DEFAULT_SECTION_ORDER,
) -> dict[str, Any]:
    """`constant` 기준선과 `mixed` 격자(상시 비율 × 관련 임계)를 같은 항목·행으로 재고 `order`(기준, 큰 쪽 1 · 작은 쪽 -1)로
    하나를 고른다."""
    configs: list[dict[str, Any]] = [{"mode": "constant"}] + [
        {"mode": "mixed", "constant_ratio": r, "tau": t} for r in ratios for t in taus
    ]
    results: list[dict[str, Any]] = []
    for config in configs:
        per_cp = [
            section_metrics(items, rows, checkpoint=cp, names=names, max_chars=max_chars, **config)
            for cp in checkpoints
        ]
        totals: dict[str, dict[str, int]] = {}
        for res in per_cp:
            for category, c in res["byCategory"].items():
                t = totals.setdefault(category, {k: 0 for k in c})
                for k, v in c.items():
                    t[k] += v
        primary = sum(totals.get(c, {}).get("hit", 0) for c in SECTION_PRIMARY_CATEGORIES)
        results.append(
            {
                "config": config,
                "primaryHits": primary,
                "secretHits": totals.get("secret", {}).get("hit", 0),
                "abstainMisinjected": totals.get(ABSTAIN_CATEGORY, {}).get("misinjected", 0),
                "totals": dict(sorted(totals.items())),
                "perCheckpoint": [{"checkpoint": r["checkpoint"], "byCategory": r["byCategory"]} for r in per_cp],
                "items": {str(r["checkpoint"]): r["items"] for r in per_cp},
            }
        )
    mixed = [r for r in results if r["config"]["mode"] == "mixed"]

    def rank(r: Mapping[str, Any]) -> tuple[float, ...]:
        return tuple(sign * float(r[key] if key in r else r["config"][key]) for key, sign in order)

    best = max(mixed, key=rank, default=None)
    return {"order": [list(o) for o in order], "checkpoints": list(checkpoints), "maxChars": max_chars,
            "names": list(names), "results": results, "chosen": best["config"] if best else None}  # fmt: skip
