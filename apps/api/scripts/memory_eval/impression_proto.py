"""인상(Reflective) 문안 시제품과 문장 단위 판정 — 운영 인상 생성(`chat/memory_impressions.py`)과 같은 입력으로 후보 문안의 인상을
다시 만들고, 인상 문장마다 입력에 근거가 있는지·작가 설정과 어긋나는지 판정한다. 운영 문안이 DB 에 심기기 전에 문안을 고르고,
저장 품질을 재는 용도다.

입력(`load_room_inputs`): 방의 스냅샷을 커서 순으로 N 개씩 꽉 찬 묶음으로 자른다 — 운영은 스냅샷 수가 N 의 배수가 될 때마다
가장 새 N 개를 묶으므로, 대화가 끝까지 흘렀을 때 운영이 만들었을 묶음과 같다. 묶음 스냅샷의 장면·사실 추출이 모두 `done` 이
아니면 운영처럼 건너뛴다. 행은 운영 함수(`_load_inputs`)로 읽는다 — 아는 사람이 정해진 행을 빼는 조건과 순서를 따로 쓰면 운영과
어긋날 수 있어서다. 줄 모양도 운영 함수(`episode_line`·`fact_line`)다. 빠진 비밀 행은 개수만 남긴다. DB 는 읽기만 한다.

생성(`run_generation`): 후보 문안 파일의 섹션을 운영 인상 채널 섹션처럼 만들어 운영 조립 함수로 렌더하고, 운영과 같은 호출
위치(`chat_memory_impression`)·같은 모델 고르기(설정 `memory_impression_model` 을 Haiku 로)로 부른다. 글은 운영처럼 앞뒤 공백을
걷고 상한에서 자른다 — 자르기 전 길이와 잘렸는지를 함께 남긴다. 호출마다 그 전에 원장 상한을 본다. 끊긴 실행은 이어서 돈다.

판정(`judge_items`): 인상 글을 문장으로 나눠 번호를 붙이고, 판정 문안 파일(공개 저장소 밖)의 틀에 작가 설정·입력 줄·문장을 채워
판정자에게 문장마다 근거 있음 / 근거 없음 / 설정 어긋남을 받는다. 같은 입력을 두 번 묻고 모든 문장이 같으면 그 값, 한 문장이라도
갈리거나 한 표가 불능이면 셋째를 받아 문장마다 과반으로 정한다. 과반이 없는 문장은 판정 불능이다. 정답이 붙은 대조군(합성
견본)은 측정이 세는 단위 그대로 관문을 본다 — 문장 3갈래 정확도, 근거 없음·어긋남을 하나로 본 이진 정확도, 어긋남 이진 정확도가
모두 문턱 이상이고 불능 문장이 0 이어야 통과한다. 문턱은 측정 하네스 판정자 대조군과 같은 값(`CONTROL_ACCURACY_MIN`)이다.

결과 파일에는 인상 글·입력 줄이 들어 있다 — 공개 저장소에 넣지 않는다. 집계(`length_report`·`judge_report`)는 숫자만 낸다."""

import asyncio
import hashlib
import json
import re
import statistics
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any, Literal, Protocol, TypeVar, cast, get_args

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_impressions
from api.chat.memory_impressions import episode_line, fact_line
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, MemoryImpressionResult, build_memory_impression_prompt
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMemoryFact,
    ChatMemoryFactExtraction,
    ChatRoom,
    ChatRoomMemorySnapshot,
    PromptSection,
)
from api.db.models.chat import IMPRESSION_TEXT_MAX
from api.llm.client import CallUsage, LLMCallContext, LLMCallSite, LLMClientError
from memory_eval.judge import CONTROL_ACCURACY_MIN, JUDGE_MODELS, JUDGE_RETRIES, _gather_or_cancel
from memory_eval.judge_agreement import setting_overrides
from memory_eval.ledger import BudgetExceededError, Ledger, cost_usd

