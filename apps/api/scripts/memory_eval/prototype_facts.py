"""사실 계층 시제품 추출 — 접힌 창(스냅샷)마다 문안 파일과 모델로 관계·사실 행을 뽑아 JSON 으로 저장한다(DB 에 넣지 않는다).
운영 추출을 만들기 전에 문안과 행 모양을 재는 용도다.

창과 줄 번호는 장면 시제품과 같다(`prototype_extract.build_windows`·`render_window`·`map_lines`). 입력에는 그 창 앞 창들의
행을 키별 최신으로 줄인 기존 키 목록(최근 40줄)을 준다 — 같은 대상을 새 키로 또 쓰지 않고 기존 키로 갱신하게.

실제 호출은 Anthropic 직결 Haiku 5.5(사고 끔·구조화 effort low), 키는 설정(환경변수)으로만 받는다. 호출마다 원장에
call_site·토큰·원가를 남긴다. 호출 함수는 주입받는다 — 테스트와 넣기 절차는 가짜를 넣는다.

넣기 절차의 따라잡기용 저장소(`FactStore`)는 스냅샷마다 한 줄(JSONL)이다: 그 스냅샷을 추출했으면 완료로 본다."""

import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from memory_eval.facts import existing_key_lines, fact_key
from memory_eval.ledger import Ledger
from memory_eval.prototype_extract import Window, map_lines

FACT_MODEL = "claude-haiku-5-5"
FACT_CALL_SITE = "memory_eval_prototype_facts"
# 창 하나 견적: 입력 약 4K 토큰(대화 + 기존 키 40줄) × 토크나이저 1.3, 출력 약 1.5K.
FACT_CALL_ESTIMATE_USD = 0.002
# 저장 전에 자르는 창당 행 수와 값 길이(시제품 값 — 운영 스키마가 생기면 그 상수와 맞춘다).
MAX_FACTS = 20
VALUE_MAX = 200


class PrototypeFact(BaseModel):
    kind: Literal["relation", "fact"]
    subject: str
    # 관계의 대상(사실이면 빈 문자열)과 사실의 속성(관계면 빈 문자열). 구조화 스키마에서 선택 칸을 피하려고 빈 문자열로 받는다.
    object: str
    attribute: str
    value: str
    truth_status: Literal["confirmed", "claimed", "disproved"]
    asserted_by: Literal["user", "character", "narration"]
    speaker: str
    known_by: list[str]
    importance: int
    start_line: int
    end_line: int


class PrototypeFactResult(BaseModel):
    facts: list[PrototypeFact]


FactCaller = Callable[[str], Awaitable[PrototypeFactResult]]


def build_prompt(instruction: str, user_name: str, existing: Sequence[str], turn_lines: str) -> str:
    parts = [instruction.strip(), f"사용자의 이야기 속 이름: {user_name}"]
    parts.append("[기존 키]\n" + ("\n".join(existing) if existing else "(없음)"))
    parts.append("[접힌 대화]\n" + turn_lines)
    return "\n\n".join(parts)


