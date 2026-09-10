import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from string import Formatter

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import Integer, cast, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminPromptDraftResponse,
    AdminPromptDraftUpsertRequest,
    AdminPromptLabels,
    AdminPromptPreviewItem,
    AdminPromptPreviewResponse,
    AdminPromptPublishRequest,
    AdminPromptSectionItem,
    AdminPromptSetDetailResponse,
    AdminPromptSetListResponse,
    AdminPromptSetSummary,
)
from api.chat.prompt_builder import (
    ALLOWED_PLACEHOLDERS,
    build_generation_prompt,
    build_stat_judgment_prompt,
    build_story_generation_prompt,
    load_active_prompt_set,
    system_instruction_for,
)
from api.chat.prompt_builder import build_ending_judgment_prompt as _build_ending_judgment_prompt
from api.chat.prompt_builder import build_image_judgment_prompt as _build_image_judgment_prompt
from api.chat.prompt_set_cache import invalidate_active_prompt_set
from api.content.publish import build_character_publish_filter_prompt, build_story_publish_filter_prompt
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StartingSetup, StatDef, StoryPromptTemplate
from api.db.session import get_db_session

router = APIRouter(tags=["admin"])

logger = logging.getLogger(__name__)

# prompt-db-goal-prompt.md §9-2 — 코드가 아는 (channel, scope, slot, variant) 정확한 집합.
# 마이그레이션 bd258b26c34a의 시드 48행 및 prompt-db-progress.md §B와 정확히 같다.
# `tests/test_prompt_seed.py`의 `_EXPECTED_SLOTS`가 "시드가 이 표와 일치하는가"를 보는
# 반면, 이 상수는 "임의의 초안이 이 표와 일치하는가"(게시 검증)를 본다 — 검증 대상이
# 달라 두 파일에 따로 둔다(시드 하나는 상수 데이터, 이건 임의 입력을 거부하는 게이트).
#
# R-1은 이 표에서 `variant`를 뗀 (channel, scope, slot) 수준으로만 본다 — 뗀 이유는
# R-2와 겹치지 않기 위해서다. `variant`까지 그대로 정확 일치를 요구하면
# `template_instruction`의 variant 하나를 지웠을 때 "슬롯 집합 불일치"(R-1)로도 이미
# 걸려서 R-2("R-2가 유일한 방어다")가 영원히 발동할 기회가 없다 — 두 규칙이 같은 입력을
# 두고 항상 같은 순서로 겹치면 뒤엣것은 죽은 코드다. 그래서 R-1은 "그 슬롯이 (scope
# 기준으로) 존재는 하는가"만 보고, "그 슬롯의 variant가 전부 있는가"는 R-2 전담이다.
_EXPECTED_ROWS: dict[str, frozenset[tuple[str, str, str]]] = {
    "system": frozenset(
        {
            ("story", "self_definition", ""),
            ("character", "self_definition", ""),
            ("both", "rule_response_format", ""),
            ("both", "rule_user_agency", ""),
            ("both", "rule_open_turn", ""),
            ("both", "rule_rating", ""),
            ("story", "template_instruction", "basic"),
            ("story", "template_instruction", "emotional"),
            ("story", "template_instruction", "simulation"),
            ("story", "template_instruction", "custom"),
            ("both", "priority_tail", ""),
        }
    ),
    "generation": frozenset(
        {
            ("character", "character_prompt", ""),
            ("story", "base_content", ""),
            ("story", "base_content", "custom"),
            ("character", "example_dialogues", ""),
            ("story", "rules", ""),
            ("story", "user_goal", ""),
            ("story", "development_examples", ""),
            ("story", "prologue", ""),
            ("both", "history", ""),
            ("story", "keyword_notes", ""),
            ("story", "shortcut_prompt", ""),
            ("both", "final_frame", ""),
        }
    ),
    "stat_judgment": frozenset(
        {
            ("story", "stat_defs_intro", ""),
            ("story", "turn_context", ""),
            ("story", "judgment_instruction", ""),
        }
    ),
    "ending_judgment": frozenset(
        {
            ("story", "history_header", ""),
            ("story", "turn_context", ""),
            ("story", "criteria", ""),
        }
    ),
    "image_judgment": frozenset(
        {
            ("character", "image_list_intro", ""),
            ("character", "turn_context", ""),
            ("character", "judgment_instruction", ""),
        }
    ),
    "publish_filter": frozenset(
        {
            ("character", "intro_instruction", ""),
            ("story", "intro_instruction", ""),
            ("both", "name", ""),
            ("both", "one_liner", ""),
            ("character", "intro", ""),
            ("story", "setting_text", ""),
            ("story", "development_example_legacy", ""),
            ("story", "custom_prompt", ""),
            ("story", "rules", ""),
            ("story", "user_goal", ""),
            ("story", "development_examples_pairs", ""),
            ("character", "example_dialogues", ""),
            ("character", "character_prompt", ""),
            ("both", "detail_description", ""),
            ("story", "starting_setups", ""),
            ("both", "verdict_instruction", ""),
        }
    ),
}