Lane = Literal["story", "character"]
Label = Literal["supported", "unsupported", "conflict"]
LABELS: tuple[str, ...] = get_args(Label)

CHANNEL = "memory_impression"
# 운영 인상 생성과 같은 호출 위치 — 앱이 이 위치로 모델·출력 상한·시간 제한을 고른다.
IMPRESSION_CALL_SITE: LLMCallSite = "chat_memory_impression"
# 운영에서 인상을 켤 때 고르는 모델(설정 값). 이 설정이 기본 Gemini 로 남아 있으면 다른 모델로 잰 셈이 된다.
IMPRESSION_MODEL_OVERRIDE: dict[str, Any] = {"memory_impression_model": "haiku"}
JUDGE_CALL_SITE = "memory_eval_impression_judge"
JUDGE_MODEL = "claude-opus-5-5"
# 판정 한 번의 출력 상한. 사고를 끌 수 없는 판정자의 사고 토큰도 이 안에 든다 — 문장 여럿의 이유를 함께 내므로 문항 하나짜리
# 판정자보다 넉넉히 둔다.
JUDGE_MAX_TOKENS = 4_000
JUDGE_FIRST_VOTES = 2
JUDGE_MAX_VOTES = 3
RETRY_PAUSE_SECONDS = 1.0
TEMPLATE_FIELDS = frozenset({"author_setting", "episode_lines", "fact_lines", "sentences"})
SCOPES = frozenset({"both", "story", "character"})
# 입력 줄이 하나도 없을 때 판정 틀에 채우는 글.
EMPTY_LINES = "(없음)"

_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+|\n+")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 입력


@dataclass(frozen=True)
class ImpressionInput:
    room_id: str
    lane: Lane
    # 방 안에서 몇 번째 묶음인지(1부터).
    group_index: int
    snapshot_ids: tuple[str, ...]
    episode_lines: tuple[str, ...]
    fact_lines: tuple[str, ...]
    episode_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    # 아는 사람이 정해져 입력에서 빠진 행 수.
    withheld_episodes: int
    withheld_facts: int

    @property
    def key(self) -> str:
        return f"{self.room_id}:{self.group_index}"

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "roomId": self.room_id,
            "lane": self.lane,
            "groupIndex": self.group_index,
            "snapshotIds": list(self.snapshot_ids),
            "episodeLines": list(self.episode_lines),
            "factLines": list(self.fact_lines),
            "episodeIds": list(self.episode_ids),
            "factIds": list(self.fact_ids),
            "withheldEpisodes": self.withheld_episodes,
            "withheldFacts": self.withheld_facts,
        }

    @classmethod
    def from_json(cls, row: Mapping[str, Any]) -> "ImpressionInput":
        lane = row["lane"]
        if lane not in ("story", "character"):
            raise SystemExit(f"모르는 레인: {lane!r}")
        return cls(
            room_id=str(row["roomId"]),
            lane=lane,
            group_index=int(row["groupIndex"]),
            snapshot_ids=tuple(row["snapshotIds"]),
            episode_lines=tuple(row["episodeLines"]),
            fact_lines=tuple(row["factLines"]),
            episode_ids=tuple(row["episodeIds"]),
            fact_ids=tuple(row["factIds"]),
            withheld_episodes=int(row["withheldEpisodes"]),
            withheld_facts=int(row["withheldFacts"]),
        )


def load_inputs(paths: Iterable[Path]) -> list[ImpressionInput]:
    items = [ImpressionInput.from_json(row) for path in paths for row in read_rows(path) if "groupIndex" in row]
    keys = [item.key for item in items]
    duplicated = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicated:
        raise SystemExit(f"같은 묶음이 두 번 들어 있다: {duplicated[:5]}")
    return items


_T = TypeVar("_T")


def full_groups(ids: Sequence[_T], every: int) -> list[list[_T]]:
    """순서대로 N 개씩 꽉 찬 묶음. 남는 꼬리는 운영도 아직 묶지 않았으므로 버린다."""
    if every < 1:
        raise ValueError("묶음 크기는 1 이상이다")
    return [list(ids[start : start + every]) for start in range(0, len(ids) - every + 1, every)]


