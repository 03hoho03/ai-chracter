"""실제로 돌았나 — 판정·집계 입구의 단언.

스위치를 켠 갈래라도 그 장치가 측정 중에 한 번도 일하지 않았으면(질의 임베딩이 계속 실패해 명사 단독으로 회상했다, 아는 사람
가림이 한 번도 걸리지 않았다, 따옴표 안 이름 재분류가 한 번도 일어나지 않았다) 그 갈래의 결과는 스위치의 효과가 아니다. 그래서
집계 전에 갈래별로 아래 수를 보고 문턱에 못 미치면 집계를 거부한다.

- 질의 임베딩 성공 비율: 프로브 행의 `queryEmbeddings`(턴 기록의 질의 임베딩 호출)에서 `outcome == "ok"` 수 / 받아들인 행의 턴
  수. 호출 기록이 없는 턴(멈춤 키로 건너뜀 등)도 분모에 든다.
- 가림 합계·재분류 합계: `filter-recompute` 출력 행의 `hiddenEpisodes`·`reclassified` 합(서버 함수로 다시 센 값).
- 사실 섹션 실림 턴 수: 사실 주입을 켠 갈래의 프로브 행 `memoryFacts`(턴 기록 `chat_turns.memory_facts`, 그 턴 프롬프트가 실은
  사실 행)가 비지 않은 턴 수. 사실 주입 스위치를 켰어도 고를 행이 없거나 섹션이 늘 비었으면 그 갈래는 사실 주입을 잰 것이 아니다.
  이 문턱만은 상수가 아니라 실행 인자로 받는다 — 실릴 수 있는 턴 수가 측정마다 대본·체크포인트에 달려 봉인 문서가 정하고, 기본값을
  두면 문서가 정하지 않은 값으로 조용히 통과한다.

문턱이 없는 갈래(꺼진 갈래, 이전 런의 갈래)는 보지 않는다."""

from collections.abc import Collection, Iterable, Mapping
from fractions import Fraction
from typing import Any

from api.chat.memory_vector import QUERY_EMBEDDING_CALL_SITE

# 문턱은 판정 결과를 보기 전에 고정한 값이다 — 결과를 본 뒤 맞춰 고치면 단언이 아무것도 지키지 못한다. 비율은 부동소수 경계
# 오차 없이 견주려고 분수로 둔다(정확히 문턱이면 통과).
EMBED_OK_MIN = Fraction(95, 100)
HIDDEN_MIN_TOTAL = 1
RECLASSIFIED_MIN_TOTAL = 1
# 문턱을 거는 갈래 — 임베딩 회상을 켠 갈래, 지식 범위 필터와 회상을 함께 켠 갈래. 재분류는 서버가 장면 인물을 세는 갈래(회상이나
# 사실 주입이 켜진 필터 갈래)만 — 요약 표기만 켠 필터 갈래(b1-A0M)는 회상·사실 주입이 꺼져 서버가 장면 인물을 세지 않는다.
EMBED_ARMS = ("b1-B1E", "b1-B2")
HIDDEN_ARMS = ("b1-B1", "b1-B1E", "b1-B2")
RECLASSIFIED_ARMS = ("b1-B1", "b1-B1E", "b1-B2")
# 사실 주입을 켠 갈래 — 사실 섹션 실림 턴 수 문턱을 건다.
FACTS_ARMS = ("b1-B2",)  # cite-ok: 하네스 갈래 이름 문자열이다(결정 번호 아님)
GATED_ARMS = tuple(sorted({*EMBED_ARMS, *HIDDEN_ARMS, *RECLASSIFIED_ARMS, *FACTS_ARMS}))
# 문턱을 실행 인자로 주는 인자 이름 — 거부 문구가 이 이름을 가리킨다.
FACTS_MIN_FLAG = "--ran-facts-min"

ACCEPTED = ("accept", "count_wrong")
# 덮지 못한 행을 알릴 때 보여 줄 키 수.
SHOWN_KEYS = 5