# R-1이 실제로 보는 것 — 위 표에서 `variant`를 뗀 (scope, slot) 집합. 새 목록을 손으로
# 또 적지 않고 `_EXPECTED_ROWS`에서 뽑는다(두 벌이면 template_instruction/base_content의
# variant 행 수가 바뀔 때 한쪽만 갱신되고 갈린다).
_EXPECTED_SLOTS: dict[str, frozenset[tuple[str, str]]] = {
    channel: frozenset((scope, slot) for scope, slot, _variant in rows)
    for channel, rows in _EXPECTED_ROWS.items()
}

# prompt-db-goal-prompt.md §9-2 R-2 — variant 전종이 반드시 있어야 하는 슬롯.
#
# `template_instruction`은 요청한 variant가 없으면 폴백할 기본(`variant=""`) 행 자체가
# 없어 슬롯째 조용히 드롭된다.
#
# `base_content`도 같은 크기의 사고다 — 처음엔 "기본 행이 있으니 드롭이 아니라 다른
# 문안으로 대체될 뿐"이라고 판단했는데 **틀렸다(적대적 리뷰가 실제 시드 body로 재현)**:
# `custom` variant가 빠지면 CUSTOM 템플릿 스토리도 `variant=""` 행(`body="{setting_text}"`)
# 으로 폴백하고, CUSTOM 스토리는 `setting_text`가 비어 있는 게 정상이라 `conditional=True`
# 탓에 섹션째 드롭된다 — "다른 문안으로 대체"가 아니라 **작품 설정(세계관/커스텀
# 프롬프트) 전체 소실**이다. `tests/test_chat_prompt_builder.py`의
# `test_render_prompt_channel_default_variant_fallback_drops_section_when_value_is_empty`가
# 이 사고를 렌더러 수준에서 고정한다.
#
# `StoryPromptTemplate`에서 직접 뽑아 두 벌로 갈릴 여지를 없앤다.
_REQUIRED_VARIANT_SLOTS: dict[tuple[str, str, str], frozenset[str]] = {
    ("system", "story", "template_instruction"): frozenset(t.value for t in StoryPromptTemplate),
    ("generation", "story", "base_content"): frozenset({"", "custom"}),
}

_LABEL_FIELDS: tuple[tuple[str, str], ...] = (
    ("userLabel", "user_label"),
    ("storyAssistantLabel", "story_assistant_label"),
    ("storyExampleLabel", "story_example_label"),
    ("characterAssistantLabel", "character_assistant_label"),
)


def _validation_error(rule: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"rule": rule, "message": message})