async def load_room_inputs(
    session: AsyncSession, room_id: uuid.UUID, *, every: int
) -> tuple[list[ImpressionInput], list[dict[str, Any]]]:
    """방의 묶음마다 운영과 같은 입력. 돌려주는 둘째 값은 건너뛴 묶음(추출이 덜 끝났다)이다."""
    starting_setup = await session.execute(select(ChatRoom.starting_setup_entity_id).where(ChatRoom.id == room_id))
    found = starting_setup.first()
    if found is None:
        raise SystemExit(f"방이 없다: {room_id}")
    lane: Lane = "character" if found[0] is None else "story"
    snapshot = ChatRoomMemorySnapshot
    snapshots = (
        await session.execute(
            select(snapshot.id, snapshot.cursor_created_at, snapshot.cursor_message_id)
            .where(snapshot.chat_room_id == room_id)
            .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id)
        )
    ).all()
    inputs: list[ImpressionInput] = []
    skipped: list[dict[str, Any]] = []
    for index, members in enumerate(full_groups(snapshots, every), start=1):
        ids = [row.id for row in members]
        if not await _extractions_done(session, ids):
            skipped.append({"roomId": str(room_id), "groupIndex": index, "reason": "extraction_not_done"})
            continue
        group = memory_impressions._Group(
            room_id=room_id,
            snapshot_ids=ids,
            first_cursor=(members[0].cursor_created_at, members[0].cursor_message_id),
        )
        episodes, facts = await memory_impressions._load_inputs(session, group)
        inputs.append(
            ImpressionInput(
                room_id=str(room_id),
                lane=lane,
                group_index=index,
                snapshot_ids=tuple(str(i) for i in ids),
                episode_lines=tuple(episode_line(row) for row in episodes),
                fact_lines=tuple(fact_line(row) for row in facts),
                episode_ids=tuple(str(row.id) for row in episodes),
                fact_ids=tuple(str(row.id) for row in facts),
                withheld_episodes=await _withheld(session, ChatMemoryEpisode, ids),
                withheld_facts=await _withheld(session, ChatMemoryFact, ids),
            )
        )
    return inputs, skipped


async def _extractions_done(session: AsyncSession, ids: Sequence[uuid.UUID]) -> bool:
    for extraction in (ChatMemoryExtraction, ChatMemoryFactExtraction):
        done = await session.scalar(
            select(func.count())
            .select_from(extraction)
            .where(extraction.snapshot_id.in_(ids), extraction.status == "done")
        )
        if done != len(ids):
            return False
    return True


async def _withheld(
    session: AsyncSession, model: type[ChatMemoryEpisode] | type[ChatMemoryFact], ids: Sequence[uuid.UUID]
) -> int:
    count = await session.scalar(
        select(func.count()).select_from(model).where(model.snapshot_id.in_(ids), model.known_by.is_not(None))
    )
    return int(count or 0)


# ---------------------------------------------------------------- 후보 문안


def load_candidate(path: Path) -> tuple[list[PromptSection], str]:
    """후보 문안 파일 → 인상 채널 섹션(세션에 넣지 않는다)과 파일 sha. 운영 채널에 그대로 심을 수 있는 꼴만 받는다 — 슬롯과
    플레이스홀더는 운영 허용 표(`ALLOWED_PLACEHOLDERS`) 안, scope 는 셋 중 하나."""
    raw = path.read_bytes()
    spec = json.loads(raw)
    sections: list[PromptSection] = []
    for entry in spec["sections"]:
        slot = entry["slot"]
        allowed = ALLOWED_PLACEHOLDERS.get((CHANNEL, slot))
        if allowed is None:
            raise SystemExit(f"인상 채널에 없는 슬롯: {slot!r}")
        body = entry["body"]
        used = {name for _, name, _, _ in Formatter().parse(body) if name}
        if not used <= allowed:
            raise SystemExit(f"슬롯 {slot!r} 에 허용되지 않은 플레이스홀더: {sorted(used - allowed)}")
        if entry["scope"] not in SCOPES:
            raise SystemExit(f"모르는 scope: {entry['scope']!r}")
        sections.append(
            PromptSection(
                prompt_set_id=uuid.UUID(int=0),
                channel=CHANNEL,
                scope=entry["scope"],
                slot=slot,
                variant="",
                body=body,
                conditional=bool(entry["conditional"]),
                order=int(entry["order"]),
            )
        )
    return sections, hashlib.sha256(raw).hexdigest()


