"""턴 기록의 판정 이벤트 로그(`chat_turns.stat_events`) 분포 — 읽기 전용 SELECT 하나로 집계만 낸다.

운영 DB 에서도 같은 SQL 을 psql 로 돌릴 수 있게 집계는 전부 SQL 안에서 한다(`stat_events_sql`). 결과 행은
`('p5d', 지표, 턴 종류, 칸, 값)` 이고 턴 종류는 `send`·`edit`·`regenerate` 와 합계 `all` 이다. 방·메시지·규칙·스탯 id 와 글은
어느 행에도 없다.

원소 꼴은 `chat/stats.py` 의 `apply_rule_judgment_with_events` 가 정한다.
- 판정 원소 `{statEntityId, firedRuleIds:[{entityId,id}], appliedRuleId:{entityId,id}, delta, clamped}` — 발동 규칙이 있는 판정
  스탯마다 하나.
- 카운터 원소 `{statEntityId, counter: true, delta, clamped}` — 카운터 스탯마다 매 판정 하나.
- 모르는 id 원소 `{unknownRuleIdCount}` — 맨 끝에 하나. 그 밖의 꼴은 `other` 로 센다(꼴이 바뀐 것을 놓치지 않게).

행마다의 일치 불변식은 "스탯마다 `v != start` ⇔ `stat_changes` 에 키가 있고 그 값이 `[start, v]`" 이다(`v` 는 원소가 있으면
`clamp(start + delta)`, 없으면 `start`). 기록만으로는 최소·최대를 모르므로 이렇게 나눠 센다.
- 잘리지 않은 원소: 키가 있으면 `뒤 - 앞 = delta`(아니면 `deltaMismatch`), 키가 없으면 `delta = 0`(아니면 `missingChange`).
- 잘린 원소: 키가 없으면 이미 끝 값이라 그대로인 것이라 맞다. 키가 있으면 `delta` 와 같은 방향으로 `|delta|` 보다 덜 움직여야 한다
  (아니면 `clampMismatch`).
- 키가 있는데 그 스탯의 판정·카운터 원소가 없으면 `changeWithoutEvent`.
- 키의 앞 값이 `null`(반영 전 값이 없던 스탯 — 시작 값이 작가의 초기값이라 기록에 없다)이면 값 비교를 하지 않고 `startUnknown` 으로
  센다. 키 값이 두 숫자의 배열이 아니거나 원소의 `delta`·`clamped` 꼴이 틀리면 `malformed`.
검사 대상은 원소가 하나라도 있는 행이다. 원소가 없는데 키가 있는 행(`rowsNoEventsWithChanges`)은 스위치를 켜기 전 행이거나 그런
행을 재판정 없이 물려받은 재생성이라 기록이 없는 것이지 어긋난 것이 아니어서 따로 센다."""

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import asyncpg
from sqlalchemy.engine import make_url

from replay.local_db import ensure_local_database

TURN_KINDS = ("send", "edit", "regenerate")
ELEMENT_KINDS = ("judged", "counter", "unknown", "other")
VIOLATIONS = ("deltaMismatch", "clampMismatch", "missingChange", "changeWithoutEvent", "malformed")
# 숫자 비교 허용 오차 — 값과 폭이 소수인 작품에서 jsonb 숫자 뺄셈의 끝자리 차이를 위반으로 세지 않게.
_EPSILON = "0.000000001"