async def call_haiku(
    api_key: str, prompt: str, ledger: Ledger, *, stage: str, model: str = FACT_MODEL
) -> PrototypeFactResult:
    if not api_key:
        raise SystemExit("사실 시제품 추출은 Anthropic 키가 있어야 한다")
    import anthropic

    from api.llm.claude_messages import message_usage, parse_structured, structured_output_config

    ledger.check_headroom(FACT_CALL_ESTIMATE_USD)
    output_config: Any = {**structured_output_config(PrototypeFactResult), "effort": "low"}
    message = await anthropic.AsyncAnthropic(api_key=api_key).messages.create(
        model=model,
        max_tokens=8_000,
        thinking={"type": "disabled"},
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = message_usage(message)
    ledger.append(
        stage=stage,
        call_site=FACT_CALL_SITE,
        model=model,
        input_tokens=usage.prompt_token_count,
        cached_tokens=usage.cached_content_token_count,
        cache_write_tokens=usage.cache_write_token_count,
        output_tokens=usage.candidates_token_count,
        thoughts_tokens=usage.thoughts_token_count,
    )
    return parse_structured(message, PrototypeFactResult, "anthropic", "Anthropic")


def fact_rows(window: Window, result: PrototypeFactResult, *, version: str) -> list[dict[str, Any]]:
    """서버가 저장 전에 하듯 주어·값이 빈 행을 버린 뒤 앞에서부터 `MAX_FACTS` 개, 값은 `VALUE_MAX` 에서 자른다. 종류에 맞지 않는
    칸(관계의 속성·사실의 대상)은 버리고, 빈 화자·빈 아는 사람은 없음(None)으로 둔다."""
    kept = [f for f in result.facts if f.subject.strip() and f.value.strip()][:MAX_FACTS]
    rows = []
    for k, fact in enumerate(kept):
        start, end = map_lines(window, fact.start_line, fact.end_line)
        relation = fact.kind == "relation"
        target = (fact.object if relation else fact.attribute).strip()
        known = [n.strip() for n in fact.known_by if n.strip()]
        rows.append(
            {
                "id": f"{window.snapshot_id}:f{k}",
                "snapshot_id": str(window.snapshot_id),
                "kind": fact.kind,
                "subject": fact.subject.strip(),
                "object": target if relation else None,
                "attribute": None if relation else target,
                "fact_key": fact_key(fact.kind, fact.subject, target),
                "value": fact.value.strip()[:VALUE_MAX],
                "truth_status": fact.truth_status,
                "asserted_by": fact.asserted_by,
                "speaker": fact.speaker.strip() or None,
                "known_by": known or None,
                "importance": min(max(fact.importance, 1), 5),
                "start_turn": start,
                "end_turn": end,
                "available_from_turn": window.fold_turn + 1,
                "promptVersion": version,
            }
        )
    return rows


async def extract_window(
    window: Window,
    *,
    prior_rows: Sequence[dict[str, Any]],
    render: Callable[[Window], str],
    caller: FactCaller,
    instruction: str,
    user_name: str,
    version: str,
) -> list[dict[str, Any]]:
    prompt = build_prompt(instruction, user_name, existing_key_lines(prior_rows), render(window))
    return fact_rows(window, await caller(prompt), version=version)


async def extract_windows(
    windows: Sequence[Window],
    *,
    render: Callable[[Window], str],
    caller: FactCaller,
    instruction: str,
    user_name: str,
    version: str,
) -> list[dict[str, Any]]:
    """창 순서대로 — 창마다 그 앞 창들의 행이 기존 키 목록이 된다."""
    rows: list[dict[str, Any]] = []
    for window in windows:
        rows += await extract_window(
            window,
            prior_rows=rows,
            render=render,
            caller=caller,
            instruction=instruction,
            user_name=user_name,
            version=version,
        )
    return rows


class FactStore:
    """넣기 절차의 따라잡기 기록. 한 줄 = 추출을 마친 스냅샷 하나(`snapshotId`, 그 창의 `rows`)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def done_ids(self) -> set[str]:
        return {str(r["snapshotId"]) for r in self.records()}

    def append(self, snapshot_id: uuid.UUID, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            record = {"snapshotId": str(snapshot_id), "rows": rows}
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def next_pending(windows: Sequence[Window], done: set[str]) -> int | None:
    """아직 추출하지 않은 가장 이른 창의 순번. 운영 추출처럼 오래된 것부터 하나씩 따라잡는다."""
    return next((i for i, w in enumerate(windows) if str(w.snapshot_id) not in done), None)


async def extract_next(
    windows: Sequence[Window],
    store: FactStore,
    *,
    render: Callable[[Window], str],
    caller: FactCaller,
    instruction: str,
    user_name: str,
    version: str,
) -> bool:
    """가장 이른 미추출 창 하나를 추출해 저장한다. 할 일이 없었으면 거짓. 기존 키는 지금 남아 있는 창 가운데 그 창 앞의 것만
    쓴다(되감기로 지워진 스냅샷의 기록은 남아 있어도 쓰지 않는다)."""
    index = next_pending(windows, store.done_ids())
    if index is None:
        return False
    by_snapshot = {str(r["snapshotId"]): r["rows"] for r in store.records()}
    prior = [row for w in windows[:index] for row in by_snapshot.get(str(w.snapshot_id), [])]
    rows = await extract_window(
        windows[index],
        prior_rows=prior,
        render=render,
        caller=caller,
        instruction=instruction,
        user_name=user_name,
        version=version,
    )
    store.append(windows[index].snapshot_id, rows)
    return True


def load_fact_rows(path: Path) -> list[dict[str, Any]]:
    """사실 행 목록: 시제품 추출 출력(JSON 배열) 또는 넣기 따라잡기 기록(JSONL, 줄마다 `rows`)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [row for line in text.splitlines() if line.strip() for row in json.loads(line)["rows"]]
    rows: list[dict[str, Any]] = json.loads(text)
    return rows