def render_prompt(item: ImpressionInput, sections: Sequence[PromptSection]) -> str:
    prompt = build_memory_impression_prompt(
        sections=sections,
        is_story_chat=item.lane == "story",
        episode_lines=item.episode_lines,
        fact_lines=item.fact_lines,
    )
    if not prompt:
        raise SystemExit(f"{item.lane} 레인에서 후보 문안이 빈 프롬프트를 낸다")
    return prompt


def finalize(raw: str) -> tuple[str, int, bool]:
    """운영과 같은 다듬기 — (저장될 글, 자르기 전 길이, 잘렸는가)."""
    stripped = raw.strip()
    return stripped[:IMPRESSION_TEXT_MAX].strip(), len(stripped), len(stripped) > IMPRESSION_TEXT_MAX


# ---------------------------------------------------------------- 생성


class StructuredClient(Protocol):
    async def generate_structured(self, prompt: str, response_schema: Any, *, usage: LLMCallContext) -> Any: ...


def _done_keys(rows: Sequence[Mapping[str, Any]], candidate_sha: str) -> set[str]:
    return {str(r["key"]) for r in rows if r.get("candidateSha") == candidate_sha and r.get("status") == "ok"}


def estimate(
    items: Sequence[ImpressionInput],
    sections: Sequence[PromptSection],
    *,
    model: str,
    tokens_per_char: float,
    output_tokens: int,
    done: set[str],
) -> dict[str, Any]:
    """아직 결과가 없는 묶음의 호출 수·프롬프트 글자·견적. 입력 토큰은 글자 수 × 글자당 토큰으로 어림한다."""
    pending = [item for item in items if item.key not in done]
    chars = [len(render_prompt(item, sections)) for item in pending]
    costs = [
        cost_usd(
            model,
            input_tokens=round(c * tokens_per_char),
            cached_tokens=0,
            cache_write_tokens=0,
            output_tokens=output_tokens,
            thoughts_tokens=0,
        )
        for c in chars
    ]
    return {
        "calls": len(pending),
        "promptChars": sum(chars),
        "maxPromptChars": max(chars, default=0),
        "perCallMaxUsd": max(costs, default=0.0),
        "totalUsd": sum(costs),
    }