def _validate_prompt_draft_for_publish(prompt_set: PromptSet, sections: list[PromptSection]) -> None:
    """prompt-db-goal-prompt.md §9-2 R-1~R-7. 규칙 이름이 붙은 순서대로 검사하고 첫
    위반에서 멈춘다("순서대로 본다") — 뒤의 규칙들은 앞이 통과했다는 것에 기대어 있다
    (예: R-2는 슬롯 자체가 있다는 R-1의 결과를 전제한다)."""
    # R-1 — `variant`는 보지 않는다(위 `_EXPECTED_SLOTS` 주석 참고, R-2와 역할을 가른다).
    grouped: dict[str, set[tuple[str, str]]] = {}
    for section in sections:
        grouped.setdefault(section.channel, set()).add((section.scope, section.slot))
    actual = {channel: frozenset(rows) for channel, rows in grouped.items()}
    if actual != _EXPECTED_SLOTS:
        raise _validation_error(
            "R-1", "슬롯 집합이 코드가 아는 목록과 다릅니다(누락 또는 잉여가 있습니다)."
        )

    # R-2
    for (channel, scope, slot), required_variants in _REQUIRED_VARIANT_SLOTS.items():
        present = {
            s.variant for s in sections if s.channel == channel and s.scope == scope and s.slot == slot
        }
        missing = required_variants - present
        if missing:
            raise _validation_error(
                "R-2", f"{channel}/{slot}에 variant가 빠졌습니다: {sorted(missing)}"
            )

    # R-3
    for section in sections:
        if not section.body.strip():
            raise _validation_error(
                "R-3", f"{section.channel}/{section.slot}(variant={section.variant!r})의 body가 비어 있습니다."
            )

    # R-4
    for section in sections:
        try:
            fields = [name for _, name, _, _ in Formatter().parse(section.body) if name is not None]
        except ValueError as exc:
            raise _validation_error(
                "R-4", f"{section.channel}/{section.slot} body의 중괄호 짝이 맞지 않습니다: {exc}"
            ) from exc
        allowed = ALLOWED_PLACEHOLDERS.get((section.channel, section.slot), frozenset())
        unknown = sorted({name for name in fields if name not in allowed})
        if unknown:
            raise _validation_error(
                "R-4", f"{section.channel}/{section.slot} body가 허용되지 않은 플레이스홀더를 씁니다: {unknown}"
            )

    # R-5
    for query_name, attr in _LABEL_FIELDS:
        value = getattr(prompt_set, attr)
        if not value.strip():
            raise _validation_error("R-5", f"{query_name}이(가) 비어 있습니다.")
        if "\n" in value or ":" in value:
            raise _validation_error("R-5", f"{query_name}은(는) 개행이나 ':'을 포함할 수 없습니다.")

    # R-6. `(channel, scope, variant)`로 묶는다 — `self_definition`/`intro_instruction`처럼
    # 같은 슬롯이 scope만 다르게 두 행으로 존재하는 경우(§4-2) 서로 다른 실제 렌더 호출
    # (story-scope 렌더와 character-scope 렌더)에서만 각각 쓰이므로 같은 order를 공유해도
    # 충돌이 아니다 — 그래서 scope를 그룹 키에서 빼면 이 정상 케이스를 오탐한다.
    seen_orders: dict[tuple[str, str, str], dict[int, str]] = {}
    for section in sections:
        group = seen_orders.setdefault((section.channel, section.scope, section.variant), {})
        if section.order in group:
            raise _validation_error(
                "R-6",
                f"{section.channel}(scope={section.scope}, variant={section.variant!r})에서 "
                f"order={section.order}가 {group[section.order]!r}와 {section.slot!r}에 중복됩니다.",
            )
        group[section.order] = section.slot

    # R-7
    system_sections = [s for s in sections if s.channel == "system"]
    tail = next(s for s in system_sections if s.slot == "priority_tail")
    other_orders = [s.order for s in system_sections if s.slot != "priority_tail"]
    if other_orders and tail.order <= max(other_orders):
        raise _validation_error("R-7", "system 채널에서 priority_tail의 order가 가장 크지 않습니다.")


async def _next_published_version(db: AsyncSession) -> str:
    """D-15 — 서버가 부여하는 자동 증가 정수(문자열로 저장). 별도 함수로 뺀 이유는
    `test_admin_prompts_api.py`가 이 반환값만 몽키패치해 두 게시가 같은 버전을 계산하는
    경쟁을 흉내내기 위해서다(legal의 동시성 테스트가 `_get_draft`를 패치하는 것과 같은
    방식)."""
    latest_version: int | None = await db.scalar(
        select(func.max(cast(PromptSet.version, Integer))).where(PromptSet.status == "published")
    )
    return str((latest_version or 0) + 1)


async def _get_draft(db: AsyncSession) -> PromptSet | None:
    draft: PromptSet | None = await db.scalar(select(PromptSet).where(PromptSet.status == "draft"))
    return draft