_SQL = """
WITH t AS (
  SELECT row_number() OVER () AS rid, kind,
         CASE WHEN jsonb_typeof(stat_events) = 'array' THEN stat_events ELSE '[]'::jsonb END AS ev,
         CASE WHEN jsonb_typeof(stat_changes) = 'object' THEN stat_changes ELSE '{}'::jsonb END AS ch
    FROM chat_turns
   WHERE created_at >= timestamptz '__SINCE__'__UNTIL__
),
el AS (
  SELECT t.rid, t.kind, x.e,
         CASE WHEN jsonb_typeof(x.e) <> 'object' THEN 'other'
              WHEN x.e ? 'appliedRuleId' THEN 'judged'
              WHEN x.e ? 'counter' THEN 'counter'
              WHEN x.e ? 'unknownRuleIdCount' THEN 'unknown'
              ELSE 'other' END AS ek
    FROM t, jsonb_array_elements(t.ev) AS x(e)
),
st AS (
  SELECT el.rid, el.kind, el.ek, el.e,
         el.e->>'statEntityId' AS sid,
         jsonb_typeof(el.e->'delta') = 'number' AND jsonb_typeof(el.e->'clamped') = 'boolean'
           AND jsonb_typeof(el.e->'statEntityId') = 'string' AS ok,
         CASE WHEN jsonb_typeof(el.e->'delta') = 'number' THEN (el.e->>'delta')::numeric END AS delta,
         CASE WHEN jsonb_typeof(el.e->'clamped') = 'boolean' THEN (el.e->>'clamped')::boolean END AS clamped,
         t.ch -> (el.e->>'statEntityId') AS cv
    FROM el JOIN t ON t.rid = el.rid
   WHERE el.ek IN ('judged', 'counter')
),
sv AS (
  SELECT st.*,
         CASE
           WHEN NOT st.ok THEN 'malformed'
           WHEN st.cv IS NULL THEN
             CASE WHEN NOT st.clamped AND st.delta <> 0 THEN 'missingChange' ELSE 'ok' END
           WHEN jsonb_typeof(st.cv) <> 'array' OR jsonb_array_length(st.cv) <> 2
                OR jsonb_typeof(st.cv->1) <> 'number' OR jsonb_typeof(st.cv->0) NOT IN ('number', 'null') THEN 'malformed'
           WHEN jsonb_typeof(st.cv->0) = 'null' THEN 'startUnknown'
           WHEN NOT st.clamped THEN
             CASE WHEN abs((st.cv->>1)::numeric - (st.cv->>0)::numeric - st.delta) <= __EPS__ THEN 'ok'
                  ELSE 'deltaMismatch' END
           ELSE
             CASE WHEN sign((st.cv->>1)::numeric - (st.cv->>0)::numeric) = sign(st.delta)
                       AND abs((st.cv->>1)::numeric - (st.cv->>0)::numeric) < abs(st.delta) THEN 'ok'
                  ELSE 'clampMismatch' END
         END AS verdict
    FROM st
),
orphan AS (
  SELECT t.rid, t.kind
    FROM t, jsonb_object_keys(t.ch) AS k(key)
   WHERE jsonb_array_length(t.ev) > 0
     AND NOT EXISTS (SELECT 1 FROM st WHERE st.rid = t.rid AND st.sid = k.key)
),
per_row AS (
  SELECT t.rid, t.kind,
         jsonb_array_length(t.ev) > 0 AS has_ev,
         t.ch <> '{}'::jsonb AS has_ch,
         coalesce((SELECT sum(jsonb_array_length(el.e->'firedRuleIds')) FROM el
                    WHERE el.rid = t.rid AND el.ek = 'judged' AND jsonb_typeof(el.e->'firedRuleIds') = 'array'), 0) AS fired,
         EXISTS (SELECT 1 FROM el WHERE el.rid = t.rid AND el.ek = 'judged') AS has_judged,
         NOT EXISTS (SELECT 1 FROM el WHERE el.rid = t.rid AND el.ek = 'judged'
                      AND NOT coalesce(el.e->'firedRuleIds' @> jsonb_build_array(el.e->'appliedRuleId'), false)) AS all_applied,
         EXISTS (SELECT 1 FROM sv WHERE sv.rid = t.rid AND sv.verdict NOT IN ('ok', 'startUnknown'))
           OR EXISTS (SELECT 1 FROM orphan o WHERE o.rid = t.rid) AS violating
    FROM t
)
SELECT 'p5d', 'rows', coalesce(kind, 'all'), 'turns', count(*) FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'rows', coalesce(kind, 'all'), 'rowsWithEvents', count(*) FILTER (WHERE has_ev)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'rows', coalesce(kind, 'all'), 'rowsWithChanges', count(*) FILTER (WHERE has_ch)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'rows', coalesce(kind, 'all'), 'rowsNoEventsWithChanges', count(*) FILTER (WHERE has_ch AND NOT has_ev)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'elements', coalesce(kind, 'all'), ek, count(*) FROM el GROUP BY GROUPING SETS ((kind, ek), (ek))
UNION ALL
SELECT 'p5d', 'unknownRuleIds', coalesce(kind, 'all'), 'sum', sum((e->>'unknownRuleIdCount')::numeric)
  FROM el WHERE ek = 'unknown' AND jsonb_typeof(e->'unknownRuleIdCount') = 'number'
 GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'firedPerTurn', coalesce(kind, 'all'), fired::text, count(*)
  FROM per_row WHERE has_ev GROUP BY GROUPING SETS ((kind, fired), (fired))
UNION ALL
SELECT 'p5d', 'firedPerElement', coalesce(kind, 'all'), jsonb_array_length(e->'firedRuleIds')::text, count(*)
  FROM el WHERE ek = 'judged' AND jsonb_typeof(e->'firedRuleIds') = 'array'
 GROUP BY GROUPING SETS ((kind, jsonb_array_length(e->'firedRuleIds')), (jsonb_array_length(e->'firedRuleIds')))
UNION ALL
SELECT 'p5d', 'clamped', coalesce(kind, 'all'), ek, count(*) FILTER (WHERE clamped)
  FROM st GROUP BY GROUPING SETS ((kind, ek), (ek))
UNION ALL
SELECT 'p5d', 'appliedInFired', coalesce(kind, 'all'), 'turnsWithJudged', count(*) FILTER (WHERE has_judged)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'appliedInFired', coalesce(kind, 'all'), 'turnsAllApplied', count(*) FILTER (WHERE has_judged AND all_applied)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'appliedInFired', coalesce(kind, 'all'), 'elements',
       count(*) FILTER (WHERE coalesce(e->'firedRuleIds' @> jsonb_build_array(e->'appliedRuleId'), false))
  FROM el WHERE ek = 'judged' GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'invariant', coalesce(kind, 'all'), 'rowsChecked', count(*) FILTER (WHERE has_ev)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'invariant', coalesce(kind, 'all'), 'rowsViolating', count(*) FILTER (WHERE has_ev AND violating)
  FROM per_row GROUP BY GROUPING SETS ((kind), ())
UNION ALL
SELECT 'p5d', 'invariant', coalesce(kind, 'all'), verdict, count(*)
  FROM sv WHERE verdict <> 'ok' GROUP BY GROUPING SETS ((kind, verdict), (verdict))
UNION ALL
SELECT 'p5d', 'invariant', coalesce(kind, 'all'), 'changeWithoutEvent', count(*)
  FROM orphan GROUP BY GROUPING SETS ((kind), ())
ORDER BY 2, 3, 4;
"""