async def run_generation(
    items: Sequence[ImpressionInput],
    sections: Sequence[PromptSection],
    *,
    candidate_sha: str,
    client: StructuredClient,
    ledger: Ledger,
    out_path: Path,
    stage: str,
    call_estimate_usd: float,
) -> int:
    """아직 결과가 없는 묶음마다 인상을 만든다. 호출 전에 원장 여유를 보고(넘을 것 같으면 `BudgetExceededError`), 끝나면 공급자가
    보고한 토큰으로 원장에 한 줄, 결과 파일에 한 줄. 실패한 호출은 실패 줄을 남기고 다음 실행에서 다시 부른다."""
    done = _done_keys(read_rows(out_path), candidate_sha)
    made = 0
    for item in items:
        if item.key in done:
            continue
        prompt = render_prompt(item, sections)
        ledger.check_headroom(call_estimate_usd)
        sink: list[CallUsage] = []
        usage = LLMCallContext(call_site=IMPRESSION_CALL_SITE, user_id=None, room_id=None, usage_sink=sink)
        row: dict[str, Any] = {
            "key": item.key,
            "roomId": item.room_id,
            "groupIndex": item.group_index,
            "lane": item.lane,
            "candidateSha": candidate_sha,
            "promptSha": sha256_text(prompt),
            "promptChars": len(prompt),
        }
        try:
            with setting_overrides(IMPRESSION_MODEL_OVERRIDE):
                result = await client.generate_structured(prompt, MemoryImpressionResult, usage=usage)
            text, raw_chars, truncated = finalize(cast(MemoryImpressionResult, result).impression)
            row |= {"status": "ok", "error": None, "text": text, "rawChars": raw_chars, "truncated": truncated}
        except LLMClientError as exc:
            row |= {
                "status": "call_error",
                "error": type(exc).__name__,
                "text": None,
                "rawChars": None,
                "truncated": None,
            }
        for call in sink:
            ledger.append(
                stage=stage,
                call_site=IMPRESSION_CALL_SITE,
                model=call.model,
                input_tokens=call.prompt_tokens or 0,
                cached_tokens=call.cached_tokens or 0,
                cache_write_tokens=call.cache_write_tokens or 0,
                output_tokens=call.output_tokens or 0,
                thoughts_tokens=call.thoughts_tokens or 0,
                note=f"impression-proto {item.key}",
            )
        row |= {
            "model": sink[0].model if sink else None,
            "inputTokens": sum(c.prompt_tokens or 0 for c in sink),
            "outputTokens": sum(c.output_tokens or 0 for c in sink),
        }
        _append(out_path, row)
        made += 1
    return made


def split_sentences(text: str) -> list[str]:
    """문장 끝 부호(마침표·느낌표·물음표·말줄임표) 뒤 공백과 줄바꿈에서 나눈다."""
    return [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]


