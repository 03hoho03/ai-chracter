"""소설 리플레이 출력의 기계 지표 — LLM 판정 없이, 운영이 출력을 받을 때 쓰는 순수 함수로 센다.

판정 규칙을 새로 만들지 않는다. 화 생성은 운영 실행(`novelize/runner.py` 의 묶음 받기)이 쓰는 함수를 같은 순서로 부른다: 구분자 형식
파서(`parse_batch_output`), 형식이 없는 한 화 출력을 옛 형식으로 받는 조건(`has_structure_lines`), 본문 후처리(`clean_chapter_body`·
`split_paragraphs`), 거절 판정(`looks_like_refusal`), 최소 길이 설정. 구성안 둘은 응답 스키마 검증과 저장 쪽 검증(`outline_episodes`·
`model_scenes` — 화·장면 수 범위, 턴 범위·겹침·순서, 빈 제목, 거절문)을 그대로 부른다. 같은 규칙을 여기 베끼면 운영 규칙이 바뀔 때
지표만 옛 규칙으로 남는다.

저장 쪽 검증은 원문 줄의 턴마다 메시지 구간을 받는다. 덤프에는 메시지가 없으므로 슬롯 값의 원문 줄(`turn_lines`)에서 턴 수만 읽어 그
수만큼 자리 구간을 만든다 — 검증이 구간에서 읽는 것은 개수뿐이고 구간을 메시지 id 로 바꾼 결과는 지표에 쓰지 않는다. 원문 줄의
턴 표시는 `novelize/source.py` 의 `format_turn_lines` 가 줄 머리에 붙이는 `[턴 n]` 이다.

장면 구성안을 원고가 순서대로 따랐는지 재는 운영 함수는 없다 — 원고 저장은 장면 경계를 모델 출력에서 읽지 않고, 장면마다 근거 원문
글자 수를 몫으로 삼아 문단을 차례대로 나눈다(`novelize/scenes.py` 의 `assign_scenes`). 그래서 이 리포트는 장면 수만 센다. 리포트에는
개수·비율·판 번호·모델 id 만 싣는다 — 출력 본문과 표지 글자는 싣지 않는다."""

import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from api.core.config import settings
from api.db.models.chat import ChatMessage
from api.novelize.outline import MalformedOutlineError, RefusedOutlineError, TurnSpan, outline_episodes
from api.novelize.output import MalformedOutputError, ParsedEpisode, has_structure_lines, parse_batch_output
from api.novelize.prompts import NovelizeEpisodeOutlineResult, NovelizeOutlineResult
from api.novelize.scene_outline import MalformedScenesError, RefusedScenesError, SceneSpan, model_scenes
from api.novelize.text import clean_chapter_body, looks_like_refusal, split_paragraphs
from turn_cost_report import percentile

CHAPTER_CHANNEL = "novelize_chapter"
STRUCTURED_SCHEMAS: dict[str, type[BaseModel]] = {
    "novelize_outline": NovelizeOutlineResult,
    "novelize_episode_outline": NovelizeEpisodeOutlineResult,
}
_TURN_HEAD = re.compile(r"^\[턴 (\d+)\]", re.MULTILINE)


@dataclass(frozen=True)
class ChapterChecks:
    """화 생성 출력 하나. `parsed` 는 구분자 형식 통과, `legacy` 는 형식이 없는 한 화 출력이라 운영이 옛 형식으로 받는 경우(형식
    통과로 세지 않는다), `refused` 는 거절문, `below_min` 은 최소 길이에 못 미친 화 수, `chars` 는 화마다 후처리한 본문 글자 수."""

    parsed: bool
    legacy: bool
    refused: bool
    episodes: int
    below_min: int
    chars: list[int]


@dataclass(frozen=True)
class StructuredChecks:
    """구성안 출력 하나. `schema_ok` 는 응답 스키마 검증, `valid` 는 저장 쪽 검증까지 통과, `refused` 는 거절문 판정, `items` 는 화·장면 수
    (스키마를 통과했을 때)."""

    schema_ok: bool
    valid: bool
    refused: bool
    items: int