async def _sections_of(db: AsyncSession, prompt_set_id: uuid.UUID) -> list[PromptSection]:
    sections = (
        await db.scalars(select(PromptSection).where(PromptSection.prompt_set_id == prompt_set_id))
    ).all()
    return sorted(sections, key=lambda s: (s.channel, s.order, s.slot, s.variant))


def _to_section_item(section: PromptSection) -> AdminPromptSectionItem:
    return AdminPromptSectionItem(
        channel=section.channel,
        scope=section.scope,
        slot=section.slot,
        variant=section.variant,
        body=section.body,
        conditional=section.conditional,
        order=section.order,
    )


def _to_labels(prompt_set: PromptSet) -> AdminPromptLabels:
    return AdminPromptLabels(
        user_label=prompt_set.user_label,
        story_assistant_label=prompt_set.story_assistant_label,
        story_example_label=prompt_set.story_example_label,
        character_assistant_label=prompt_set.character_assistant_label,
    )


@dataclass(frozen=True)
class _SectionFields:
    channel: str
    scope: str
    slot: str
    variant: str
    body: str
    conditional: bool
    order: int


def _find_duplicate_section_keys(sections: list[_SectionFields]) -> list[tuple[str, str, str, str]]:
    """`(channel, scope, slot, variant)` 중복을 찾는다 — DB의 유니크 인덱스
    (`ix_prompt_sections_set_channel_scope_slot_variant`)와 같은 키다.

    적대적 리뷰가 재현한 결함: 이 검사 없이 SAVEPOINT에 그대로 들어가면, 요청 자신의
    섹션 목록에 중복 키가 있어도 "다른 요청이 먼저 커밋했다"는 경쟁 상황과 **똑같은**
    `IntegrityError`가 난다. 초안이 없던 경우엔 SAVEPOINT 롤백이 방금 만든 draft 행까지
    되감아 `except` 블록의 `assert draft is not None`이 깨지고, 초안이 있던 경우엔
    `except` 블록의 재삽입이 감싸이지 않은 채 그대로 크래시한다 — 두 원인이 같은
    예외로 오므로 사후에 구분하려 들지 않고, 애초에 SAVEPOINT 밖에서 요청 자체를
    검사해 걸러낸다."""
    seen: set[tuple[str, str, str, str]] = set()
    duplicates: list[tuple[str, str, str, str]] = []
    for item in sections:
        key = (item.channel, item.scope, item.slot, item.variant)
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    return duplicates


