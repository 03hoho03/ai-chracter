"""가짜 어댑터 — 명세에서 정답 출력을 만들어 돌려준다. 모델을 부르지 않는다. 모드가 둘이다.

- CI 모드(기본): 정답 일부만 낸다 — 사실의 시작 서술(`onset`)은 늘 거짓, 범위는 불변 여부로만(불변 속성은 작품 전체, 그 밖은
  이 장면부터), 사건의 사용은 빈 목록이다. 일부러 틀린 출력(`Faults`)을 섞어 지표가 그 틀림을 세는지 본다.
- 오라클 모드(`oracle=True`): 명세 정답의 모든 칸을 슬롯 출력 스키마 그대로 낸다 — 위 셋도 명세 값(`onset`·`effective_scope`·
  `uses`)으로. 추출이 정답과 똑같다고 놓고 세트를 실제 확정·검사 경로로 돌려, 막히거나 안 막힌 것이 세트 쪽 결함인지 보는
  실행이다. 틀린 출력을 섞지 않는다. 명세가 싣지 않는 칸 하나는 늘 비운다 — 사건의 말로만 언급된 인물(`mentioned`)은 규칙이
  읽지 않고 매처도 견주지 않는다.

근거 인용은 두 모드 모두 원고에서 정답 문단의 글 전체를 그대로 옮긴다 — 문안의 `[번호] 글` 줄과 같은 글이라 인용 검증과 차단 전
근거 재확인을 통과한다. 사건 인용은 그 사건의 첫 문단이다(앱은 인용 문단이 사건 문단 안이기를 요구한다).

원고 문단으로 어느 화인지 알아본다. 문안은 원고 값과, 표지를 찾는 데 쓰는 앞 화 사건 목록·플레이 사실 목록을 렌더한다 — 회상
관계의 대상(`P1` …)과 플레이 차이의 행(`P1` …)은 그 화 문안에 실린 목록에서 찾고, 원작 차이의 표지는 명세의 원작 글 차례에서
온다. 그래서 심기가 앞 화·플레이 행을 명세대로 놓지 못하면 표지를 못 찾아 그 관계·차이를 내지 않는다.

문안 원천은 등록부의 추출 슬롯 채널을 모두 낸다 — 확정 입구가 배정된 체인에 채널이 있는지 먼저 보므로, 슬롯이 늘어도 여기를 고치지 않고 확정이 받힌다. 출력 꼴을 아는 슬롯은 사건·
사실·지식이다 — 새 추출 슬롯이 등록부에 들어오면 그 슬롯의 출력 만들기를 여기 더해야 `slots` 가 넓어진다. 더하지 않으면 슬롯을
좁히지 않은 확정(라벨용 추출)이 그 슬롯 작업에서 실패한다. 호출 기록 원소는 실제 어댑터와 같은 칸을 갖는다. CI 모드의 모델은
단가표에 있는 id 라 원장이 실제 호출처럼 원가를 친다. 오라클 모드의 모델은 `oracle` 이다 — 보고서의 실제 모델 칸에 실측 모델 id
가 찍히지 않고, 비교 명령이 결과 묶음에서 오라클 실행을 알아보는 표지가 된다(단가표에 없어 원가는 0 이다).

모호 후보 판정도 같은 해석기로 온다. 문안 원천은 판정 채널도 내고, 판정에는 판단 없이 늘 "모르겠다"를 답한다 — 그러면 후보
경고만 남아(앎 출처 불명은 버려진다) 판정 실패 경고가 측정 결과에 섞이지 않는다. 명세는 판정 정답을 싣지 않는다."""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.prompt import PromptSection
from api.novel_bible.adapters.table import OPERATION_CALL_SITES
from api.novel_bible.core.contracts import AdapterCallError, AdapterCapabilities, AdapterResolver, PromptSource
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import OperationKey, SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.rules.judge import CHANNEL as JUDGE_CHANNEL

from novel_bible_eval.spec import ChapterSpec, EvalSet, NovelSpec, PlayRow

T = TypeVar("T", bound=BaseModel)
# 오라클 모드 호출 기록의 모델 칸.
ORACLE_MODEL = "oracle"
_LINE = re.compile(r"^\[\d+\] (.*)$", re.MULTILINE)
_NOT_IN_MANUSCRIPT = "원고에 없는 구절"
# 사건 슬롯 문안의 앞 화 사건 한 줄(`P1. 3화 — 요지`)과 사실 슬롯 문안의 플레이 사실 한 줄(`P1. 주어 · 속성: 값`).
_PRIOR = re.compile(r"^(P\d+)\. (\d+)화 — (.*)$", re.MULTILINE)
_PLAY = re.compile(r"^(P\d+)\. (.*)$", re.MULTILINE)


@dataclass(frozen=True)
class _Chapter:
    """가짜 해석기가 알아본 화 — 소설 키, 표지(기본 화는 화 번호 글자, 탐침은 탐침 키), 그 화 명세, 그 소설 명세."""

    novel: str
    label: str
    spec: ChapterSpec
    book: NovelSpec


