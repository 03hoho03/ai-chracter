"""한 턴의 생성 프롬프트에 넣을 값을 모아 조립한다 — 실제 방(DB 에서 읽음)과 미리보기(초안 페이로드에서 읽음) 둘 다.

라우터의 SSE 제너레이터가 차감 뒤 이 모듈의 빌더를 부르고, 지난 턴을 다시 조립하는 측정 도구도 같은 빌더를 직접
부른다. 그래서 이 모듈은 라우터를 import 하지 않는다(라우터가 이 모듈을 import 한다).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.ending_rules import evaluate_rule_list
from api.chat.keyword_notes import match_keyword_notes
from api.chat.memory_window import CurrentSummary, load_current_summary, prompt_window
from api.chat.prompt_builder import (
    PromptLane,
    PromptNames,
    build_generation_prompt,
    build_story_generation_prompt,
    format_user_persona,
    load_active_prompt_set,
    memory_note_rendered,
    system_instruction_for,
    user_persona_rendered,
)
from api.chat.prompt_set_cache import get_cached_active_prompt_set, set_cached_active_prompt_set
from api.chat.room_stats import load_room_stats
from api.chat.schemas import EndingRuleGroupItem, EndingRuleItem, EndingRuleListItem
from api.content.schemas import (
    CharacterDraftPayload,
    RULE_LIST_ADAPTER,
    EndingRuleDraftItem,
    EndingRuleGroupDraftItem,
    EndingRuleListDraftItem,
    ShortcutDraftItem,
    StoryDraftPayload,
    count_rules,
)
from api.core.config import settings
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage, ChatRoom
from api.db.models.persona import UserPersona
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import KeywordNote, Shortcut, SituationNote, StartingSetup, StoryVersionDetail
from api.llm.chat_models import DEFAULT_CHAT_MODEL, ChatModelId

logger = logging.getLogger(__name__)


class GenerationPrompt(NamedTuple):
    """한 턴의 생성 호출에 넘길 값. `persona_description_rendered` 는 대화 프로필 섹션이 이 프롬프트에 실제로 들어갔고
    그 프로필에 설명이 있는가, `note_rendered` 는 기억 노트 섹션이 실제로 들어갔는가다(정책 안내 문구 분기용 — 이름만 있는
    프로필은 안내 대상이 아니다). `names` 는 같은 턴의 판정·요약이 생성과 같은 이름을 쓰도록 함께 돌려준다."""

    prompt: str
    system_instruction: str
    persona_description_rendered: bool
    note_rendered: bool
    names: PromptNames


@dataclass(frozen=True)
class InjectedPersona:
    """턴 상태 묶음의 대화 프로필 — 조립에 쓰이는 칸 전부(`format_user_persona` 의 인자와 같다)."""

    name: str
    gender: str | None
    description: str


@dataclass(frozen=True)
class InjectedTurnState:
    """`build_room_prompt` 가 방의 지금 값 대신 쓸 한 턴의 상태. 지난 턴을 그때 상태로 다시 조립하는 측정 도구가 넘긴다 —
    요약·기억 노트·스탯·대화 프로필은 DB 에 지금 값만 남기 때문이다.

    네 칸을 한꺼번에 준다(일부만 주고 나머지를 DB 에서 읽으면 서로 다른 시점의 값이 섞인다). `summary` 가 None 이면
    "요약 없음", `memory_note` 가 `""` 이면 "노트 없음", `persona` 가 None 이면 "프로필 없음"이다. `stats` 의 키는
    스탯 entity_id 문자열이고, 빠진 스탯은 상황 노트 조건에서 거짓이다."""

    summary: CurrentSummary | None
    memory_note: str
    stats: dict[str, float]
    persona: InjectedPersona | None


async def generation_prompt_set(
    db: AsyncSession,
    *,
    lane: PromptLane,
    model: ChatModelId,
    gemini_set: tuple[PromptSet, list[PromptSection]],
) -> tuple[PromptSet, list[PromptSection]]:
    """이 턴의 생성(바닥 지시문·생성 프롬프트·화자 라벨·정지 시퀀스)에 쓸 세트. 글쓰기 모델마다 독립 세트가 있고, 판정·요약은
    모델과 무관하게 `gemini_set`(라우터의 `_active_prompt_set_dependency`)을 쓴다.

    Gemini 면 받은 Gemini 세트를 그대로 돌려준다 — 조회가 없고, Gemini 턴의 프롬프트는 모델별 세트가 생기기 전과 바이트까지
    같다. 그 밖의 모델은 캐시를 보고 없으면 (레인, 모델) 활성 세트를 읽는다. 모델은 차감 영수증에서 오므로 차감 뒤에 읽는다 —
    세트가 없으면(`PromptSetNotFoundError`) 호출부가 렌더 실패와 같은 자리에서 오류 이벤트를 내고 환불한다."""
    if model == DEFAULT_CHAT_MODEL:
        return gemini_set
    cached = await get_cached_active_prompt_set(lane, model=model)
    if cached is not None:
        return cached
    prompt_set, sections = await load_active_prompt_set(db, lane=lane, model=model)
    await set_cached_active_prompt_set(lane, prompt_set, sections, model=model)
    return prompt_set, sections


def _situation_note_rules(note: SituationNote, room_id: uuid.UUID) -> list[EndingRuleListDraftItem]:
    """노트 행의 JSON 조건을 규칙 타입으로 되읽는다. 저장 경로는 전부 검증을 지나지만 손으로 고친 행이 깨져 있으면
    그 노트만 싣지 않는다(빈 조건 = 싣지 않음) — 생성 프롬프트 조립은 SSE 본문 안이라 예외가 새면 무관한 요청까지
    500 이 된다."""
    try:
        return RULE_LIST_ADAPTER.validate_python(note.condition_rules)
    except ValidationError:
        logger.warning("대화방 %s 상황 노트 %s 의 조건을 읽지 못해 싣지 않는다", room_id, note.entity_id, exc_info=True)
        return []


def _preview_ending_rule_item(item: EndingRuleDraftItem) -> EndingRuleItem:
    return EndingRuleItem(
        id=item.id, stat_id=item.stat_id, operator=item.operator, threshold=item.threshold, next_op=item.next_op
    )


def preview_ending_rule_list_item(item: EndingRuleListDraftItem) -> EndingRuleListItem:
    if isinstance(item, EndingRuleGroupDraftItem):
        return EndingRuleGroupItem(
            id=item.id, rules=[_preview_ending_rule_item(rule) for rule in item.rules], next_op=item.next_op
        )
    return _preview_ending_rule_item(item)


def pick_situation_note_texts(
    notes: Sequence[tuple[Sequence[EndingRuleListDraftItem], str]], stat_values: dict[str, float]
) -> list[str]:
    """`(조건, 본문)` 목록에서 조건이 참인 노트의 본문을 받은 순서대로 고른다. 실채팅·미리보기가 함께 쓴다 — 실채팅
    노트도 조건을 초안과 같은 타입으로 저장하므로 미리보기 엔딩 변환을 그대로 쓴다.

    조건 규칙이 하나도 없는 노트(빈 그룹만 있는 노트 포함)는 싣지 않는다. 평가기는 빈 목록을 참으로 보는데(엔딩은
    판정 모델만으로 정하라는 뜻), 노트에 그대로 쓰면 조건을 다 지운 노트·막 추가한 노트가 매 턴 실린다. 규칙 수는
    발행 검사와 같은 `count_rules` 로 세어 "발행이 거절하는 노트"와 "싣지 않는 노트"가 같게 한다.

    값이 없는 스탯을 가리키는 규칙은 거짓이다(평가기 규칙). 스탯을 지운 초안에서 생길 수 있다."""
    return [
        info_text
        for rules, info_text in notes
        if count_rules(rules) > 0
        and evaluate_rule_list([preview_ending_rule_list_item(item) for item in rules], stat_values)
    ]


def format_persona(persona: UserPersona | None) -> str:
    """실채팅(`build_room_prompt`)과 미리보기(`send_preview_message`)가 공유한다 — 프로필이
    없으면 `""`라 생성 프롬프트가 프로필 기능 이전과 바이트까지 같다."""
    if persona is None:
        return ""
    return format_user_persona(name=persona.name, gender=persona.gender, description=persona.description)


async def build_room_prompt(
    db: AsyncSession,
    room: ChatRoom,
    setup: StartingSetup | None,
    history: list[ChatMessage],
    user_content: str,
    shortcut: Shortcut | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    *,
    turn_state: InjectedTurnState | None = None,
) -> GenerationPrompt:
    """캐릭터 챗은 character_prompt+exampleDialogues로, 스토리 챗은 스토리 설정 템플릿+시작설정
    프롤로그로 생성 프롬프트를 조립한다. `send_message`/`edit_message`/`regenerate_message` 가
    라우터의 `_room_generation_prompt` 를 거쳐 공유한다.

    프롬프트와 함께 바닥 지시문(`system_instruction`)도 돌려준다 — 스토리 챗의 템플릿별 지시
    (`system_instruction_for`)를 고르려면 `story_detail.prompt_template`이 필요한데, 그 조회가
    이 함수 안에서만 일어나 호출부는 모른다. 조회를 한 번 더 하는 대신
    여기서 함께 고른다.

    방이 고른 대화 프로필은 이 턴에 **락 없이** 읽는다. 방 안에서
    바꾸면 다음 턴부터, 재생성·편집은 그 시점의 방 선택값을 쓴다. 그 사이 프로필이
    지워졌으면 `db.get`이 None이라 "선택 없음"(`""`)과 같다.

    세 번째·네 번째 값은 대화 프로필(설명이 있을 때만)·기억 노트 섹션이 이 프롬프트에 **실제로 들어갔는가**다
    (`user_persona_rendered`·`memory_note_rendered`, 정책 안내 문구 분기용). scope·variant를 아는
    곳이 여기뿐이라 함께 돌려준다.

    다섯 번째 값은 이 턴의 이름(`PromptNames`) — 방 프로필 이름, 방이 고정한 버전의 작품 기본 이름, 캐릭터 작품이면
    그 이름이다. 작가 글의 `{{user}}`·`{{char}}` 를 바꾸고 이름 한 줄을 채우는 데 쓰며, 프로필과 버전 상세를 읽는 곳이
    여기뿐이라 판정·요약 호출부가 같은 값을 쓰도록 함께 돌려준다(같은 턴 안에서 생성과 판정의 이름이 갈리지 않게).

    `history`는 호출부가 읽은 전체 히스토리이고, 요약 스냅샷이 덮은 메시지는 여기서 빼고 그 자리를
    현재 요약 본문이 대신한다(`prompt_window`). 세 라우트의 생성 프롬프트가 모두 이 함수를 지나므로
    윈도우도 한 곳에서만 계산된다. 판정 호출(엔딩·상황이미지)은 호출부의 전체 히스토리를 받고, 판정
    윈도우 설정이 켜졌을 때만 각자 윈도우를 씌운다. 생성 윈도우 설정이 꺼져 있으면 전체 히스토리를 싣고 요약은 싣지 않는다(같은
    대화가 두 번 들어가지 않게). 방의 기억 노트는 대화와 겹치지 않으므로 설정과 무관하게 싣는다.

    상황 노트 조건은 지금 DB 의 스탯 값(사용자가 보낸 순간 화면의 게이지, 이번 턴 판정 반영 전)으로 본다. 재생성은
    이번 턴 판정이 이미 반영된 값을 보므로 원 생성과 다른 노트가 실릴 수 있다 — 그때도 화면 게이지와는 맞다. 엔딩
    뒤에는 스탯이 멈춰 있어 같은 노트가 계속 실린다.

    `turn_state` 를 주면 요약·기억 노트·스탯·대화 프로필을 DB 대신 그 묶음에서 읽는다(지난 턴을 그때 상태로 다시
    조립하는 측정 도구가 쓴다 — 실제 대화의 호출부는 주지 않는다). 주입 요약에도 생성 윈도우 설정이 똑같이 걸리고,
    주입 프로필은 프로필 섹션·이름(`{{user}}` 치환·키워드 매칭·이름 한 줄)·프로필 렌더 여부가 모두 함께 본다."""
    memory_summary = ""
    if settings.memory_window_generation:
        current_summary = await load_current_summary(db, room.id) if turn_state is None else turn_state.summary
        if current_summary is not None:
            history = prompt_window(history, current_summary.cursor)
            memory_summary = current_summary.text
    if turn_state is None:
        memory_note = room.memory_note
        persona = await db.get(UserPersona, room.persona_id) if room.persona_id is not None else None
        persona_name = persona.name if persona is not None else None
        persona_description = persona.description if persona is not None else ""
        user_persona = format_persona(persona)
    else:
        memory_note = turn_state.memory_note
        injected = turn_state.persona
        persona_name = injected.name if injected is not None else None
        persona_description = injected.description if injected is not None else ""
        user_persona = (
            ""
            if injected is None
            else format_user_persona(name=injected.name, gender=injected.gender, description=injected.description)
        )

    if setup is not None:
        story_detail = await db.get(StoryVersionDetail, room.content_version_id)
        assert story_detail is not None
        notes = (
            await db.scalars(
                select(KeywordNote)
                .where(
                    KeywordNote.content_version_id == room.content_version_id,
                    or_(KeywordNote.starting_setup_id.is_(None), KeywordNote.starting_setup_id == setup.id),
                )
                .order_by(KeywordNote.order, KeywordNote.entity_id)
            )
        ).all()
        names = PromptNames(
            persona_name=persona_name,
            default_user_name=story_detail.default_user_name,
            char_name=None,
        )
        matched_notes = match_keyword_notes(notes, history, user_content, names=names)
        situation_notes = (
            await db.scalars(
                select(SituationNote)
                .where(SituationNote.starting_setup_id == setup.id)
                .order_by(SituationNote.order, SituationNote.entity_id)
            )
        ).all()
        situation_note_texts: list[str] = []
        # 스탯은 노트가 있을 때만 읽는다 — 노트 없는 시작설정의 턴에는 스탯 쿼리를 더하지 않는다.
        if situation_notes:
            current_stats = (
                (await load_room_stats(db, room.id, setup.id))[2] if turn_state is None else turn_state.stats
            )
            situation_note_texts = pick_situation_note_texts(
                [(_situation_note_rules(note, room.id), note.info_text) for note in situation_notes], current_stats
            )
        prompt = build_story_generation_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            prompt_template=story_detail.prompt_template,
            setting_text=story_detail.setting_text,
            development_examples=story_detail.development_examples,
            user_goal=story_detail.user_goal,
            rules=story_detail.rules,
            custom_prompt=story_detail.custom_prompt,
            prologue=setup.prologue,
            history=history,
            user_message=user_content,
            user_persona=user_persona,
            memory_note=memory_note,
            memory_summary=memory_summary,
            keyword_note_texts=[note.info_text for note in matched_notes],
            situation_note_texts=situation_note_texts,
            shortcut_prompt=shortcut.prompt if shortcut is not None else None,
            names=names,
        )
        return GenerationPrompt(
            prompt,
            system_instruction_for(prompt_sections, is_story_chat=True, template=story_detail.prompt_template),
            bool(persona_description)
            and user_persona_rendered(
                prompt_sections, is_story_chat=True, template=story_detail.prompt_template, user_persona=user_persona
            ),
            memory_note_rendered(
                prompt_sections, is_story_chat=True, template=story_detail.prompt_template, memory_note=memory_note
            ),
            names,
        )

    detail = await db.get(CharacterVersionDetail, room.content_version_id)
    assert detail is not None
    names = PromptNames(
        persona_name=persona_name,
        default_user_name=detail.default_user_name,
        char_name=detail.name,
    )
    prompt = build_generation_prompt(
        prompt_set=prompt_set,
        sections=prompt_sections,
        character_prompt=detail.character_prompt,
        example_dialogues=detail.example_dialogues,
        history=history,
        user_message=user_content,
        user_persona=user_persona,
        memory_note=memory_note,
        memory_summary=memory_summary,
        names=names,
    )
    return GenerationPrompt(
        prompt,
        system_instruction_for(prompt_sections, is_story_chat=False),
        bool(persona_description)
        and user_persona_rendered(prompt_sections, is_story_chat=False, user_persona=user_persona),
        memory_note_rendered(prompt_sections, is_story_chat=False, memory_note=memory_note),
        names,
    )


def _preview_keyword_notes(payload: StoryDraftPayload, setup_id: uuid.UUID | None) -> list[KeywordNote]:
    """실제 방의 `starting_setup_id IS NULL OR == 현재 setup` DB 필터와 동일한
    스코프 규칙을 payload 안에서 그대로 적용한다.

    매칭 엔진이 읽는 필드는 전부 채운다 — 세션 없이 만든 ORM 객체는 지정하지 않은 속성이 None 이다. 순서는 빌더 목록
    위치이고(저장도 그 위치를 순서로 쓴다), 같은 순서끼리 가르는 값은 노트 id 다."""
    return [
        KeywordNote(
            entity_id=note.id,
            info_text=note.info_text,
            trigger_keywords=note.trigger_keywords,
            name=note.name,
            order=index,
            exclude_keywords=note.exclude_keywords,
            sticky_turns=note.sticky_turns,
            always_on=note.always_on,
        )
        for index, note in enumerate(payload.keyword_notes)
        if note.starting_setup_id is None or note.starting_setup_id == setup_id
    ]


def build_preview_prompt(
    payload: CharacterDraftPayload | StoryDraftPayload,
    history: list[ChatMessage],
    user_content: str,
    shortcut: ShortcutDraftItem | None,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    user_persona: str,
    persona_description: str,
    stats: dict[str, float],
    names: PromptNames,
) -> GenerationPrompt:
    """`build_room_prompt`(실제 방)과 동일한 조립 규칙을 DB 조회 대신 payload 필드에서 직접
    읽어 적용한다. 스토리 draft가 시작설정을 아직 하나도 갖지 않으면("미완성 상태에서도
    테스트 가능" 원칙) 빈 프롤로그로 진행한다. 상황 노트 조건은 세션의 지금 스탯(`stats`, 이번 턴 판정
    반영 전)으로 본다 — 실제 방과 같은 시점이다.

    실제 방과 같은 모양으로 돌려준다. 미리보기에는 기억 노트가 없어 `note_rendered` 는 언제나 거짓이고, `names` 는
    받은 값 그대로다. 지시문·프로필 렌더 여부는 프롬프트를 렌더한 다음에 고른다 — 셋 중 무엇이 렌더 실패를 내든
    호출부의 같은 except 가 받는다."""
    if isinstance(payload, CharacterDraftPayload):
        prompt = build_generation_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            character_prompt=payload.character_prompt,
            example_dialogues=[dialogue.model_dump(by_alias=True) for dialogue in payload.example_dialogues],
            history=history,
            user_message=user_content,
            user_persona=user_persona,
            memory_note="",
            memory_summary="",
            names=names,
        )
    else:
        setup = payload.starting_setups[0] if payload.starting_setups else None
        notes = _preview_keyword_notes(payload, setup.id if setup is not None else None)
        matched_notes = match_keyword_notes(notes, history, user_content, names=names)
        situation_notes = setup.situation_notes if setup is not None else []
        prompt = build_story_generation_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            prompt_template=payload.prompt_template,
            setting_text=payload.setting_text,
            development_examples=[
                example.model_dump(by_alias=True) for example in payload.development_examples
            ],
            user_goal=payload.user_goal,
            rules=payload.rules,
            custom_prompt=payload.custom_prompt,
            prologue=setup.prologue if setup is not None else "",
            history=history,
            user_message=user_content,
            user_persona=user_persona,
            memory_note="",
            memory_summary="",
            keyword_note_texts=[note.info_text for note in matched_notes],
            situation_note_texts=pick_situation_note_texts(
                [(note.condition_rules, note.info_text) for note in situation_notes], stats
            ),
            shortcut_prompt=shortcut.prompt if shortcut is not None else None,
            names=names,
        )
    template = payload.prompt_template if isinstance(payload, StoryDraftPayload) else None
    system_instruction = system_instruction_for(
        prompt_sections, is_story_chat=isinstance(payload, StoryDraftPayload), template=template
    )
    # 활성 세트는 미리보기가 쓰는 것(라우터의 `_preview_prompt_set_dependency`), 값은 작가의 기본 프로필.
    persona_description_rendered = bool(persona_description) and user_persona_rendered(
        prompt_sections,
        is_story_chat=isinstance(payload, StoryDraftPayload),
        template=template,
        user_persona=user_persona,
    )
    return GenerationPrompt(prompt, system_instruction, persona_description_rendered, False, names)