def query_embedding_ok(probe_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """갈래별 질의 임베딩 성공 수·턴 수·비율(턴이 없으면 None). 받아들인 행(집계에 들어가는 행)만 센다."""
    totals: dict[str, list[int]] = {}
    for row in probe_rows:
        if row.get("status") not in ACCEPTED or not row.get("turns"):
            continue
        counts = totals.setdefault(str(row["arm"]), [0, 0])
        counts[0] += sum(
            1
            for call in row.get("queryEmbeddings") or ()
            if call.get("callSite") == QUERY_EMBEDDING_CALL_SITE and call.get("outcome") == "ok"
        )
        counts[1] += len(row["turns"])
    return {
        arm: {"ok": ok, "turns": turns, "ratio": ok / turns if turns else None}
        for arm, (ok, turns) in sorted(totals.items())
    }


def facts_loaded_turns(probe_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """갈래별 사실 섹션이 실린 턴 수(`memoryFacts` 가운데 빈 목록이 아닌 것)와 턴 수. 받아들인 행만 센다."""
    totals: dict[str, dict[str, int]] = {}
    for row in probe_rows:
        if row.get("status") not in ACCEPTED or not row.get("turns"):
            continue
        counts = totals.setdefault(str(row["arm"]), {"loaded": 0, "turns": 0})
        counts["loaded"] += sum(1 for facts in row.get("memoryFacts") or () if facts)
        counts["turns"] += len(row["turns"])
    return dict(sorted(totals.items()))


def recompute_totals(recompute_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """갈래별 가림·재분류 합계와 행 수."""
    totals: dict[str, dict[str, int]] = {}
    for row in recompute_rows:
        counts = totals.setdefault(str(row["arm"]), {"rows": 0, "hiddenEpisodes": 0, "reclassified": 0})
        counts["rows"] += 1
        counts["hiddenEpisodes"] += int(row.get("hiddenEpisodes") or 0)
        counts["reclassified"] += int(row.get("reclassified") or 0)
    return totals


def needs_inputs(arms: Collection[str]) -> bool:
    return any(arm in GATED_ARMS for arm in arms)


def ran_failures(
    arms: Collection[str],
    *,
    probe_rows: Iterable[Mapping[str, Any]],
    recompute_rows: Iterable[Mapping[str, Any]],
    facts_loaded_min: int | None,
) -> list[str]:
    """문턱에 못 미친 (갈래, 지표, 값) 줄. 빈 목록이면 통과. 사실 주입 갈래가 있는데 `facts_loaded_min` 이 없으면 거부한다."""
    probe_rows = list(probe_rows)
    embedding = query_embedding_ok(probe_rows)
    recomputed = recompute_totals(recompute_rows)
    loaded = facts_loaded_turns(probe_rows)
    failures: list[str] = []
    for arm in sorted(arms):
        if arm in FACTS_ARMS:
            if facts_loaded_min is None:
                raise SystemExit(f"사실 주입 갈래 {arm} 를 집계하려면 사실 섹션 실림 턴 수 문턱({FACTS_MIN_FLAG})을 준다")
            count = (loaded.get(arm) or {"loaded": 0})["loaded"]
            if count < facts_loaded_min:
                failures.append(f"{arm} factsLoadedTurns={count} (문턱 {facts_loaded_min})")
        if arm in EMBED_ARMS:
            stats = embedding.get(arm) or {"ok": 0, "turns": 0}
            ok, turns = int(stats["ok"]), int(stats["turns"])
            if not turns or Fraction(ok, turns) < EMBED_OK_MIN:
                value = f"{ok / turns:.4f}" if turns else "없음"
                failures.append(f"{arm} queryEmbeddingOk={value} ({ok}/{turns}, 문턱 {float(EMBED_OK_MIN)})")
        totals = recomputed.get(arm, {"hiddenEpisodes": 0, "reclassified": 0})
        for metric, gated, minimum in (
            ("hiddenEpisodes", HIDDEN_ARMS, HIDDEN_MIN_TOTAL),
            ("reclassified", RECLASSIFIED_ARMS, RECLASSIFIED_MIN_TOTAL),
        ):
            if arm in gated and totals[metric] < minimum:
                failures.append(f"{arm} {metric}={totals[metric]} (문턱 {minimum})")
    return failures


def require_ran(
    arms: Collection[str],
    *,
    probe_rows: Iterable[Mapping[str, Any]],
    recompute_rows: Iterable[Mapping[str, Any]],
    facts_loaded_min: int | None,
) -> None:
    failures = ran_failures(
        arms, probe_rows=list(probe_rows), recompute_rows=list(recompute_rows), facts_loaded_min=facts_loaded_min
    )
    if failures:
        raise SystemExit("집계 거부 — 켠 장치가 측정 중에 일하지 않은 갈래가 있다: " + "; ".join(failures))


def _key(row: Mapping[str, Any]) -> str:
    if "item" not in row or "checkpoint" not in row:
        raise SystemExit(f"집계 행에 문항·체크포인트 칸이 없다(갈래 {row.get('arm')}) — 단언 입력과 맞춰 볼 수 없다")
    return f"{row['arm']}:{row['item']}:{int(row['checkpoint'])}"


def require_covered(
    rows: Iterable[Mapping[str, Any]],
    *,
    probe_rows: Iterable[Mapping[str, Any]],
    recompute_rows: Iterable[Mapping[str, Any]],
) -> None:
    """단언 입력이 집계할 행을 덮는지 — 문턱이 걸린 갈래의 집계 행 (갈래, 문항, 체크포인트)가 임베딩 갈래면 프로브 결과에,
    가림·재분류 갈래면 필터 재계산 출력에 모두 있어야 한다. 갈래 합계만 보면 일부 측정분의 입력으로 전체 집계를 통과시킬 수
    있다. 재계산은 받아들인 행만 다루므로 상태가 받아들임이 아닌 집계 행(채점하지 않은 행)은 재계산 쪽에서 묻지 않는다."""
    probe_keys = {_key(row) for row in probe_rows}
    recompute_keys = {_key(row) for row in recompute_rows}
    missing: dict[str, list[str]] = {"--ran-probes": [], "--ran-recompute": []}
    for row in rows:
        arm = str(row.get("arm"))
        if arm not in GATED_ARMS:
            continue
        key = _key(row)
        if arm in EMBED_ARMS and key not in probe_keys:
            missing["--ran-probes"].append(key)
        accepted = row.get("status", ACCEPTED[0]) in ACCEPTED and row.get("scored", True) is not False
        if accepted and arm in {*HIDDEN_ARMS, *RECLASSIFIED_ARMS} and key not in recompute_keys:
            missing["--ran-recompute"].append(key)
    problems = [
        f"{flag} 에 없는 집계 행 {len(set(keys))}개(처음 {sorted(set(keys))[:SHOWN_KEYS]})"
        for flag, keys in missing.items()
        if keys
    ]
    if problems:
        raise SystemExit("집계 거부 — 단언 입력이 집계 행을 덮지 않는다: " + "; ".join(problems))