async def _replace_draft_content(
    db: AsyncSession, *, labels: AdminPromptLabels, sections: list[_SectionFields]
) -> PromptSet:
    """초안 upsert(§9-1) — 섹션 전체 교체다. `PUT /draft`와 `POST /{id}/restore`가 공유한다.

    `admin/legal.py`의 SAVEPOINT 패턴을 그대로 따른다: 세션이 이미 이 요청(또는 테스트의
    롤백 트랜잭션)이라는 바깥 트랜잭션 안에 있으므로 `db.rollback()`은 그 바깥까지 되감아
    이전에 커밋된 행까지 지운다(실측으로 확인, `admin/legal.py:139-153`) — 이 upsert
    하나만 되감으려면 `begin_nested()`(SAVEPOINT)가 필요하다. 두 요청이 동시에 초안이
    없는 것을 보고 경쟁하면 진 쪽의 INSERT가 부분 유니크 인덱스(`ix_prompt_sets_draft`)에
    걸리는데, upsert 의미상 "초안이 이 내용이 되게 하라"는 먼저 커밋된 게 자신인지
    남인지와 무관하게 그대로 성립하므로 409로 거부하지 않고 이긴 행을 다시 읽어 이
    요청의 내용으로 덮어쓴다(legal의 draft upsert와 같은 판단). 자식(섹션) 삭제→삽입도
    같은 SAVEPOINT 안에서 한다 — `relationship()`이 없어 순서를 직접 지켜야 한다."""
    duplicate_keys = _find_duplicate_section_keys(sections)
    if duplicate_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "rule": "duplicate-section-key",
                "message": f"섹션 키(channel, scope, slot, variant)가 중복됩니다: {duplicate_keys}",
            },
        )

    draft = await _get_draft(db)
    try:
        async with db.begin_nested():
            if draft is None:
                draft = PromptSet(
                    id=uuid.uuid4(),
                    version=None,
                    status="draft",
                    note="",
                    user_label=labels.user_label,
                    story_assistant_label=labels.story_assistant_label,
                    story_example_label=labels.story_example_label,
                    character_assistant_label=labels.character_assistant_label,
                )
                db.add(draft)
                await db.flush()
            else:
                draft.user_label = labels.user_label
                draft.story_assistant_label = labels.story_assistant_label
                draft.story_example_label = labels.story_example_label
                draft.character_assistant_label = labels.character_assistant_label

            await db.execute(delete(PromptSection).where(PromptSection.prompt_set_id == draft.id))
            await db.flush()
            for item in sections:
                db.add(
                    PromptSection(
                        id=uuid.uuid4(),
                        prompt_set_id=draft.id,
                        channel=item.channel,
                        scope=item.scope,
                        slot=item.slot,
                        variant=item.variant,
                        body=item.body,
                        conditional=item.conditional,
                        order=item.order,
                    )
                )
            await db.flush()
    except IntegrityError:
        draft = await _get_draft(db)
        assert draft is not None  # 유니크 위반은 곧 초안이 이제 존재한다는 뜻이다
        draft.user_label = labels.user_label
        draft.story_assistant_label = labels.story_assistant_label
        draft.story_example_label = labels.story_example_label
        draft.character_assistant_label = labels.character_assistant_label
        await db.execute(delete(PromptSection).where(PromptSection.prompt_set_id == draft.id))
        await db.flush()
        for item in sections:
            db.add(
                PromptSection(
                    id=uuid.uuid4(),
                    prompt_set_id=draft.id,
                    channel=item.channel,
                    scope=item.scope,
                    slot=item.slot,
                    variant=item.variant,
                    body=item.body,
                    conditional=item.conditional,
                    order=item.order,
                )
            )

    await db.commit()
    return draft


# ---- 목록·조회 ----------------------------------------------------------------