@dataclass(frozen=True)
class Faults:
    """일부러 틀릴 곳. 화는 (소설 키, 표지) — 기본 화의 표지는 화 번호 글자, 탐침은 탐침 키. 사건·사실·지식은 그 화 정답의
    차례(0부터)."""

    omit: frozenset[tuple[str, str, int]] = frozenset()  # 그 사건을 내지 않는다
    misquote: frozenset[tuple[str, str, int]] = frozenset()  # 그 사건의 인용을 원고에 없는 구절로 낸다
    schema_failure: frozenset[tuple[str, str]] = frozenset()  # 그 화의 첫 호출을 스키마 불일치로 실패시킨다
    flip_immutable: frozenset[tuple[str, str, int]] = frozenset()  # 그 사실의 불변 표시를 뒤집어 낸다
    extra_fact: frozenset[tuple[str, str]] = frozenset()  # 그 화에 심지 않은 사실 하나를 더 낸다
    swap_knower: frozenset[tuple[str, str, int]] = frozenset()  # 그 지식의 앎 주체와 명제 주어를 맞바꿔 낸다


def _events(at: _Chapter, prompt: str, faults: Faults, oracle: bool) -> dict[str, Any]:
    """회상 관계는 대상 사건의 (화 번호, 요지)가 문안의 앞 화 사건 목록에 있을 때만 그 표지로 낸다. 사용은 오라클 모드에서만
    명세 그대로 낸다."""
    novel, label, chapter = at.novel, at.label, at.spec
    prior = {(int(ordinal), summary): target for target, ordinal, summary in _PRIOR.findall(prompt)}
    events, relations = [], []
    for index, event in enumerate(chapter.events):
        if (novel, label, index) in faults.omit:
            continue
        first = event.paragraphs[0]
        quote = _NOT_IN_MANUSCRIPT if (novel, label, index) in faults.misquote else chapter.paragraphs[first - 1]
        events.append(
            {
                "key": f"e{index}", "summary": event.summary, "paragraphs": event.paragraphs,
                "actuality": event.actuality, "present": event.present, "mentioned": [],
                "uses": [use.model_dump() for use in event.uses] if oracle else [],
                "quote": {"paragraph": first, "text": quote},
            }
        )
        if (relation := event.relation) is not None:
            aimed = at.book.chapters[relation.chapter - 1].events[relation.event - 1]
            if (target := prior.get((relation.chapter, aimed.summary))) is not None:
                relations.append({"event": f"e{index}", "relation": relation.kind, "target": target})
    return {"events": events, "relations": relations}


def _fact(
    subject: str, subject_kind: str, kind: str, attribute: str | None, value: str, holds: bool, immutable: bool,
    paragraph: int, chapter: ChapterSpec, *, onset: bool = False, scope: str | None = None,
) -> dict[str, Any]:
    """`scope` 가 없으면 불변 여부로 정한다(불변 속성은 작품 전체, 그 밖은 이 장면부터)."""
    return {
        "subject": subject, "subject_kind": subject_kind, "kind": kind, "attribute": attribute, "value": value,
        "holds": holds, "immutable": immutable, "onset": onset,
        "scope": scope or ("work" if immutable else "from_here"),
        "quote": {"paragraph": paragraph, "text": chapter.paragraphs[paragraph - 1]},
        "source_difference": None, "play_difference": None,
    }


def _play_line(row: PlayRow) -> str:
    """사실 슬롯이 플레이 사실 한 줄에 싣는 본문(표지·꼬리 뺌)과 같은 꼴."""
    if row.object is not None:
        return f"{row.subject} → {row.object}: {row.value}"
    return f"{row.subject} · {row.attribute}: {row.value}"


def _facts(at: _Chapter, prompt: str, faults: Faults, oracle: bool) -> dict[str, Any]:
    """정답마다 첫 허용 표기로 낸다. 원작 차이는 명세의 표지·구절 그대로, 플레이 차이는 그 행의 줄이 문안에 있을 때만 그 표지로
    낸다. 더하는 사실은 첫 문단을 인용한, 정답에 없는 소지다. 시작 서술·범위는 오라클 모드에서만 명세 값이다."""
    novel, label, chapter = at.novel, at.label, at.spec
    shown = {body: ref for ref, body in _PLAY.findall(prompt)}
    facts = []
    for index, fact in enumerate(chapter.facts):
        out = _fact(
            fact.subject, fact.subject_kind, fact.kind, fact.attribute, fact.values[0], fact.holds,
            fact.immutable != ((novel, label, index) in faults.flip_immutable), fact.paragraph, chapter,
            onset=oracle and fact.onset, scope=fact.effective_scope if oracle else None,
        )
        if (source := fact.source_difference) is not None:
            out["source_difference"] = {"label": source.label, "quote": source.quote}
        if fact.play_difference is not None:
            line = _play_line(at.book.play[fact.play_difference - 1])
            ref = next((ref for body, ref in shown.items() if body.startswith(line)), None)
            out["play_difference"] = None if ref is None else {"ref": ref}
        facts.append(out)
    if (novel, label) in faults.extra_fact:
        facts.append(_fact("합성 여분 인물", "character", "possession", None, "합성 여분 물건", True, False, 1, chapter))
    return {"facts": facts}