def _until_clause(since: datetime, until: datetime | None, column: str) -> str:
    for value in (since, until):
        if value is not None and value.tzinfo is None:
            raise SystemExit(f"시각에 시간대가 없다: {value.isoformat()}")
    return "" if until is None else f" AND {column} < timestamptz '{until.isoformat()}'"


def stat_events_sql(since: datetime, until: datetime | None) -> str:
    """기준 시각(포함)부터 끝 시각(제외, 없으면 끝없음)까지의 턴 기록을 집계하는 SELECT 하나. 시각은 시간대가 있어야 한다 —
    운영 psql 에 그대로 붙여 넣을 수 있게 리터럴로 싣는다(값은 `datetime` 의 ISO 꼴뿐이라 다른 글이 끼어들지 않는다)."""
    until_clause = _until_clause(since, until, "created_at")
    return (
        _SQL.replace("__SINCE__", since.isoformat()).replace("__UNTIL__", until_clause).replace("__EPS__", _EPSILON)
    ).strip()


def _number(value: Any) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def _empty_kind() -> dict[str, Any]:
    return {
        "turns": 0,
        "rowsWithEvents": 0,
        "rowsWithChanges": 0,
        "rowsNoEventsWithChanges": 0,
        "elements": dict.fromkeys(ELEMENT_KINDS, 0),
        "unknownRuleIds": 0,
        "firedPerTurn": {},
        "firedPerElement": {},
        "clamped": {"judged": 0, "counter": 0},
        "appliedInFired": {"turnsWithJudged": 0, "turnsAllApplied": 0, "elements": 0},
        "invariant": {"rowsChecked": 0, "rowsViolating": 0, **dict.fromkeys(VIOLATIONS, 0), "startUnknown": 0},
    }