@router.get("/admin/prompt-sets/draft")
async def get_prompt_draft(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    """`/admin/prompt-sets/{id}`보다 반드시 먼저 등록한다 — 둘 다 `GET`이고 경로 깊이가
    같아 "draft"가 문자 그대로 `{id}`에도 매치된다. Starlette은 등록 순서대로 첫 매치를
    쓰므로, `{id}`가 먼저면 이 라우트는 영원히 도달하지 못한다."""
    draft = await _get_draft(db)
    if draft is not None:
        sections = await _sections_of(db, draft.id)
        return AdminPromptDraftResponse(
            id=draft.id, labels=_to_labels(draft), sections=[_to_section_item(s) for s in sections]
        )

    active_set, active_sections = await load_active_prompt_set(db)
    return AdminPromptDraftResponse(
        id=None, labels=_to_labels(active_set), sections=[_to_section_item(s) for s in active_sections]
    )


@router.put("/admin/prompt-sets/draft")
async def upsert_prompt_draft(
    body: AdminPromptDraftUpsertRequest,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    fields = [
        _SectionFields(
            channel=item.channel,
            scope=item.scope,
            slot=item.slot,
            variant=item.variant,
            body=item.body,
            conditional=item.conditional,
            order=item.order,
        )
        for item in body.sections
    ]
    draft = await _replace_draft_content(db, labels=body.labels, sections=fields)
    sections = await _sections_of(db, draft.id)
    return AdminPromptDraftResponse(
        id=draft.id, labels=_to_labels(draft), sections=[_to_section_item(s) for s in sections]
    )


@router.post("/admin/prompt-sets/draft/preview")
async def preview_prompt_draft(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptPreviewResponse:
    """T-44/D-10 — 샘플 입력으로 **실제 렌더러**를 태워 조립된 전문을 채널별로 돌려준다.
    LLM은 부르지 않는다. 초안이 없으면 활성 세트로 미리보기한다(`GET .../draft`와 같은
    폴백)."""
    draft = await _get_draft(db)
    if draft is not None:
        prompt_set = draft
        sections = await _sections_of(db, draft.id)
    else:
        prompt_set, sections = await load_active_prompt_set(db)

    items = _build_preview_items(prompt_set, sections)
    return AdminPromptPreviewResponse(items=items)


@router.post("/admin/prompt-sets/publish")
async def publish_prompt_set(
    body: AdminPromptPublishRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptSetDetailResponse:
    draft = await _get_draft(db)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="발행할 초안이 없습니다.")
    sections = await _sections_of(db, draft.id)

    _validate_prompt_draft_for_publish(draft, sections)

    next_version = await _next_published_version(db)

    # `admin/legal.py:139-153`과 같은 이유로 `begin_nested()`(SAVEPOINT)로 감싼다 — 두
    # 게시가 동시에 같은 `next_version`을 계산하면 부분 유니크 인덱스
    # (`ix_prompt_sets_version_published`)가 뒤에 커밋되는 쪽을 막는데, 그건 진짜 초안
    # upsert와 달리 "덮어써도 되는" 경쟁이 아니라 서로 다른 두 내용 중 하나를 잃는
    # 상황이라 409로 재시도를 요구한다.
    try:
        async with db.begin_nested():
            published = PromptSet(
                id=uuid.uuid4(),
                version=next_version,
                status="published",
                note=body.note,
                user_label=draft.user_label,
                story_assistant_label=draft.story_assistant_label,
                story_example_label=draft.story_example_label,
                character_assistant_label=draft.character_assistant_label,
                published_at=datetime.now(UTC),
            )
            db.add(published)
            await db.flush()
            for section in sections:
                db.add(
                    PromptSection(
                        id=uuid.uuid4(),
                        prompt_set_id=published.id,
                        channel=section.channel,
                        scope=section.scope,
                        slot=section.slot,
                        variant=section.variant,
                        body=section.body,
                        conditional=section.conditional,
                        order=section.order,
                    )
                )
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="방금 다른 게시와 버전이 겹쳤습니다. 다시 시도해 주세요.",
        ) from None

    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="prompt-set-publish",
        reason_text=body.note,
    )
    # legal과 같다 — 게시 후에도 초안 행은 지우지 않는다(오타 하나 고쳐 재게시하는 흐름).
    await db.commit()

    # ⚠️ 반드시 커밋 **뒤에** 무효화한다(prompt-db-goal-prompt.md §8-1) — 커밋 전에 지우면
    # 그 사이의 캐시 미스가 아직 커밋되지 않은(=옛) 값을 다시 캐싱해 이 게시가 통째로
    # 씹힌다. `invalidate_active_prompt_set`은 `RedisError`를 삼키지 않는데, 여기서는
    # 그걸 삼키고 경고만 남긴다 — **DB 커밋(진짜 소스)이 이미 성공했다는 것은 곧 게시가
    # 실제로 일어났다는 뜻이다.** 이 시점에 500을 올리면 이미 일어난 성공을 실패로
    # 잘못 알리는 것이다. TTL(`prompt_set_cache_ttl_seconds`)이 이 실패의 상한이라 최대
    # 그 시간만큼만 옛 문안이 나간다 — DB read/SET 캐시 모듈이 이미 쓰는 것과 같은 판단이다.
    try:
        await invalidate_active_prompt_set()
    except RedisError:
        logger.warning("게시 후 프롬프트 세트 캐시 무효화 실패", exc_info=True)

    return AdminPromptSetDetailResponse(
        id=published.id,
        version=published.version,
        status=published.status,
        note=published.note,
        created_at=published.created_at,
        published_at=published.published_at,
        labels=_to_labels(published),
        sections=[_to_section_item(s) for s in sections],
    )


@router.post("/admin/prompt-sets/{id}/restore")
async def restore_prompt_set(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    """옛 버전을 초안으로 복제한다(= 롤백 경로). 게시하지 않는 한 서비스에는 아무 영향이
    없다 — 실제 롤백은 이 뒤에 이어지는 `POST /publish`가 한다."""
    source = await db.get(PromptSet, id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 버전을 찾을 수 없습니다.")
    source_sections = await _sections_of(db, source.id)

    fields = [
        _SectionFields(
            channel=s.channel,
            scope=s.scope,
            slot=s.slot,
            variant=s.variant,
            body=s.body,
            conditional=s.conditional,
            order=s.order,
        )
        for s in source_sections
    ]
    draft = await _replace_draft_content(db, labels=_to_labels(source), sections=fields)
    sections = await _sections_of(db, draft.id)
    return AdminPromptDraftResponse(
        id=draft.id, labels=_to_labels(draft), sections=[_to_section_item(s) for s in sections]
    )


@router.get("/admin/prompt-sets/{id}")
async def get_prompt_set(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptSetDetailResponse:
    prompt_set = await db.get(PromptSet, id)
    if prompt_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 버전을 찾을 수 없습니다.")
    sections = await _sections_of(db, prompt_set.id)
    return AdminPromptSetDetailResponse(
        id=prompt_set.id,
        version=prompt_set.version,
        status=prompt_set.status,
        note=prompt_set.note,
        created_at=prompt_set.created_at,
        published_at=prompt_set.published_at,
        labels=_to_labels(prompt_set),
        sections=[_to_section_item(s) for s in sections],
    )


@router.get("/admin/prompt-sets")
async def list_prompt_sets(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptSetListResponse:
    prompt_sets = (
        await db.scalars(select(PromptSet).order_by(PromptSet.created_at.desc()))
    ).all()
    active_id = await db.scalar(
        select(PromptSet.id)
        .where(PromptSet.status == "published")
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )
    return AdminPromptSetListResponse(
        items=[
            AdminPromptSetSummary(
                id=prompt_set.id,
                version=prompt_set.version,
                status=prompt_set.status,
                note=prompt_set.note,
                created_at=prompt_set.created_at,
                published_at=prompt_set.published_at,
                is_active=prompt_set.id == active_id,
            )
            for prompt_set in prompt_sets
        ]
    )


# ---- 미리보기 샘플 입력 --------------------------------------------------------
#
# T-44/D-10: 별도 조립 코드를 만들지 않는다 — 위 `build_*` 함수들(실제 채팅·발행 검열이
# 쓰는 바로 그 함수)에 지어낸 샘플 값을 넣어 호출할 뿐이다. DB에 닿지 않는 순수 함수라
# (`chat/stats.py` 류와 같은 리포 관례) ORM 모델을 세션 없이 생성자로만 채운다.

_SAMPLE_HISTORY = [
    ChatMessage(role=ChatMessageRole.USER, content="[샘플] 오늘 하루 어땠어?"),
    ChatMessage(role=ChatMessageRole.ASSISTANT, content="[샘플] 그럭저럭. 네가 오니까 낫네."),
]
_SAMPLE_EXAMPLE_DIALOGUES = [{"userLine": "[샘플] 뭐 하고 있었어?", "characterLine": "[샘플] 너 기다리고 있었지."}]
_SAMPLE_DEVELOPMENT_EXAMPLES = [{"userLine": "[샘플] 이 방향으로 가보자", "assistantLine": "[샘플] 그러자, 앞장설게"}]
_SAMPLE_STAT_DEFS = [
    StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=uuid.uuid4(),
        name="호감도",
        icon="heart",
        color="#ff6b81",
        min_value=0,
        max_value=100,
        initial_value=50,
        unit=None,
        description="[샘플] 캐릭터가 사용자에게 느끼는 호감도",
        per_turn_delta=None,
        order=1,
    )
]
_SAMPLE_SITUATIONAL_IMAGES = [
    SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        trigger_condition="[샘플] 캐릭터가 웃을 때",
        order=1,
    )
]
_SAMPLE_STARTING_SETUPS = [
    StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        name="[샘플] 시작 설정",
        prologue="[샘플] 이야기가 여기서 시작된다.",
        order=1,
    )
]


def _build_preview_items(prompt_set: PromptSet, sections: list[PromptSection]) -> list[AdminPromptPreviewItem]:
    items: list[AdminPromptPreviewItem] = []

    items.append(
        AdminPromptPreviewItem(
            channel="system",
            label="system · 캐릭터",
            text=system_instruction_for(sections, is_story_chat=False),
        )
    )
    for template in StoryPromptTemplate:
        items.append(
            AdminPromptPreviewItem(
                channel="system",
                label=f"system · 스토리 · {template.value}",
                text=system_instruction_for(sections, is_story_chat=True, template=template),
            )
        )

    items.append(
        AdminPromptPreviewItem(
            channel="generation",
            label="generation · 캐릭터",
            text=build_generation_prompt(
                prompt_set=prompt_set,
                sections=sections,
                character_prompt="[샘플] 캐릭터 프롬프트",
                example_dialogues=_SAMPLE_EXAMPLE_DIALOGUES,
                history=_SAMPLE_HISTORY,
                user_message="[샘플] 사용자 메시지",
            ),
        )
    )
    for label_suffix, template, custom_prompt in (
        ("스토리 · basic", StoryPromptTemplate.BASIC, None),
        ("스토리 · custom", StoryPromptTemplate.CUSTOM, "[샘플] 커스텀 프롬프트"),
    ):
        items.append(
            AdminPromptPreviewItem(
                channel="generation",
                label=f"generation · {label_suffix}",
                text=build_story_generation_prompt(
                    prompt_set=prompt_set,
                    sections=sections,
                    prompt_template=template,
                    setting_text="[샘플] 세계관 설정" if custom_prompt is None else None,
                    development_examples=_SAMPLE_DEVELOPMENT_EXAMPLES,
                    user_goal="[샘플] 사용자의 목표",
                    rules="[샘플] 규칙",
                    custom_prompt=custom_prompt,
                    prologue="[샘플] 시작 상황",
                    history=_SAMPLE_HISTORY,
                    user_message="[샘플] 사용자 메시지",
                    keyword_note_texts=["[샘플] 키워드북 항목"],
                    shortcut_prompt=None,
                ),
            )
        )

    items.append(
        AdminPromptPreviewItem(
            channel="stat_judgment",
            label="stat_judgment",
            text=build_stat_judgment_prompt(
                prompt_set=prompt_set,
                sections=sections,
                stat_defs=_SAMPLE_STAT_DEFS,
                current_stats={},
                user_message="[샘플] 사용자 메시지",
                assistant_message="[샘플] 진행자 응답",
            ),
        )
    )
    items.append(
        AdminPromptPreviewItem(
            channel="ending_judgment",
            label="ending_judgment",
            text=_build_ending_judgment_prompt(
                prompt_set=prompt_set,
                sections=sections,
                judgment_prompt="[샘플] 엔딩 판정 기준",
                history=_SAMPLE_HISTORY,
                user_message="[샘플] 사용자 메시지",
                assistant_message="[샘플] 진행자 응답",
            ),
        )
    )
    items.append(
        AdminPromptPreviewItem(
            channel="image_judgment",
            label="image_judgment",
            text=_build_image_judgment_prompt(
                prompt_set=prompt_set,
                sections=sections,
                situational_images=_SAMPLE_SITUATIONAL_IMAGES,
                history=_SAMPLE_HISTORY,
                user_message="[샘플] 사용자 메시지",
                assistant_message="[샘플] 캐릭터 응답",
            ),
        )
    )

    items.append(
        AdminPromptPreviewItem(
            channel="publish_filter",
            label="publish_filter · 캐릭터",
            text=build_character_publish_filter_prompt(
                prompt_set=prompt_set,
                sections=sections,
                name="[샘플] 캐릭터 이름",
                one_liner="[샘플] 한줄소개",
                intro="[샘플] 인트로",
                example_dialogues=_SAMPLE_EXAMPLE_DIALOGUES,
                character_prompt="[샘플] 캐릭터 프롬프트",
                detail_description="[샘플] 상세 설명",
            ),
        )
    )
    items.append(
        AdminPromptPreviewItem(
            channel="publish_filter",
            label="publish_filter · 스토리",
            text=build_story_publish_filter_prompt(
                prompt_set=prompt_set,
                sections=sections,
                name="[샘플] 스토리 이름",
                one_liner="[샘플] 한줄소개",
                setting_text="[샘플] 세계관 설정",
                development_example=None,
                custom_prompt=None,
                development_examples=_SAMPLE_DEVELOPMENT_EXAMPLES,
                user_goal="[샘플] 사용자의 목표",
                rules="[샘플] 규칙",
                detail_description="[샘플] 상세 설명",
                starting_setups=_SAMPLE_STARTING_SETUPS,
            ),
        )
    )

    return items
