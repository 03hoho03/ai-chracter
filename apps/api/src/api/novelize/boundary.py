"""묶음 경계 — 다음 묶음 후보 턴마다의 화 수와, 모델이 고르는 끝 턴. 경계 제안 라우트와 연쇄 생성이 같이 쓴다.

화 수 계산을 한 곳에 두는 것은 확인 화면이 보여 준 금액과 작업이 계산한 금액이 같아야 해서다 — 둘이 다르게 세면 확인한
금액으로 낸 요청이 늘 409 가 된다. 끝 턴 제안을 한 곳에 두는 것은 사용자가 경계 모달에서 받는 제안과 연쇄가 묶음마다
자동으로 고르는 끝이 같은 판정이어야 해서다."""

import logging
import uuid

from api.chat.prompt_builder import PromptRenderError
from api.db.models.novel import Novel
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from api.novelize.episodes import episode_count, source_chars
from api.novelize.prompts import NovelizeBoundaryResult, build_novelize_boundary_prompt
from api.novelize.source import SourceTurn, format_turn_lines, novel_prompt_names

logger = logging.getLogger(__name__)


def episode_counts(turns: list[SourceTurn], novel: Novel, model: ChatModelId) -> list[int]:
    """턴마다 "다음 묶음 시작부터 이 턴까지"를 `model` 로 만들 때의 화 수."""
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    counts: list[int] = []
    chars = 0
    for turn in turns:
        chars += source_chars([turn], names)
        counts.append(episode_count(chars, model))
    return counts


async def suggest_end_turn(
    llm_client: LLMClient,
    *,
    novel: Novel,
    turns: list[SourceTurn],
    sections: list[PromptSection],
    chat_set: PromptSet,
    room_id: uuid.UUID,
) -> tuple[int, str] | None:
    """후보 `turns` 중 모델이 고른 끝 턴 번호(1부터)와 이유. 호출이나 문안 렌더가 실패하면 None 이다 — 경계는 사람이
    확인하거나(경계 모달) 턴 상한 끝으로 대신하므로(연쇄) 실패가 생성을 막을 이유가 없다. 범위 밖 번호는 버리지 않고
    마지막 후보로 바꾼다. 세션을 받지 않는다 — 부르는 쪽이 세트를 읽고 세션을 닫은 뒤 부른다(모델 호출 동안 커넥션을
    쥐지 않는다). 호출은 구조화 호출이라 고른 글쓰기 모델과 무관하게 늘 Gemini 다. `sections` 는 소설 레인 Gemini 체인
    세트, `chat_set` 은 원문 줄 라벨을 읽을 채팅 세트다(`inputs.load_novel_prompt_source`)."""
    is_story = novel.content_type == "story"
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    try:
        prompt = build_novelize_boundary_prompt(
            chat_set=chat_set,
            sections=sections,
            is_story_chat=is_story,
            max_turns=len(turns),
            user_name=(novel.protagonist_name or "").strip(),
            turn_lines=format_turn_lines(
                turns,
                names=names,
                user_label=chat_set.user_label,
                assistant_label=chat_set.story_assistant_label if is_story else chat_set.character_assistant_label,
            ),
        )
        result = await llm_client.generate_structured_with_instruction(
            prompt.prompt,
            NovelizeBoundaryResult,
            system_instruction=prompt.system_instruction,
            usage=LLMCallContext(call_site="novelize_boundary", user_id=novel.user_id, room_id=room_id),
        )
    except (LLMClientError, PromptRenderError) as exc:
        logger.warning("소설 묶음 경계 제안이 실패했다: %s", type(exc).__name__)
        return None
    end_turn = result.end_turn if 1 <= result.end_turn <= len(turns) else len(turns)
    return end_turn, result.reason