def _spread(values: Sequence[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "min": min(values),
        "median": float(statistics.median(values)),
        "mean": float(statistics.fmean(values)),
        "max": max(values),
    }


def length_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """결과 줄의 길이 집계(글은 내지 않는다). 글자·문장 분포는 비지 않은 글만 본다."""
    ok = [r for r in rows if r.get("status") == "ok"]
    texts = [str(r["text"]) for r in ok if r["text"]]
    return {
        "rows": len(rows),
        "ok": len(ok),
        "failed": len(rows) - len(ok),
        "empty": sum(1 for r in ok if not r["text"]),
        "truncated": sum(1 for r in ok if r["truncated"]),
        "rawOverCap": sum(1 for r in ok if (r["rawChars"] or 0) > IMPRESSION_TEXT_MAX),
        "chars": _spread([len(t) for t in texts]),
        "sentences": _spread([len(split_sentences(t)) for t in texts]),
    }


# ---------------------------------------------------------------- 판정


class SentenceVerdict(BaseModel):
    index: int
    reason: str
    label: Label


class ImpressionVerdict(BaseModel):
    sentences: list[SentenceVerdict]


@dataclass(frozen=True)
class JudgeItem:
    item_id: str
    author_setting: str
    episode_lines: tuple[str, ...]
    fact_lines: tuple[str, ...]
    sentences: tuple[str, ...]
    # 대조군의 문장별 정답. 측정 문항에는 없다.
    gold: tuple[Label, ...] | None = None


def _labels(values: Sequence[Any], where: str) -> tuple[Label, ...]:
    unknown = [v for v in values if v not in LABELS]
    if unknown:
        raise SystemExit(f"{where}: 모르는 판정 값 {unknown} (고를 수 있는 값 {list(LABELS)})")
    return tuple(cast(Label, v) for v in values)


def load_items(path: Path) -> list[JudgeItem]:
    """판정 문항 파일(JSON 목록). 문장은 `sentences` 로 주거나 `impression` 글을 주면 나눈다. 정답 `gold` 는 문장 수와 같아야 한다."""
    items: list[JudgeItem] = []
    for entry in json.loads(path.read_text(encoding="utf-8")):
        sentences = tuple(entry["sentences"]) if "sentences" in entry else tuple(split_sentences(entry["impression"]))
        gold = None
        if entry.get("gold") is not None:
            gold = _labels(entry["gold"], str(entry["id"]))
            if len(gold) != len(sentences):
                raise SystemExit(f"{entry['id']}: 정답 {len(gold)} 개와 문장 {len(sentences)} 개가 다르다")
        items.append(
            JudgeItem(
                item_id=str(entry["id"]),
                author_setting=str(entry["authorSetting"]),
                episode_lines=tuple(entry["episodeLines"]),
                fact_lines=tuple(entry["factLines"]),
                sentences=sentences,
                gold=gold,
            )
        )
    return items


def items_from_results(
    rows: Sequence[Mapping[str, Any]], inputs: Sequence[ImpressionInput], settings_by_room: Mapping[str, str]
) -> list[JudgeItem]:
    """생성 결과(글이 있는 줄만)를 그 입력 줄·방의 작가 설정과 이어 판정 문항으로."""
    by_key = {item.key: item for item in inputs}
    items: list[JudgeItem] = []
    for row in rows:
        if row.get("status") != "ok" or not row.get("text"):
            continue
        item = by_key[str(row["key"])]
        if item.room_id not in settings_by_room:
            raise SystemExit(f"방 {item.room_id} 의 작가 설정이 없다")
        items.append(
            JudgeItem(
                item_id=item.key,
                author_setting=settings_by_room[item.room_id],
                episode_lines=item.episode_lines,
                fact_lines=item.fact_lines,
                sentences=tuple(split_sentences(str(row["text"]))),
            )
        )
    return items


def check_template(template: str) -> None:
    used = {name for _, name, _, _ in Formatter().parse(template) if name}
    if used != TEMPLATE_FIELDS:
        raise SystemExit(f"판정 틀의 플레이스홀더는 정확히 {sorted(TEMPLATE_FIELDS)} 여야 한다 — 지금 {sorted(used)}")


def render_judge_prompt(template: str, item: JudgeItem) -> str:
    check_template(template)
    return template.format(
        author_setting=item.author_setting,
        episode_lines="\n".join(item.episode_lines) or EMPTY_LINES,
        fact_lines="\n".join(item.fact_lines) or EMPTY_LINES,
        sentences="\n".join(f"[{i}] {s}" for i, s in enumerate(item.sentences, start=1)),
    )


def parse_vote(verdict: ImpressionVerdict, n: int) -> tuple[list[Label], list[str]] | None:
    """문장 번호가 1~n 을 정확히 한 번씩 덮으면 (번호 순 판정, 이유), 아니면 None."""
    by_index = {v.index: v for v in verdict.sentences}
    if len(verdict.sentences) != n or set(by_index) != set(range(1, n + 1)):
        return None
    ordered = [by_index[i] for i in range(1, n + 1)]
    return [v.label for v in ordered], [v.reason for v in ordered]


Judge = Callable[[str], Awaitable[ImpressionVerdict]]
Vote = dict[str, list[Any]] | None


async def _one_vote(judge: Judge, prompt: str, n: int, *, retries: int, pause: float) -> Vote:
    """한 표. 실패·꼴이 틀린 답이면 같은 입력으로 `retries` 번까지 다시 묻고, 그래도 없으면 불능 표(None)."""
    for _ in range(retries):
        try:
            verdict = await judge(prompt)
        except BudgetExceededError:
            raise
        except Exception:  # 판정 실패·파싱 실패·거부 — 같은 입력으로 다시
            await asyncio.sleep(pause)
            continue
        parsed = parse_vote(verdict, n)
        if parsed is not None:
            return {"labels": list(parsed[0]), "reasons": parsed[1]}
    return None


def _majority(values: Sequence[str | None]) -> str | None:
    value, count = Counter(values).most_common(1)[0]
    return value if value is not None and count * 2 > len(values) else None


async def judge_item(
    judge: Judge,
    prompt: str,
    n: int,
    *,
    concurrent: bool = True,
    retries: int = JUDGE_RETRIES,
    pause: float = RETRY_PAUSE_SECONDS,
) -> tuple[list[Label | None], list[Vote]]:
    """문장마다 다수결 판정과 받은 표 목록. 첫 두 표가 모든 문장에서 같으면 셋째를 부르지 않는다(셋째가 무엇이든 과반이 그대로다).
    한 문장이라도 갈리거나 한 표가 불능이면 셋째를 받는다."""

    async def votes_of(count: int) -> list[Vote]:
        if concurrent:
            return await _gather_or_cancel(
                [_one_vote(judge, prompt, n, retries=retries, pause=pause) for _ in range(count)]
            )
        return [await _one_vote(judge, prompt, n, retries=retries, pause=pause) for _ in range(count)]

    votes = await votes_of(JUDGE_FIRST_VOTES)
    if any(v is None for v in votes) or len({tuple(v["labels"]) for v in votes if v is not None}) > 1:
        votes += await votes_of(JUDGE_MAX_VOTES - JUDGE_FIRST_VOTES)
    decided: list[Label | None] = []
    for index in range(n):
        value = _majority([None if v is None else v["labels"][index] for v in votes])
        decided.append(cast(Label | None, value))
    return decided, votes


async def judge_items(
    items: Sequence[JudgeItem],
    judge: Judge,
    *,
    template: str,
    out_path: Path,
    concurrency: int = 4,
) -> int:
    """아직 결과가 없는 문항(같은 프롬프트의 줄이 없는 것)을 판정해 끝나는 대로 결과 파일에 한 줄씩. 동시에 `concurrency` 문항."""
    check_template(template)
    done = {(r["itemId"], r["promptSha"]) for r in read_rows(out_path)}
    pending = [
        (item, prompt)
        for item in items
        if (item.item_id, sha256_text(prompt := render_judge_prompt(template, item))) not in done
    ]
    limit = asyncio.Semaphore(concurrency)

    async def one(item: JudgeItem, prompt: str) -> None:
        async with limit:
            decided, votes = await judge_item(judge, prompt, len(item.sentences))
        _append(
            out_path,
            {
                "itemId": item.item_id,
                "promptSha": sha256_text(prompt),
                "sentences": list(item.sentences),
                "gold": None if item.gold is None else list(item.gold),
                "decided": decided,
                "votes": votes,
            },
        )

    await _gather_or_cancel([one(item, prompt) for item, prompt in pending])
    return len(pending)


def _accuracy(pairs: Sequence[tuple[str, str | None]], project: Callable[[str], Any]) -> float:
    return sum(1 for gold, got in pairs if got is not None and project(gold) == project(got)) / len(pairs)


def judge_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """판정 줄 집계(문장은 내지 않는다). 비율은 판정이 난 문장 중이다. 정답이 붙은 줄이 있으면 대조군 관문도 낸다."""
    decided = [label for r in rows for label in r["decided"]]
    known = [label for label in decided if label is not None]
    counts = Counter(known)
    total = len(known) or 1
    report: dict[str, Any] = {
        "items": len(rows),
        "sentences": len(decided),
        "inability": len(decided) - len(known),
        "counts": {label: counts.get(label, 0) for label in LABELS},
        "rates": {
            "unsupported": counts["unsupported"] / total,
            "conflict": counts["conflict"] / total,
            "flagged": (counts["unsupported"] + counts["conflict"]) / total,
        },
        "itemsWithFlag": sum(1 for r in rows if any(label in ("unsupported", "conflict") for label in r["decided"])),
        "itemsWithInability": sum(1 for r in rows if any(label is None for label in r["decided"])),
    }
    pairs = [(g, d) for r in rows if r.get("gold") is not None for g, d in zip(r["gold"], r["decided"], strict=True)]
    if pairs:
        accuracy = _accuracy(pairs, lambda label: label)
        flagged = _accuracy(pairs, lambda label: label != "supported")
        conflict = _accuracy(pairs, lambda label: label == "conflict")
        inability = sum(1 for _, d in pairs if d is None)
        per_label = {
            label: _accuracy(subset, lambda value: value) if (subset := [p for p in pairs if p[0] == label]) else None
            for label in LABELS
        }
        report["gate"] = {
            "threshold": CONTROL_ACCURACY_MIN,
            "sentences": len(pairs),
            "accuracy": accuracy,
            "flaggedAccuracy": flagged,
            "conflictAccuracy": conflict,
            "recallByGold": per_label,
            "inability": inability,
            "pass": min(accuracy, flagged, conflict) >= CONTROL_ACCURACY_MIN and inability == 0,
        }
    return report


class OpusImpressionJudge:
    """Anthropic 직결 구조화 호출 판정자(깊이 low). 사고를 끌 수 없는 모델이면 사고 칸을 싣지 않는다 — 측정 하네스 판정자와 같은
    규칙(`JUDGE_MODELS`)이다. 호출마다 견적만큼 원장 자리를 잡고 응답 토큰으로 원장에 한 줄 남긴다."""

    def __init__(
        self, api_key: str, ledger: Ledger, *, stage: str, call_estimate_usd: float, model: str = JUDGE_MODEL
    ) -> None:
        if model not in JUDGE_MODELS:
            raise SystemExit(f"판정자 모델은 {sorted(JUDGE_MODELS)} 중 하나다: {model}")
        if not api_key:
            raise SystemExit("판정자는 Anthropic 키가 있어야 한다")
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._thinking = JUDGE_MODELS[model][0]
        self._ledger = ledger
        self._stage = stage
        self._estimate = call_estimate_usd

    async def __call__(self, prompt: str) -> ImpressionVerdict:
        from api.llm.claude_messages import message_usage, parse_structured, structured_output_config

        output_config: Any = {**structured_output_config(ImpressionVerdict), "effort": "low"}
        thinking: Any = {} if self._thinking is None else {"thinking": self._thinking}
        with self._ledger.reserve(self._estimate):
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=JUDGE_MAX_TOKENS,
                **thinking,
                output_config=output_config,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = message_usage(message)
            self._ledger.append(
                stage=self._stage,
                call_site=JUDGE_CALL_SITE,
                model=self._model,
                input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                cached_tokens=int(getattr(usage, "cached_content_token_count", 0) or 0),
                cache_write_tokens=int(getattr(usage, "cache_write_token_count", 0) or 0),
                output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
                thoughts_tokens=int(getattr(usage, "thoughts_token_count", 0) or 0),
            )
        return parse_structured(message, ImpressionVerdict, "anthropic", "Anthropic")


def judge_estimate(
    items: Sequence[JudgeItem],
    template: str,
    *,
    model: str,
    tokens_per_char: float,
    output_tokens: int,
    done: set[tuple[str, str]],
) -> dict[str, Any]:
    """아직 결과가 없는 문항의 견적 — 문항마다 최대 표 수(3)를 다 부른다고 본다(상한용). 실패 재시도는 넣지 않는다."""
    pending = [
        prompt
        for item in items
        if (item.item_id, sha256_text(prompt := render_judge_prompt(template, item))) not in done
    ]
    per_call = [
        cost_usd(
            model,
            input_tokens=round(len(p) * tokens_per_char),
            cached_tokens=0,
            cache_write_tokens=0,
            output_tokens=output_tokens,
            thoughts_tokens=0,
        )
        for p in pending
    ]
    return {
        "items": len(pending),
        "maxCalls": len(pending) * JUDGE_MAX_VOTES,
        "expectedCallsIfAgree": len(pending) * JUDGE_FIRST_VOTES,
        "perCallMaxUsd": max(per_call, default=0.0),
        "ceilingUsd": sum(per_call) * JUDGE_MAX_VOTES,
        "agreeUsd": sum(per_call) * JUDGE_FIRST_VOTES,
    }