def _knowledge(at: _Chapter, prompt: str, faults: Faults, oracle: bool) -> dict[str, Any]:
    """정답마다 첫 허용 표기와 명제 주어의 종류로 내고 정답 문단 전체를 인용한다."""
    novel, label, chapter = at.novel, at.label, at.spec
    items = []
    for index, known in enumerate(chapter.knowledge):
        knower, subject = known.knower, known.subject
        if (novel, label, index) in faults.swap_knower:
            knower, subject = subject, knower
        items.append(
            {
                "knower": knower, "kind": known.kind,
                "about": {
                    "subject": subject, "subject_kind": known.subject_kind, "kind": known.fact_kind,
                    "attribute": known.attribute, "value": known.values[0], "holds": known.holds,
                },
                "quote": {"paragraph": known.paragraph, "text": chapter.paragraphs[known.paragraph - 1]},
            }
        )
    return {"items": items}


_OUTPUTS: dict[OperationKey, Callable[[_Chapter, str, Faults, bool], dict[str, Any]]] = {
    "events.extract": _events, "facts.extract": _facts, "knowledge.extract": _knowledge,
}
# 원고 값 말고 문안에 싣는 값 — 가짜 해석기가 표지를 찾는 목록이다. 조건부라 그 값이 없는 채널·화에서는 섹션째 빠진다.
_LISTED_VALUES = ("prior_events", "play_facts")
_JUDGE_ANSWER = {"verdict": "unsure", "reason": "합성 판정 — 가짜 해석기는 판단하지 않는다."}


class FakeLLM:
    id = "fake"

    def __init__(
        self, eval_set: EvalSet, *, faults: Faults | None = None, oracle: bool = False,
        model: str | None = None, prompt_tokens: int = 1_000, output_tokens: int = 200,
    ) -> None:
        if oracle and faults is not None:
            raise ValueError("오라클 모드는 명세 정답을 그대로 낸다 — 틀린 출력을 섞지 않는다")
        self._chapters: dict[tuple[str, ...], _Chapter] = {}
        for novel in eval_set.novels:
            for ordinal, chapter in enumerate(novel.chapters, start=1):
                self._chapters[tuple(chapter.paragraphs)] = _Chapter(novel.key, str(ordinal), chapter, novel)
            for probe in novel.probes:
                self._chapters[tuple(probe.chapter.paragraphs)] = _Chapter(novel.key, probe.key, probe.chapter, novel)
        self._faults = faults or Faults()
        self._oracle = oracle
        if model is None:
            model = ORACLE_MODEL if oracle else "gemini-3.5-flash-lite"
        self._usage = {"backend": "fake", "model": model, "promptTokens": prompt_tokens, "outputTokens": output_tokens}
        self._failed: set[tuple[str, str]] = set()
        self._prompt_set_id = uuid.uuid4()
        self.calls = 0
        self.capabilities = AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=1_000_000)

    @property
    def slots(self) -> frozenset[SlotId]:
        """출력을 만들 줄 아는, 등록부에 있는 슬롯."""
        return frozenset(slot_id for slot_id, slot in REGISTRY.extracting.items() if slot.operation in _OUTPUTS)

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        sections = []
        bodies = [("instruction", "합성 지시문", False), ("body", "{manuscript}", False)]
        bodies += [(name, f"{{{name}}}", True) for name in _LISTED_VALUES]
        for channel in sorted({slot.channel for slot in REGISTRY.extracting.values()}):
            for order, (slot, body, conditional) in enumerate(bodies):
                sections.append(
                    PromptSection(
                        prompt_set_id=self._prompt_set_id, channel=channel, scope="both", slot=slot, variant="",
                        body=body, conditional=conditional, order=order,
                    )
                )
        for order, (slot, body) in enumerate((("instruction", "합성 판정 지시문"), ("body", "{candidate}"))):
            sections.append(
                PromptSection(
                    prompt_set_id=self._prompt_set_id, channel=JUDGE_CHANNEL, scope="both", slot=slot, variant="",
                    body=body, conditional=False, order=order,
                )
            )
        return PromptSource(prompt_set_id=self._prompt_set_id, sections=sections)

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        self.calls += 1
        records.append(
            {"callSite": OPERATION_CALL_SITES[stage], **self._usage, "durationMs": 0, "stage": stage, "failure": None}
        )
        if stage == "conflicts.judge":
            return schema.model_validate(_JUDGE_ANSWER)
        at = self._chapters[tuple(_LINE.findall(prompt.prompt))]
        if (at.novel, at.label) in self._faults.schema_failure and (at.novel, at.label) not in self._failed:
            self._failed.add((at.novel, at.label))
            raise AdapterCallError("schema_invalid", retryable=True)
        return schema.model_validate(_OUTPUTS[stage](at, prompt.prompt, self._faults, self._oracle))

    def resolver(self) -> AdapterResolver:
        return lambda operation: self