def chapter_checks(output: str, values: Mapping[str, str]) -> ChapterChecks:
    """운영 묶음 받기와 같은 순서 — 형식 → 화마다 후처리 → 거절 → 최소 길이. 형식이 어긋난 출력은 전체를 후처리해 거절만 본다.
    화 번호 예외(`episode_number`)는 주지 않는다 — 덤프에 그 화의 번호가 없어서다(구성 흐름 원고가 `1화` 대신 이어지는 번호를 쓰면
    여기서는 형식 실패로 센다)."""
    legacy = False
    try:
        episodes = parse_batch_output(output).episodes
        parsed = True
    except MalformedOutputError:
        parsed = False
        if values.get("episode_count") == "1" and not has_structure_lines(output):
            legacy = True
            episodes = (ParsedEpisode(None, None, (), output),)
        else:
            refused = looks_like_refusal(split_paragraphs(clean_chapter_body(output)))
            return ChapterChecks(parsed=False, legacy=False, refused=refused, episodes=0, below_min=0, chars=[])
    bodies = [clean_chapter_body(episode.body) for episode in episodes]
    return ChapterChecks(
        parsed=parsed,
        legacy=legacy,
        refused=any(looks_like_refusal(split_paragraphs(body)) for body in bodies),
        episodes=len(bodies),
        below_min=sum(len(body) < settings.novelize_min_chapter_chars for body in bodies),
        chars=[len(body) for body in bodies],
    )


def turn_count(values: Mapping[str, str]) -> int:
    numbers = [int(n) for n in _TURN_HEAD.findall(values.get("turn_lines", ""))]
    return max(numbers, default=0)


def structured_checks(channel: str, output: str, values: Mapping[str, str]) -> StructuredChecks:
    schema = STRUCTURED_SCHEMAS[channel]
    try:
        result = schema.model_validate_json(output)
    except ValidationError:
        return StructuredChecks(schema_ok=False, valid=False, refused=False, items=0)
    turns = turn_count(values)
    try:
        if isinstance(result, NovelizeOutlineResult):
            items = len(result.episodes)
            outline_episodes(result, [TurnSpan(0, uuid.uuid4(), uuid.uuid4())] * turns)
        else:
            assert isinstance(result, NovelizeEpisodeOutlineResult)
            items = len(result.scenes)
            message = ChatMessage(id=uuid.uuid4(), created_at=datetime.now(UTC))
            model_scenes(result, [SceneSpan(0, message, message)] * turns)
    except (MalformedOutlineError, MalformedScenesError):
        return StructuredChecks(schema_ok=True, valid=False, refused=False, items=items)
    except (RefusedOutlineError, RefusedScenesError):
        return StructuredChecks(schema_ok=True, valid=False, refused=True, items=items)
    return StructuredChecks(schema_ok=True, valid=True, refused=False, items=items)


def leaked_markers(output: str, values: Mapping[str, str], markers: Sequence[str]) -> list[str]:
    """입력 슬롯 값 어딘가에 심긴 표지 중 출력에도 나온 것. 입력에 없는 표지는 세지 않는다(그 호출에 심지 않았다)."""
    return [m for m in markers if any(m in value for value in values.values()) and m in output]


