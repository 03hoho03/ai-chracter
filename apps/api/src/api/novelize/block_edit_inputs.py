"""여러 문단 수정 호출의 입력 — 문맥 문단(장면 있는 화는 그 장면, 없으면 화 전체)과 입력 견적, 실행 때의 프롬프트, 그리고 묶음
재검사의 프롬프트.

읽기만 하고 쓰지 않는다. 요청 라우트가 차감 전에 견적을 보고, 작업 실행이 짧은 세션 하나에서 프롬프트를 만든 뒤 세션을 닫고 모델을
부른다. 문맥은 작업의 기준 개정에서 읽는다(요청 때 지금 개정 = 기준 개정이다)."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_routing import RouteSource
from api.db.models.novel import Novel, NovelChapterRevision, NovelJob
from api.novelize.block_edits import BlockEdit, RecheckPlan, context_positions, recheck_context_positions
from api.llm.chat_models import ChatModelId, PromptSetModelId
from api.novelize.inputs import _version_id, load_novel_prompt_source, load_work_setting, resolve_novel_call_route
from api.novelize.prompts import (
    NovelizePrompt,
    build_novelize_revise_blocks_prompt,
    build_novelize_revise_recheck_prompt,
)
from api.novelize.scenes import revision_scenes
from api.novelize.text import split_paragraphs


class InputTooLongError(Exception):
    """입력 견적(글자)이 상한을 넘는다."""

    def __init__(self, estimated: int, cap: int) -> None:
        super().__init__(f"입력 견적 {estimated}자가 상한 {cap}자를 넘는다")
        self.estimated = estimated
        self.cap = cap


def context_lines(paragraphs: list[str], positions: list[int]) -> str:
    """문맥 문단을 화 전체에서 센 1부터의 번호 `[n] ` 과 함께 빈 줄로 잇는다(옛 문단 수정의 본문 줄과 같은 꼴)."""
    return "\n\n".join(f"[{index + 1}] {paragraphs[index]}" for index in positions)


async def input_estimate(
    db: AsyncSession, novel: Novel, paragraphs: list[str], positions: list[int], instruction: str
) -> int:
    """모델에 보낼 글의 글자 수 견적 — 문맥 문단 + 작품 설정 + 설정 노트 + 지시. 문안·번호 머리는 세지 않는다(모든 요청에 비슷하게
    붙는 몫이라 상한에서 떼어 둔다)."""
    work_setting = await load_work_setting(db, novel, await _version_id(db, novel))
    return (
        sum(len(paragraphs[index]) for index in positions)
        + len(work_setting)
        + len(novel.setting_notes)
        + len(instruction)
    )


@dataclass(frozen=True)
class BlockEditInput:
    prompt: NovelizePrompt
    edit: BlockEdit
    # 배정 표가 고른 부를 모델(`inputs.NovelCallRoute.call_model`). 행이 쓰이지 않았으면 None 이라 호출 문맥에 싣지 않는다.
    call_model: PromptSetModelId | None = None
    # 그 배정 해석의 출처(`inputs.NovelCallRoute.source`) — 호출 기록에만 싣는다.
    route_source: RouteSource | None = None


async def build_block_edit_input(db: AsyncSession, job: NovelJob, novel: Novel) -> BlockEditInput:
    """여러 문단 수정 작업의 입력. 기준 개정을 문단으로 나눠 대상 장면의 문단(장면 없는 화는 화 전체)을 문맥으로 싣고, 대상 문단
    번호를 함께 싣는다. 문맥에는 대상 문단이 늘 든다 — 요청 뒤 장면 경계 행이 바뀌었어도 고칠 문단이 빠진 채 부르지 않는다. 방이
    지워졌어도 작품 설정은 원작 발행본에서 읽는다(옛 문단 수정과 같다). 문안 체인과 부를 모델은 배정 표의 여러 문단 수정
    칸(`novel_revise_blocks`)대로다 — 호출 위치는 문단 수정과 같아도 칸은 따로다."""
    assert job.block_edit is not None  # 이 함수는 패치 작업에서만 부른다
    edit = BlockEdit.model_validate(job.block_edit)
    base = await db.get(NovelChapterRevision, job.base_revision_id) if job.base_revision_id is not None else None
    if base is None:
        raise ValueError(f"job={job.id} 여러 문단 수정의 기준 개정이 없다")
    paragraphs = split_paragraphs(base.body)
    scenes = await revision_scenes(db, base.chapter_id, base.block_ids)
    positions = sorted(set(context_positions(scenes, edit.scene_id)) | {target.label - 1 for target in edit.targets})
    route = await resolve_novel_call_route(db, "novel_revise_blocks")
    source = await load_novel_prompt_source(db, model=route.chain_model)
    prompt = build_novelize_revise_blocks_prompt(
        sections=source.sections,
        is_story_chat=novel.content_type == "story",
        work_setting=await load_work_setting(db, novel, await _version_id(db, novel)),
        setting_notes=novel.setting_notes,
        paragraph_lines=context_lines(paragraphs, positions),
        target_labels=[target.label for target in edit.targets],
        user_request=job.instruction or "",
    )
    return BlockEditInput(prompt=prompt, edit=edit, call_model=route.call_model, route_source=route.source)


def _numbered(position: int, paragraphs: list[str]) -> str:
    """화 전체에서 센 번호 `[n] ` 을 앞에 단 글. 패치가 문단 여럿이면 줄을 바꿔 잇는다(블록 하나를 대신하는 한 덩어리다)."""
    return f"[{position + 1}] " + "\n".join(paragraphs)


async def build_recheck_prompt(
    db: AsyncSession,
    novel: Novel,
    revision: NovelChapterRevision,
    edit: BlockEdit,
    plan: RecheckPlan,
    *,
    chain_model: ChatModelId,
) -> NovelizePrompt:
    """묶음 재검사의 프롬프트. 사용자가 고친 문단의 지금 글, 남은 수정안, 그 둘레의 지금 글(같은 장면)을 지금 개정(`revision`)에서 센
    번호로 싣는다. 문안은 소설 레인 `chain_model` 체인에서 읽는다 — 부르는 쪽이 배정 표의 재검사 칸(`novel_recheck`)을 풀어
    넘긴다."""
    paragraphs = split_paragraphs(revision.body)
    scenes = await revision_scenes(db, revision.chapter_id, revision.block_ids)
    source = await load_novel_prompt_source(db, model=chain_model)
    return build_novelize_revise_recheck_prompt(
        sections=source.sections,
        is_story_chat=novel.content_type == "story",
        edited_lines="\n\n".join(_numbered(position, [text]) for position, text in plan.edited),
        patch_lines="\n\n".join(_numbered(position, patch.paragraphs or []) for position, patch in plan.remaining),
        paragraph_lines=context_lines(paragraphs, recheck_context_positions(plan, scenes, edit.scene_id)),
    )
