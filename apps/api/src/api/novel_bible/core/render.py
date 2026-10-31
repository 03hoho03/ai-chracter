"""novel 레인 정본 기억 채널의 렌더 — `instruction` 슬롯은 값 없이 지시문으로, 나머지는 값으로 채워 본문으로.

소설 빌더의 렌더와 같은 꼴이지만 그 비공개 함수와 필수 슬롯 표를 쓰지 않는다 — 쓰려면 생성 경로 모듈에 정본 기억 채널 줄을
더해야 하고, 생성 경로는 정본 기억을 몰라야 한다. 확정 입구가 작업을 만들기 전에 배정된 체인에 채널이 있는지 보는 검사도 여기
둔다."""

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptRenderError, render_prompt_channel, select_sections_for_render
from api.novel_bible.core.contracts import AdapterCallError, AdapterResolver, PromptSource, Registry
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import SlotId

_INSTRUCTION_SLOT = "instruction"


def render(source: PromptSource, *, channel: str, scope: str, values: dict[str, str]) -> RenderedPrompt:
    """채널에 지시문 섹션이 없거나 렌더 결과가 비면 `PromptRenderError`(체인에 그 채널이 게시되지 않았다)."""
    sections = [section for section in source.sections if section.channel == channel]
    present = {section.slot for section in select_sections_for_render(sections, channel=channel, scope=scope)}
    if _INSTRUCTION_SLOT not in present:
        raise PromptRenderError(f"channel={channel!r} scope={scope!r} 지시문 섹션이 없다")
    instruction = render_prompt_channel(
        [s for s in sections if s.slot == _INSTRUCTION_SLOT], channel=channel, scope=scope, values={}
    )
    prompt = render_prompt_channel(
        [s for s in sections if s.slot != _INSTRUCTION_SLOT], channel=channel, scope=scope, values=values
    )
    if not instruction.strip() or not prompt.strip():
        raise PromptRenderError(f"channel={channel!r} scope={scope!r} 렌더 결과가 비었다")
    return RenderedPrompt(system_instruction=instruction, prompt=prompt, prompt_set_id=source.prompt_set_id)


async def verify_prompt_chains(
    session: AsyncSession, registry: Registry, resolver: AdapterResolver, *, slots: frozenset[SlotId] | None = None
) -> list[str]:
    """확정이 만들 작업마다(등록부의 추출 슬롯, `slots` 가 있으면 그중 든 것) 그 연산에 배정된 어댑터의 문안에 슬롯 채널의 지시문
    섹션이 있는지 본다. 없으면 `어댑터 id:채널` 을 돌려준다 — 확정 입구가 작업을 만들기 전에 거절해, 처리될 수 없는 확정이 쌓이지
    않게 한다. scope 는 가르지 않는다(작업 렌더가 scope 까지 다시 본다)."""
    missing: list[str] = []
    for slot_id, slot in registry.extracting.items():
        if slots is not None and slot_id not in slots:
            continue
        adapter = resolver(slot.operation)
        try:
            source = await adapter.prompt_source(session)
        except AdapterCallError:
            missing.append(f"{adapter.id}:{slot.channel}")
            continue
        if not any(s.channel == slot.channel and s.slot == _INSTRUCTION_SLOT for s in source.sections):
            missing.append(f"{adapter.id}:{slot.channel}")
    return missing