@dataclass
class Ledger:
    """원장에서 읽은 호출(덤프 줄의 슬롯 값을 붙인 것)과 갈래·채널별 판 번호."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    semvers: dict[tuple[str, str], set[str]] = field(default_factory=dict)


def load_calls(paths: Iterable[Path], dump: Path) -> Ledger:
    """원장의 호출 기록에 덤프 줄의 슬롯 값을 줄 번호로 붙인다. 줄 번호의 작업 id 가 덤프와 다르면 다른 덤프로 만든 원장이라 거부한다."""
    lines = [json.loads(line) for line in dump.read_text(encoding="utf-8").splitlines()]
    ledger = Ledger()
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            record = json.loads(raw)
            if record.get("kind") == "plan" and "arm" in record:
                semver = record.get("setSemver")
                ledger.semvers.setdefault((record["arm"], record["channel"]), set()).add(semver or "판 없음")
            if record.get("kind") != "call":
                continue
            line = lines[record["line"] - 1]
            if line.get("jobId") != record["jobId"]:
                raise ValueError(f"원장 {path} 의 덤프 줄 {record['line']} 이 이 덤프의 작업과 다르다")
            ledger.calls.append({**record, "values": line.get("values") or {}})
    return ledger


def _ratio(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def summarize(ledger: Ledger, markers: Sequence[str]) -> list[dict[str, Any]]:
    """갈래·채널별 한 줄. 오류로 끝난 호출은 `errors` 로만 세고 형식 지표의 분모에서 뺀다(출력이 없다)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for call in ledger.calls:
        groups.setdefault((call["arm"], call["channel"]), []).append(call)
    rows: list[dict[str, Any]] = []
    for (arm, channel), calls in sorted(groups.items()):
        answered = [c for c in calls if c.get("error") is None]
        row: dict[str, Any] = {
            "arm": arm,
            "channel": channel,
            "calls": len(calls),
            "errors": len(calls) - len(answered),
            "sentModels": sorted({c["sentModel"] for c in calls if c.get("sentModel")}),
            "setSemvers": sorted(ledger.semvers.get((arm, channel), set())),
            "knownUsd": round(sum(c["costUsd"] for c in calls if c.get("costUsd") is not None), 6),
        }
        leaks = [c for c in answered if leaked_markers(c.get("output") or "", c["values"], markers)]
        row["leakCalls"] = len(leaks)
        row["leakRate"] = _ratio(len(leaks), len(answered))
        if channel == CHAPTER_CHANNEL:
            checks = [chapter_checks(c.get("output") or "", c["values"]) for c in answered]
            chars = [float(n) for check in checks for n in check.chars]
            row |= {
                "formatOk": sum(c.parsed for c in checks),
                "formatRate": _ratio(sum(c.parsed for c in checks), len(checks)),
                "legacy": sum(c.legacy for c in checks),
                "refused": sum(c.refused for c in checks),
                "belowMinEpisodes": sum(c.below_min for c in checks),
                "episodes": sum(c.episodes for c in checks),
                "charsP50": percentile(chars, 0.5),
                "charsP90": percentile(chars, 0.9),
            }
        else:
            structured = [structured_checks(channel, c.get("output") or "", c["values"]) for c in answered]
            items = [float(s.items) for s in structured if s.schema_ok]
            row |= {
                "schemaOk": sum(s.schema_ok for s in structured),
                "formatOk": sum(s.valid for s in structured),
                "formatRate": _ratio(sum(s.valid for s in structured), len(structured)),
                "refused": sum(s.refused for s in structured),
                "itemsP50": percentile(items, 0.5),
                "itemsP90": percentile(items, 0.9),
            }
        rows.append(row)
    return rows


_COLUMNS = (
    "arm",
    "channel",
    "calls",
    "errors",
    "formatOk",
    "formatRate",
    "schemaOk",
    "legacy",
    "refused",
    "belowMinEpisodes",
    "episodes",
    "charsP50",
    "charsP90",
    "itemsP50",
    "itemsP90",
    "leakCalls",
    "leakRate",
    "setSemvers",
    "sentModels",
    "knownUsd",
)


def render_markdown(rows: Sequence[Mapping[str, Any]], *, markers: int) -> str:
    def cell(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) or "-"
        return str(value)

    head = [
        "# 소설 리플레이 기계 지표",
        "",
        f"누출 표지 {markers}개. 오류로 끝난 호출은 형식·누출 지표의 분모에서 뺀다.",
        "",
        "| " + " | ".join(_COLUMNS) + " |",
        "|" + "---|" * len(_COLUMNS),
    ]
    body = ["| " + " | ".join(cell(row.get(column)) for column in _COLUMNS) + " |" for row in rows]
    return "\n".join(head + body) + "\n"