def summarize_rows(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    """SQL 결과 행을 턴 종류 → 지표 사전으로 접고 비율(잘림 비율·적용 규칙 몫)을 더한다."""
    report = {kind: _empty_kind() for kind in ("all", *TURN_KINDS)}
    for _tag, metric, kind, bucket, value in rows:
        target = report.setdefault(kind, _empty_kind())
        number = _number(value) if value is not None else 0
        if metric == "rows":
            target[bucket] = number
        elif metric == "unknownRuleIds":
            target["unknownRuleIds"] = number
        elif metric in ("firedPerTurn", "firedPerElement"):
            target[metric][str(bucket)] = number
        else:
            target[metric][bucket] = number
    for target in report.values():
        target["firedPerTurn"] = dict(sorted(target["firedPerTurn"].items(), key=lambda item: int(item[0])))
        target["firedPerElement"] = dict(sorted(target["firedPerElement"].items(), key=lambda item: int(item[0])))
        elements = target["elements"]
        target["clampedRate"] = {
            kind: (target["clamped"][kind] / elements[kind] if elements[kind] else None)
            for kind in ("judged", "counter")
        }
        applied = target["appliedInFired"]
        applied["turnShare"] = (
            applied["turnsAllApplied"] / applied["turnsWithJudged"] if applied["turnsWithJudged"] else None
        )
    return report


async def stat_event_distribution(connection: Any, *, since: datetime, until: datetime | None = None) -> dict[str, Any]:
    """연결(asyncpg) 하나에서 집계 SQL 을 돌려 턴 종류별 분포를 돌려준다. 연결을 읽기 전용으로 여는 것은 부르는 쪽 몫이다
    (`read_only_connection`)."""
    rows = await connection.fetch(stat_events_sql(since, until))
    return summarize_rows([tuple(row) for row in rows])


# ---------------------------------------------------------------- 같은 규칙의 연속 적용

# 살아 있는 턴만 남기는 조건. 테스트가 이 조건을 빼 보고 기대값이 깨지는지(죽은 턴을 가려내는지) 확인하려고 이름을 둔다.
LIVE_FILTER = "WHERE t.live"
REPEAT_DIRECTIONS = ("pos", "neg", "zero", "mixed")

_REPEAT_SQL = """
WITH t AS (
  SELECT ct.chat_room_id AS room, ct.turn_number AS tn, ct.created_at AS made_at,
         CASE WHEN jsonb_typeof(ct.stat_events) = 'array' THEN ct.stat_events ELSE '[]'::jsonb END AS ev,
         EXISTS (SELECT 1 FROM chat_messages m WHERE m.id = ct.assistant_message_id) AS live
    FROM chat_turns ct
   WHERE ct.created_at >= timestamptz '__SINCE__'__UNTIL__
),
live AS (
  SELECT t.room, t.tn, t.made_at, t.ev FROM t __LIVE__
),
j AS (
  SELECT l.room, l.tn, l.made_at, x.e->>'statEntityId' AS sid,
         x.e->'appliedRuleId'->>'entityId' AS rule,
         sign(CASE WHEN jsonb_typeof(x.e->'delta') = 'number' THEN (x.e->>'delta')::numeric END)::int AS sgn,
         CASE WHEN jsonb_typeof(x.e->'clamped') = 'boolean' THEN (x.e->>'clamped')::boolean END AS clamped
    FROM live l, jsonb_array_elements(l.ev) AS x(e)
   WHERE jsonb_typeof(x.e) = 'object'
     AND jsonb_typeof(x.e->'statEntityId') = 'string'
     AND jsonb_typeof(x.e->'appliedRuleId'->'entityId') = 'string'
     AND jsonb_typeof(x.e->'delta') = 'number'
     AND jsonb_typeof(x.e->'clamped') = 'boolean'
),
s AS (
  SELECT j.*, lag(j.rule) OVER w AS prev_rule, lag(j.tn) OVER w AS prev_tn
    FROM j WINDOW w AS (PARTITION BY j.room, j.sid ORDER BY j.tn, j.made_at)
),
g AS (
  SELECT s.*,
         sum(CASE WHEN s.prev_rule = s.rule AND s.tn = s.prev_tn + 1 THEN 0 ELSE 1 END)
           OVER (PARTITION BY s.room, s.sid ORDER BY s.tn, s.made_at ROWS UNBOUNDED PRECEDING) AS grp
    FROM s
),
runs AS (
  SELECT count(*) AS len, count(*) FILTER (WHERE clamped) AS clamped,
         CASE WHEN min(sgn) <> max(sgn) THEN 'mixed'
              WHEN min(sgn) = 1 THEN 'pos' WHEN min(sgn) = -1 THEN 'neg' ELSE 'zero' END AS dir
    FROM g GROUP BY room, sid, grp
)
SELECT 'rep', 'scope', 'all', 'liveTurns', count(*) FILTER (WHERE live) FROM t
UNION ALL
SELECT 'rep', 'scope', 'all', 'deadTurns', count(*) FILTER (WHERE NOT live) FROM t
UNION ALL
SELECT 'rep', 'scope', 'all', 'liveTurnsWithJudged', count(*) FROM (SELECT DISTINCT room, tn, made_at FROM j) AS jt
UNION ALL
SELECT 'rep', 'scope', 'all', 'rooms', count(DISTINCT room) FROM j
UNION ALL
SELECT 'rep', 'scope', 'all', 'roomStats', count(*) FROM (SELECT DISTINCT room, sid FROM j) AS js
UNION ALL
SELECT 'rep', 'runs', coalesce(dir, 'all'), len::text, count(*) FROM runs GROUP BY GROUPING SETS ((dir, len), (len))
UNION ALL
SELECT 'rep', 'runClamped', coalesce(dir, 'all'), len::text, sum(clamped) FROM runs
 GROUP BY GROUPING SETS ((dir, len), (len))
ORDER BY 2, 3, 4;
"""


def stat_repeat_sql(since: datetime, until: datetime | None) -> str:
    """같은 방·같은 스탯에서 같은 적용 규칙이 인접 턴에 이어진 길이의 분포를 집계하는 SELECT 하나. 시각 규칙과 리터럴 싣기는
    `stat_events_sql` 과 같다. 운영에서는 `BEGIN READ ONLY; … ROLLBACK;` 안에 그대로 넣는다.

    - 살아 있는 턴만 본다: 응답 메시지 행이 아직 있는 턴. 재생성·수정·메시지 삭제가 지운 응답의 기록은 그 자리를 대체한 턴과
      같은 턴 번호로 남아 있어, 넣으면 같은 턴이 둘이 되고 연속이 끊기거나 부풀려진다. 메시지 행은 있는지만 보고 글은 읽지 않는다.
    - 규칙은 `appliedRuleId.entityId` 로 가린다 — 작가가 규칙을 고쳐 판본(`id`)이 바뀌어도 같은 규칙이다.
    - 구간은 (방, 스탯)마다 턴 번호 순으로 늘어놓은 판정 원소에서, 바로 앞 원소와 규칙이 같고 턴 번호가 하나 차이일 때 이어진다.
      그 스탯이 판정되지 않은 턴(발동 규칙 없음)이 끼면 끊긴다. 카운터 원소와 꼴이 틀린 원소는 보지 않는다.
    - 구간의 방향은 폭의 부호(`pos`·`neg`·`zero`, 한 구간 안에서 갈리면 `mixed`)다.

    결과 행은 `('rep', 지표, 방향, 칸, 값)` 이고 방·스탯·규칙 id 는 집계 안에서만 쓴다."""
    until_clause = _until_clause(since, until, "ct.created_at")
    return (
        _REPEAT_SQL.replace("__SINCE__", since.isoformat())
        .replace("__UNTIL__", until_clause)
        .replace("__LIVE__", LIVE_FILTER)
    ).strip()


def _empty_direction() -> dict[str, Any]:
    return {"runs": {}, "runClamped": {}}


def summarize_repeat_rows(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    """반복 집계 행을 접는다. 방향마다(`all` 은 합계) 구간 길이 → 구간 수, 길이 → 잘린 원소 수에 더해 원소 수·잘림 비율과,
    길이 2 이상 구간(같은 규칙이 이어진 것)만의 구간 수·원소 수·잘림 비율·전체 원소 중 몫, 가장 긴 구간 길이를 낸다."""
    scope: dict[str, int | float] = {
        "liveTurns": 0,
        "deadTurns": 0,
        "liveTurnsWithJudged": 0,
        "rooms": 0,
        "roomStats": 0,
    }
    by_direction: dict[str, dict[str, Any]] = {"all": _empty_direction()}
    for _tag, metric, direction, bucket, value in rows:
        number = _number(value) if value is not None else 0
        if metric == "scope":
            scope[bucket] = number
        else:
            by_direction.setdefault(direction, _empty_direction())[metric][str(bucket)] = number
    for entry in by_direction.values():
        entry["runs"] = dict(sorted(entry["runs"].items(), key=lambda item: int(item[0])))
        entry["runClamped"] = dict(sorted(entry["runClamped"].items(), key=lambda item: int(item[0])))
        lengths = {int(length): count for length, count in entry["runs"].items()}
        clamped = {int(length): count for length, count in entry["runClamped"].items()}
        elements = sum(length * count for length, count in lengths.items())
        repeated_elements = sum(length * count for length, count in lengths.items() if length >= 2)
        repeated_clamped = sum(count for length, count in clamped.items() if length >= 2)
        entry["elements"] = elements
        entry["clamped"] = sum(clamped.values())
        entry["clampedRate"] = entry["clamped"] / elements if elements else None
        entry["repeated"] = {
            "runs": sum(count for length, count in lengths.items() if length >= 2),
            "elements": repeated_elements,
            "clamped": repeated_clamped,
            "clampedRate": repeated_clamped / repeated_elements if repeated_elements else None,
            "elementShare": repeated_elements / elements if elements else None,
        }
        entry["longestRun"] = max(lengths, default=0)
    ordered = {"all": by_direction.pop("all")}
    for direction in REPEAT_DIRECTIONS:
        if direction in by_direction:
            ordered[direction] = by_direction.pop(direction)
    return {"scope": scope, "byDirection": ordered | by_direction}


async def stat_repeat_distribution(
    connection: Any, *, since: datetime, until: datetime | None = None
) -> dict[str, Any]:
    """연결(asyncpg) 하나에서 반복 집계 SQL 을 돌려 요약한다. 읽기 전용으로 여는 것은 부르는 쪽 몫이다."""
    rows = await connection.fetch(stat_repeat_sql(since, until))
    return summarize_repeat_rows([tuple(row) for row in rows])


def connect_kwargs(database_url: str, database: str | None = None) -> dict[str, Any]:
    """SQLAlchemy 꼴 URL(`postgresql+asyncpg://…`)을 asyncpg 접속 인자로. `database` 를 주면 같은 서버의 그 DB 로."""
    url = make_url(database_url)
    return {
        "host": url.host,
        "port": url.port,
        "user": url.username,
        "password": url.password,
        "database": database or url.database,
    }


@contextlib.asynccontextmanager
async def read_only_connection(database_url: str, database: str | None = None) -> AsyncIterator[asyncpg.Connection]:
    """로컬 DB 에만, 세션 기본값과 트랜잭션 둘 다 읽기 전용으로 연다. 트랜잭션은 끝에 되돌린다(쓴 것이 없어도)."""
    ensure_local_database(database_url, tool="memory_eval 관측")
    connection = await asyncpg.connect(
        **connect_kwargs(database_url, database), server_settings={"default_transaction_read_only": "on"}
    )
    transaction = connection.transaction(readonly=True)
    await transaction.start()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()
