"""CI 용 가짜 어댑터 — 명세에서 정답 출력을 만들어 돌려주고, 일부러 틀린 출력을 섞을 수 있다. 모델을 부르지 않는다.

원고 문단으로 어느 화인지 알아본다(문안은 원고 값 하나만 렌더한다). 출력 꼴을 아는 슬롯은 사건뿐이다 — 사실·지식 슬롯이
등록부에 들어오면 그 슬롯의 출력 만들기를 여기 더하고 `slots` 가 넓어진다. 호출 기록 원소는 실제 어댑터와 같은 칸을 갖고 모델은
단가표에 있는 id 라, 원장이 실제 호출처럼 원가를 친다."""

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

from novel_bible_eval.spec import ChapterSpec, EvalSet

T = TypeVar("T", bound=BaseModel)
_LINE = re.compile(r"^\[\d+\] (.*)$", re.MULTILINE)
_NOT_IN_MANUSCRIPT = "원고에 없는 구절"


@dataclass(frozen=True)
class Faults:
    """일부러 틀릴 곳. 화는 (소설 키, 표지) — 기본 화의 표지는 화 번호 글자, 탐침은 탐침 키. 사건은 그 화 정답의 차례(0부터)."""

    omit: frozenset[tuple[str, str, int]] = frozenset()  # 그 사건을 내지 않는다
    misquote: frozenset[tuple[str, str, int]] = frozenset()  # 그 사건의 인용을 원고에 없는 구절로 낸다
    schema_failure: frozenset[tuple[str, str]] = frozenset()  # 그 화의 첫 호출을 스키마 불일치로 실패시킨다


def _events(novel: str, label: str, chapter: ChapterSpec, faults: Faults) -> dict[str, Any]:
    events = []
    for index, event in enumerate(chapter.events):
        if (novel, label, index) in faults.omit:
            continue
        first = event.paragraphs[0]
        quote = _NOT_IN_MANUSCRIPT if (novel, label, index) in faults.misquote else chapter.paragraphs[first - 1]
        events.append(
            {
                "key": f"e{index}", "summary": event.summary, "paragraphs": event.paragraphs,
                "actuality": event.actuality, "present": event.present, "mentioned": [], "uses": [],
                "quote": {"paragraph": first, "text": quote},
            }
        )
    return {"events": events, "relations": []}


_OUTPUTS: dict[OperationKey, Callable[[str, str, ChapterSpec, Faults], dict[str, Any]]] = {"events.extract": _events}


class FakeLLM:
    id = "fake"

    def __init__(
        self, eval_set: EvalSet, *, faults: Faults | None = None, model: str = "gemini-3.5-flash-lite",
        prompt_tokens: int = 1_000, output_tokens: int = 200,
    ) -> None:
        self._chapters: dict[tuple[str, ...], tuple[str, str, ChapterSpec]] = {}
        for novel in eval_set.novels:
            for ordinal, chapter in enumerate(novel.chapters, start=1):
                self._chapters[tuple(chapter.paragraphs)] = (novel.key, str(ordinal), chapter)
            for probe in novel.probes:
                self._chapters[tuple(probe.chapter.paragraphs)] = (novel.key, probe.key, probe.chapter)
        self._faults = faults or Faults()
        self._usage = {"model": model, "promptTokens": prompt_tokens, "outputTokens": output_tokens}
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
        for slot_id in self.slots:
            channel = REGISTRY.extracting[slot_id].channel
            for order, (slot, body) in enumerate((("instruction", "합성 지시문"), ("body", "{manuscript}"))):
                sections.append(
                    PromptSection(
                        prompt_set_id=self._prompt_set_id, channel=channel, scope="both", slot=slot, variant="",
                        body=body, conditional=False, order=order,
                    )
                )
        return PromptSource(prompt_set_id=self._prompt_set_id, sections=sections)

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        novel, label, chapter = self._chapters[tuple(_LINE.findall(prompt.prompt))]
        self.calls += 1
        records.append(
            {"callSite": OPERATION_CALL_SITES[stage], **self._usage, "durationMs": 0, "stage": stage, "failure": None}
        )
        if (novel, label) in self._faults.schema_failure and (novel, label) not in self._failed:
            self._failed.add((novel, label))
            raise AdapterCallError("schema_invalid", retryable=True)
        return schema.model_validate(_OUTPUTS[stage](novel, label, chapter, self._faults))

    def resolver(self) -> AdapterResolver:
        return lambda operation: self
