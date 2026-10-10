"""채팅 턴의 판정(스탯 규칙·엔딩·스토리 칸·캐릭터 상황 이미지)과 그 헬퍼. 재생성은 엔딩 판정을 하지 않고, 스탯은 바꾸는 턴의
효과를 되돌린 값에서 다시 판정할 수 있을 때만 다시 판정한다(`RegenerateStatJudgment`).
빌더 미리보기도 같은 판정을 하되(상황 이미지 판정은 없다) 입력을 DB 대신 초안 페이로드에서 읽는 미리보기판 클래스를 쓴다 —
입력 출처는 생성자가, 턴마다 같은 공통 입력은 `JudgmentContext` 가 갖는다.

판정 하나는 세 단계로 나뉜다 — `prepare`(DB 읽기와, 엔딩을 뺀 판정의 프롬프트 조립, 요청 세션의 트랜잭션 안), `judge`(DB 에 닿지 않는다 —
LLM 호출, 엔딩은 엔딩마다 프롬프트 렌더도 여기서 한다), `apply`(결과를 `TurnJudgmentResult` 에 옮긴다). 단계 사이의
순서와 반납 커밋, 바깥 `try`/`except` 는 부르는 쪽(`chat/turn_engine.py` 의 `run_turn`)이 정한다 — 판정마다 목록 순서와
`wave`(같은 물결의 판정은 함께 부르고, 두 번째 물결은 첫 물결을 반영한 뒤 차례로 부른다)만 알려 준다. 이 모듈은 라우터를
import 하지 않는다(라우터가 이 모듈을 import 한다).

흡수 범위는 헬퍼마다 다르고 클래스는 그대로 따른다. 스탯·칸 판정은 자기 LLM 실패를 흡수하고, 스탯·칸 준비는 자기 DB·렌더 실패를,
엔딩 준비와 상황 이미지 후보 조회는 자기 DB 실패를 흡수한다 — 준비 실패를 판정 안에서 흡수해야 뒤 판정의 준비와 판정이 그대로
돈다(예외가 준비 루프를 빠져나가면 뒤 판정은 준비조차 못 한다). 준비의 DB 읽기는 SAVEPOINT 로 감싸 실패가 그 읽기만 되감고
요청 세션의 트랜잭션은 유효하게 남게 한다. 엔딩 판정의 렌더·LLM, 상황 이미지 준비의 렌더와 판정 LLM 은 흡수하지 않고 부르는 쪽으로
올린다.

미리보기판은 판정 헬퍼(`_await_stat_judgment`·`_endings_to_judge`·`_judge_media_cell`)를 방 판정과 그대로 함께 쓰고, 호출
위치(`preview_*`)와 판정 주어("미리보기")만 다르다. 미리보기 칸 판정의 프롬프트 렌더 경고와, 방·미리보기 스탯 준비와 방 엔딩
준비의 실패 경고는 부르는 쪽이 넘긴 로거로 남긴다 — 앞의 것은 원래 라우터 안에 있던 것이고, 뒤의 것 가운데 스탯 렌더 실패는
판정 안으로 옮기기 전까지 턴 골격이 라우터의 로거로 남기던 것이다(로거 이름으로 거르는 쪽이 옮긴 뒤에도 같은 이름을 읽는다)."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.ending_rules import (
    EndingCandidate,
    ending_judgment_order,
    evaluate_rule_list,
    is_ending_check_due,
    referenced_stat_ids,
)
from api.chat.memory_window import CurrentSummary, load_current_summary, prompt_window
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MediaCellCandidate,
    PromptNames,
    PromptRenderError,
    PromptSetNotFoundError,
    StatJudgmentRequest,
    StatRuleJudgmentResult,
    build_ending_judgment_prompt,
    build_image_judgment_prompt,
    media_cell_image_lines,
    prepare_stat_judgment,
    situational_image_lines,
)
from api.chat.room_stats import load_room_stats
from api.chat.schemas import (
    ChatEndingReachedEvent,
    ChatStatChangeEvent,
    EndingRuleGroupItem,
    EndingRuleItem,
    EndingRuleListItem,
    PreviewSessionState,
)
from api.chat.stats import apply_rule_judgment
from api.chat.turn_prompt import JudgmentPromptSets, preview_ending_rule_list_item
from api.content.media_tags import normalize_media_tags
from api.content.schemas import (
    CharacterDraftPayload,
    EndingDraftItem,
    MediaTagImage,
    StartingSetupDraftItem,
    StatDefDraftItem,
    StoryDraftPayload,
)
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatRoom, ChatRoomStat, ChatTurn
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    StartingSetup,
    StatDef,
    StatRule,
)
from api.llm.client import (
    CallUsage,
    LLMCallContext,
    LLMClient,
    LLMClientError,
    dependency_tag,
    is_retryable_judgment_failure,
)

# 판정 실패는 흡수하더라도 서버 로그에 남긴다 — 라우터와 같은 이유로 이 모듈의 로그도 전부 warning 이상이다.
logger = logging.getLogger(__name__)


def _llm_dependency_tag(exc: LLMClientError | PromptRenderError | PromptSetNotFoundError) -> str:
    """생성·판정 흡수 지점(이 모듈의 판정 헬퍼, 턴 골격 `chat/turn_engine.py` 의 생성·판정, `chat/router.py` 의 방·미리보기
    생성 프롬프트 렌더)이 공유하는 승격 태그
    분류다. `PromptRenderError`는 외부 의존이 아니라 우리 템플릿 결함이라 별도 태그로 갈라
    묶어 본다. 생성 세트가 없는 것(`PromptSetNotFoundError`)도 같은 묶음이다 — 둘 다 어드민 문안 쪽을 고쳐야 한다. LLM 실패는 공급자와 쿼터 소진(429) 여부로 가른다(`llm/client.py` 의 `dependency_tag`) —
    안 갈라 붙이면 승격된 이벤트가 행동 가능하지 않다."""
    if isinstance(exc, (PromptRenderError, PromptSetNotFoundError)):
        return "prompt_render"
    return dependency_tag(exc)


def _ending_rule_item(rule: EndingRule) -> EndingRuleItem:
    return EndingRuleItem(
        id=rule.entity_id,
        stat_id=rule.stat_def_entity_id,
        operator=rule.operator,
        threshold=float(rule.threshold),
        next_op=rule.next_op,
    )


async def _ending_rule_items(db: AsyncSession, ending: Ending) -> list[EndingRuleListItem]:
    """`ending_rules`(top-level)와 `ending_rule_groups`(1단계 중첩) 두 테이블을 하나의
    `order` 공유 시퀀스로 합쳐 재구성한다 — 엔딩 규칙 평가 엔진(`evaluate_rule_list`)과
    contentSnapshot 응답 양쪽이 이 결과를 그대로 재사용한다."""
    top_rules = (await db.scalars(select(EndingRule).where(EndingRule.ending_id == ending.id))).all()
    top_groups = (await db.scalars(select(EndingRuleGroup).where(EndingRuleGroup.ending_id == ending.id))).all()

    items: list[tuple[int, EndingRuleListItem]] = [(rule.order, _ending_rule_item(rule)) for rule in top_rules]
    for group in top_groups:
        nested = (
            await db.scalars(
                select(EndingRule).where(EndingRule.rule_group_id == group.id).order_by(EndingRule.order)
            )
        ).all()
        items.append(
            (
                group.order,
                EndingRuleGroupItem(
                    id=group.entity_id, rules=[_ending_rule_item(r) for r in nested], next_op=group.next_op
                ),
            )
        )
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


def _ending_rules_pass(
    rule_items: list[EndingRuleListItem], stats: dict[str, float], *, log_subject: str, ending_id: uuid.UUID
) -> bool:
    """실채팅·미리보기 엔딩 루프가 판정 모델 앞에서 부른다. 값이 없는 스탯을 가리키는 항목은 `evaluate_rule_list`
    가 거짓으로 보고, 여기서 어느 엔딩의 어느 스탯인지 경고로 남긴다 — 그 엔딩이 영영 안 열리는 이유를 찾을 단서다."""
    missing_stat_ids = referenced_stat_ids(rule_items) - stats.keys()
    if missing_stat_ids:
        logger.warning(
            "%s 엔딩 %s 의 규칙이 값이 없는 스탯 %s 을 가리킨다 — 그 항목은 거짓으로 본다",
            log_subject,
            ending_id,
            ", ".join(sorted(missing_stat_ids)),
        )
    return evaluate_rule_list(rule_items, stats)


_JudgedEndingT = TypeVar("_JudgedEndingT")


def _endings_to_judge(
    due: Sequence[tuple[_JudgedEndingT, uuid.UUID, uuid.UUID | None, list[EndingRuleListItem]]],
    stats: dict[str, float],
    *,
    log_subject: str,
) -> list[_JudgedEndingT]:
    """판정 차례인 엔딩(목록 순서, `(엔딩, entity_id, 우선 스탯, 규칙)`)에서 이번 턴에 판정 모델을 부를 엔딩과 그 순서.
    실채팅·미리보기 엔딩 루프가 함께 쓴다 — 호출부는 이 순서로 판정하다 처음 발동한 엔딩에서 멈추고, 끝까지 발동이
    없으면 그 턴은 엔딩 없이 끝난다(우선 스탯 무리가 선 턴은 무리 1등까지만 판정한다).

    규칙을 먼저 전부 본 뒤 순서를 정한다(`ending_judgment_order`). 규칙은 이번 턴 반영 뒤 스탯만으로 정해지고 발동은
    규칙과 판정의 논리곱이라, 판정 모델 앞에서 미리 봐도 결과는 같고 규칙이 거짓인 엔딩의 호출만 준다. 우선 스탯 값이
    없어 무리에서 빠진 엔딩은 경고로 남긴다 — 무리 비교에서 빠진 이유를 찾을 단서다."""
    candidates = [
        EndingCandidate(ending=ending, ending_id=ending_id, priority_stat_id=priority_stat_id)
        for ending, ending_id, priority_stat_id, rule_items in due
        if _ending_rules_pass(rule_items, stats, log_subject=log_subject, ending_id=ending_id)
    ]
    order = ending_judgment_order(candidates, stats)
    for candidate in order.missing_priority:
        logger.warning(
            "%s 엔딩 %s 의 우선 스탯 %s 에 값이 없다 — 우선 스탯 비교에서 빼고 우선 스탯이 없는 엔딩처럼 다룬다",
            log_subject,
            candidate.ending_id,
            candidate.priority_stat_id,
        )
    return order.endings


@dataclass(frozen=True)
class _DueEndings:
    """이번 턴 엔딩 판정의 DB 읽기 결과 — 판정할 때가 된 엔딩(목록 순서)과 그 스탯 규칙, 판정 프롬프트에 실을
    히스토리·요약."""

    endings: list[tuple[Ending, list[EndingRuleListItem]]]
    history: list[ChatMessage]
    summary: str


async def _load_due_endings(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup, history: list[ChatMessage], turn: int
) -> _DueEndings:
    """엔딩 판정에 필요한 것을 판정 LLM **앞에서** 읽는다 — 엔딩 판정은 엔딩마다 LLM 을 차례로 부르므로, 규칙을
    루프 안에서 읽으면 DB 읽기와 LLM 대기가 번갈아 트랜잭션을 쥔 채 LLM 을 기다린다. 판정할 때가 아닌 엔딩의 규칙은
    읽지 않는다(때는 이번 턴 번호와 엔딩의 게이트만으로 정해진다).

    판정 윈도우를 켜면 요약이 덮은 원문을 빼고 그 자리에 현재 요약을 싣는다 — 엔딩은 지금까지의 대화 전체를 보는 누적
    판단이라 원문만 줄이면 앞부분을 잃는다. 끄면 전체 히스토리 그대로다."""
    endings = list(
        (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order))).all()
    )
    due = [
        (ending, await _ending_rule_items(db, ending))
        for ending in endings
        if is_ending_check_due(turn, ending.turn_count_gate)
    ]
    ending_history = history
    ending_summary = ""
    if settings.memory_window_generation and settings.memory_window_ending_judgment:
        current_summary = await load_current_summary(db, room.id)
        if current_summary is not None:
            ending_history = prompt_window(history, current_summary.cursor)
            ending_summary = current_summary.text
    return _DueEndings(endings=due, history=ending_history, summary=ending_summary)


async def _load_stat_rules(db: AsyncSession, stat_defs: Sequence[StatDef]) -> dict[uuid.UUID, list[StatRule]]:
    """스탯들의 규칙을 스탯 entity_id → 규칙 목록(`order` 순)으로 읽는다. 규칙은 스탯을 물리 FK 로 가리키므로 방이 고정한
    버전의 스탯 행에 달린 규칙만 나온다."""
    entity_id_by_stat_def_id = {stat_def.id: stat_def.entity_id for stat_def in stat_defs}
    rules_by_stat_id: dict[uuid.UUID, list[StatRule]] = {}
    for rule in (
        await db.scalars(
            select(StatRule)
            .where(StatRule.stat_def_id.in_(list(entity_id_by_stat_def_id)))
            .order_by(StatRule.order)
        )
    ).all():
        rules_by_stat_id.setdefault(entity_id_by_stat_def_id[rule.stat_def_id], []).append(rule)
    return rules_by_stat_id


async def _await_stat_judgment(
    llm_client: LLMClient,
    request: StatJudgmentRequest,
    usage: LLMCallContext,
    *,
    log_subject: str,
    current_stats: dict[str, float],
    stat_defs: list[StatDef],
) -> dict[str, float] | None:
    """스탯 판정 LLM 호출과 반영. 반영한 스탯 값(키 → 값, 바뀌지 않은 스탯 포함)을 돌려준다. 판정 LLM 이 고른 규칙을
    `apply_rule_judgment` 로 반영한다. 요청에 프롬프트가 없으면(`prepare_stat_judgment` 가 판정할 규칙이 없다고 정했다)
    LLM 을 부르지 않고 발동 규칙 없이 반영한다 — 카운터는 굴러가고, 결과가 `None` 이 아니라 엔딩 판정도 이어진다.

    LLM 실패는 흡수해 `None` — 칸 판정과 동시에 돌 때 이 실패가 칸 결과를 지우지 않게 한다. `None` 이면 호출부는 지금처럼
    스탯·엔딩 판정을 함께 건너뛴다."""
    if request.prompt is None:
        return apply_rule_judgment(current_stats, [], request.rule_ids, stat_defs)
    try:
        rule_judgment = await llm_client.generate_structured(request.prompt, StatRuleJudgmentResult, usage=usage)
        return apply_rule_judgment(current_stats, rule_judgment.fired_rule_ids, request.rule_ids, stat_defs)
    except LLMClientError as exc:
        logger.warning("%s 스탯 판정 실패 — 이번 턴의 스탯·엔딩 판정을 건너뛴다: %s", log_subject, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None


async def _await_stat_rejudgment(
    llm_client: LLMClient,
    request: StatJudgmentRequest,
    usage: LLMCallContext,
    *,
    log_subject: str,
    current_stats: dict[str, float],
    stat_defs: list[StatDef],
) -> dict[str, float] | None:
    """재생성의 스탯 재판정 — `_await_stat_judgment` 와 같되, 첫 호출이 곧바로 다시 부를 만한 실패
    (`is_retryable_judgment_failure`)면 한 번만 더 부른다. 재생성은 원 턴의 효과가 이미 반영된 상태에서 시작해 실패하면 새 응답에
    맞지 않는 스탯이 남으므로 다시 부를 만한 실패에서는 한 번 더 시도할 값이 있다. 보내기·수정의 판정은 실패해도 "그 턴의 효과
    없음"으로 일관되므로 다시 부르지 않는다 — 그래서 재시도를 공통 헬퍼가 아니라 여기에만 둔다.

    다시 부르는 것은 LLM 호출뿐이고 반영(`apply_rule_judgment`)은 성공한 결과 하나에 한 번이다. 실패한 호출마다 경고를 한 줄씩
    남기고(보내기·수정의 판정 실패 경고와 같은 "스탯 판정 실패"가 들어 있어 실패율을 함께 셀 수 있다), Bugsink 승격은 끝내
    실패했을 때 한 번이다. 끝내 실패하면 `None` 이다."""
    if request.prompt is None:
        return apply_rule_judgment(current_stats, [], request.rule_ids, stat_defs)
    attempt = 1
    while True:
        try:
            rule_judgment = await llm_client.generate_structured(request.prompt, StatRuleJudgmentResult, usage=usage)
        except LLMClientError as exc:
            if attempt == 1 and is_retryable_judgment_failure(exc):
                attempt += 1
                logger.warning("%s 스탯 판정 실패 — 한 번 다시 부른다: %s", log_subject, exc)
                continue
            logger.warning("%s 스탯 판정 실패 — 옛 응답의 스탯 효과를 그대로 둔다: %s", log_subject, exc)
            capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
            return None
        return apply_rule_judgment(current_stats, rule_judgment.fired_rule_ids, request.rule_ids, stat_defs)


async def _no_judgment() -> None:
    return None


async def _image_judgment_summary(db: AsyncSession, room: ChatRoom) -> CurrentSummary | None:
    """판정 윈도우를 켜면 요약이 덮은 원문을 뺀다 — 장면 매칭은 최근 원문이면 충분해 요약은 싣지 않는다.
    캐릭터 상황별 이미지와 스토리 칸 판정이 같은 스위치를 따른다. 후보가 있을 때만 부른다."""
    if settings.memory_window_generation and settings.memory_window_image_judgment:
        return await load_current_summary(db, room.id)
    return None


async def _judge_image_entity(
    llm_client: LLMClient, prompt: str, candidate_ids: set[uuid.UUID], usage: LLMCallContext
) -> uuid.UUID | None:
    """그림 고르기 판정 LLM 호출 — DB 에 닿지 않는다(스토리 턴은 이것만 스탯 판정과 동시에 부른다). 응답
    id 가 후보 안에 있을 때만 돌려준다: 응답은 문자열이라 형식이 틀리거나 후보 밖(노출 제외 칸 등)일 수 있다.
    `LLMClientError` 는 그대로 올린다 — 흡수 범위는 호출부가 정한다."""
    judgment = await llm_client.generate_structured(prompt, ImageMatchJudgmentResult, usage=usage)
    return next(
        (entity_id for entity_id in candidate_ids if str(entity_id) == judgment.matched_image_entity_id), None
    )


async def _load_situational_candidates(
    db: AsyncSession, room: ChatRoom
) -> tuple[list[SituationalImage], CurrentSummary | None]:
    """캐릭터 상황별 이미지 판정의 DB 읽기 — 후보 이미지(order 순)와, 판정 윈도우를 켰으면 현재 요약.

    조회 실패(`SQLAlchemyError`)는 여기서 흡수하고 후보 없음으로 돌려준다 — 호출부의
    `except (LLMClientError, PromptRenderError)` 는 DB 예외를 잡지 않아 그대로 두면 제너레이터를 뚫는다.

    `db.begin_nested()`(SAVEPOINT)로 국소화한다 — SAVEPOINT 없이 여기서 진짜 Postgres 실행 오류(`DBAPIError` 계열)가
    나면 트랜잭션이 aborted 상태가 되고, 이 `except`가 예외를 삼켜도 같은 트랜잭션에서 이어지는 문장은 전부
    `DBAPIError`로 부딪힌다 — 이 함수가 막으려는 파열이 한 자리 뒤로 미뤄질 뿐이다. 지금 호출부는 이 읽기 뒤에
    판정 앞 반납 커밋을 하고(aborted 트랜잭션의 커밋은 오류 없이 롤백으로 끝난다) 쓰기는 새 트랜잭션에서 하지만,
    가드가 그 커밋 위치에 기대지 않게 한다(테스트의 요청 세션은 바깥 트랜잭션에 묶여 그 커밋이 트랜잭션을 끝내지
    못하므로 실제 SQL 실패 테스트가 이 SAVEPOINT 를 직접 잰다). SAVEPOINT로 감싸면 실패가 그 SAVEPOINT에만
    갇히고 바깥 트랜잭션은 그대로 유효하게 남는다(SQLAlchemy 2.0.51 `AsyncSessionTransaction.__aexit__`이 예외 시
    SAVEPOINT까지만 rollback하고 재전파함을 소스로 확인, 격리 재현으로 실측 검증도 마쳤다)."""
    try:
        async with db.begin_nested():
            situational_images = list(
                (
                    await db.scalars(
                        select(SituationalImage)
                        .where(
                            SituationalImage.content_version_id == room.content_version_id,
                            # `PATCH /contents/{id}/draft`가
                            # 이미지 파일 업로드 전에 image_asset_id=NULL인 행을 먼저 만들 수 있다
                            # (character.py의 SituationalImage docstring). 지금은 발행 검증이 그런
                            # 행을 거부하지만, 그 검증이 생기기 전에 발행된 버전에는 NULL 행이 남아
                            # 있을 수 있다. 그런 후보를 판단 프롬프트에
                            # 싣지 않는다 — LLM이 존재하지 않는 이미지를 매칭할 원인을 여기서 끊는다.
                            SituationalImage.image_asset_id.is_not(None),
                        )
                        .order_by(SituationalImage.order)
                    )
                ).all()
            )
            current_summary = await _image_judgment_summary(db, room) if situational_images else None
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 상황이미지 후보 조회 실패 — 이번 턴은 매칭을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return [], None
    return situational_images, current_summary


@dataclass(frozen=True)
class _SituationalImageJudgment:
    """캐릭터 상황별 이미지 판정 한 번에 필요한 것 — DB 읽기·프롬프트 조립을 끝낸 상태라 LLM 호출만 남았다."""

    prompt: str
    candidates: list[SituationalImage]


async def _prepare_situational_image_judgment(
    db: AsyncSession,
    room: ChatRoom,
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> _SituationalImageJudgment | None:
    """캐릭터 챗 상황별 이미지 판정의 DB 읽기와 프롬프트 조립. 등록된 이미지가 없으면 `None` — 판정 호출 자체를
    생략한다. 판정(`_judge_situational_image`)과 노출 기록(`_record_character_image_exposure`)을 따로 두는 이유는 그
    사이에 요청 세션을 커밋으로 반납하기 위해서다 — 판정 LLM 을 기다리는 동안 커넥션을 쥐지 않는다.

    조회 실패는 `_load_situational_candidates` 가 흡수한다. 렌더 실패(`PromptRenderError`)는 호출부가 흡수한다."""
    situational_images, current_summary = await _load_situational_candidates(db, room)
    if not situational_images:
        return None
    if current_summary is not None:
        history = prompt_window(history, current_summary.cursor)

    prompt = build_image_judgment_prompt(
        prompt_set=prompt_set,
        sections=prompt_sections,
        scope="character",
        assistant_label=prompt_set.character_assistant_label,
        image_lines=situational_image_lines(situational_images, names=names),
        history=history,
        user_message=user_message,
        assistant_message=assistant_message,
        names=names,
    )
    return _SituationalImageJudgment(prompt=prompt, candidates=situational_images)


async def _judge_situational_image(
    llm_client: LLMClient, judgment: _SituationalImageJudgment, room: ChatRoom, usage_sink: list[CallUsage] | None
) -> SituationalImage | None:
    """상황별 이미지 판정 LLM 호출 — DB 에 닿지 않는다. 응답(matchedImageEntityId)은 항상 단수라 "동시 매칭 시
    order 최상위만 발동"은 프롬프트 지시로 처리하고, 그 반환값이 실제 후보 목록에 있는지만 방어적으로 재확인한다.
    매칭된 이미지 자체(entity_id 뿐 아니라 image_asset_id 도 필요, 인라인 렌더링 URL 조회용)를 돌려준다.
    `LLMClientError` 는 그대로 올린다 — 흡수 범위는 호출부가 정한다."""
    matched_id = await _judge_image_entity(
        llm_client,
        judgment.prompt,
        {image.entity_id for image in judgment.candidates},
        LLMCallContext(
            call_site="chat_situational_image", user_id=room.user_id, room_id=room.id, usage_sink=usage_sink
        ),
    )
    return next((image for image in judgment.candidates if image.entity_id == matched_id), None)


@dataclass(frozen=True)
class _MediaCellJudgment:
    """스토리 칸 판정 한 번에 필요한 것 — DB 읽기·프롬프트 조립을 끝낸 상태라 LLM 호출만 남았다."""

    prompt: str
    candidate_ids: set[uuid.UUID]


async def _prepare_media_cell_judgment(
    db: AsyncSession,
    room: ChatRoom,
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
) -> _MediaCellJudgment | None:
    """스토리 미디어 북 칸 판정의 DB 읽기와 프롬프트 조립. 후보는 방이 고정한 버전의 칸 중 대화 중 노출
    제외가 아닌 것이고, 빌더 축 순서(인물 → 장면)로 싣는다. 후보가 없으면(미디어 북 없음·전부 노출 제외)
    `None` — 판정을 부르지 않는다.

    판정 쪽 실패는 전부 여기서 흡수하고 `None` 이다 — 조회 실패는 캐릭터 후보 조회와 같은 SAVEPOINT 규칙,
    렌더 실패(배포 직후 캐시에 남은 옛 세트의 빈 프롬프트 포함)는 그 턴의 그림만 포기한다. 스탯·엔딩 판정은
    이 실패와 무관하게 돈다."""
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(
                        MediaBookCell.entity_id,
                        MediaBookPerson.name,
                        MediaBookScene.name,
                        MediaBookCell.situation_description,
                    )
                    .select_from(MediaBookCell)
                    .join(
                        MediaBookPerson,
                        and_(
                            MediaBookPerson.content_version_id == MediaBookCell.content_version_id,
                            MediaBookPerson.entity_id == MediaBookCell.person_entity_id,
                        ),
                    )
                    .join(
                        MediaBookScene,
                        and_(
                            MediaBookScene.content_version_id == MediaBookCell.content_version_id,
                            MediaBookScene.entity_id == MediaBookCell.scene_entity_id,
                        ),
                    )
                    .where(
                        MediaBookCell.content_version_id == room.content_version_id,
                        MediaBookCell.exclude_from_chat.is_(False),
                    )
                    .order_by(MediaBookPerson.order, MediaBookScene.order)
                )
            ).tuples().all()
            candidates = [
                MediaCellCandidate(entity_id=cell_id, person=person, scene=scene, situation_description=situation)
                for cell_id, person, scene, situation in rows
            ]
            current_summary = await _image_judgment_summary(db, room) if candidates else None
    except SQLAlchemyError as exc:
        logger.warning("대화방 %s 미디어 북 칸 후보 조회 실패 — 이번 턴은 칸 판정을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return None
    if not candidates:
        return None
    if current_summary is not None:
        history = prompt_window(history, current_summary.cursor)
    try:
        prompt = build_image_judgment_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            scope="story",
            assistant_label=prompt_set.story_assistant_label,
            image_lines=media_cell_image_lines(candidates, names=names),
            history=history,
            user_message=user_message,
            assistant_message=assistant_message,
            names=names,
        )
    except PromptRenderError as exc:
        logger.warning("대화방 %s 미디어 북 칸 판정 프롬프트 렌더 실패 — 이번 턴은 그림 없이 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None
    return _MediaCellJudgment(prompt=prompt, candidate_ids={cell.entity_id for cell in candidates})


async def _judge_media_cell(
    llm_client: LLMClient, judgment: _MediaCellJudgment, usage: LLMCallContext, *, log_subject: str
) -> uuid.UUID | None:
    """스토리 칸 판정 LLM 호출. 실패(`LLMClientError`)는 여기서 흡수해 그림만 포기한다 — 스탯 판정과 동시에
    돌 때 한쪽 예외가 다른 쪽 결과를 지우지 않게 한다. DB 에 닿지 않는다."""
    try:
        return await _judge_image_entity(llm_client, judgment.prompt, judgment.candidate_ids, usage)
    except LLMClientError as exc:
        logger.warning("%s 미디어 북 칸 판정 실패 — 이번 턴은 그림 없이 진행한다: %s", log_subject, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None


def _preview_stat_def(item: StatDefDraftItem) -> StatDef:
    return StatDef(
        entity_id=item.id,
        name=item.name,
        description=item.description,
        min_value=item.min_value,
        max_value=item.max_value,
        initial_value=item.initial_value,
        per_turn_delta=item.per_turn_delta,
    )


def _preview_stat_rules(item: StatDefDraftItem) -> list[StatRule]:
    """초안 스탯의 규칙을 판정 빌더가 읽는 인메모리 `StatRule` 로. 배열 순서가 순서다(저장과 같다)."""
    return [
        StatRule(entity_id=rule.id, condition=rule.condition, delta=rule.delta, order=order)
        for order, rule in enumerate(item.rules)
    ]


def _preview_cells_by_name(
    payload: StoryDraftPayload, media_images: dict[uuid.UUID, MediaTagImage]
) -> dict[tuple[str, str], uuid.UUID]:
    """페이로드 미디어 북을 (인물 이름, 장면 이름) → 칸 id 로. 축이 없는 칸은 이름이 없어 빠진다(실채팅의
    `load_media_cells_by_name` 과 같은 규칙). 그림을 서명하지 못한 칸(남의 자산·준비 안 된 자산)도 빼서 그 칸의
    태그는 없는 이름처럼 지워진다 — 빈칸 자리를 남기지 않는다."""
    if payload.media_book is None:
        return {}
    people = {person.id: person.name for person in payload.media_book.people}
    scenes = {scene.id: scene.name for scene in payload.media_book.scenes}
    return {
        (people[cell.person_id], scenes[cell.scene_id]): cell.id
        for cell in payload.media_book.cells
        if cell.person_id in people and cell.scene_id in scenes and cell.id in media_images
    }


def _prepare_preview_media_cell_judgment(
    payload: StoryDraftPayload,
    media_images: dict[uuid.UUID, MediaTagImage],
    *,
    prompt_set: PromptSet,
    prompt_sections: list[PromptSection],
    history: list[ChatMessage],
    user_message: str,
    assistant_message: str,
    names: PromptNames,
    log: logging.Logger,
) -> _MediaCellJudgment | None:
    """미리보기 칸 판정 — 실채팅 `_prepare_media_cell_judgment` 의 페이로드판. 후보는 노출 제외가 아니고 그림을
    서명한 칸(요청자 소유·준비 완료 — 라우터의 `_preview_media_book_dependency`)이며 빌더 축 순서다. 렌더 실패는 그림만
    포기하고, 그 경고는 부르는 쪽 로거(`log`)로 남긴다."""
    if payload.media_book is None:
        return None
    people = {person.id: (order, person.name) for order, person in enumerate(payload.media_book.people)}
    scenes = {scene.id: (order, scene.name) for order, scene in enumerate(payload.media_book.scenes)}
    candidates = [
        MediaCellCandidate(
            entity_id=cell.id,
            person=people[cell.person_id][1],
            scene=scenes[cell.scene_id][1],
            situation_description=cell.situation_description,
        )
        for cell in sorted(
            payload.media_book.cells, key=lambda cell: (people[cell.person_id][0], scenes[cell.scene_id][0])
        )
        if not cell.exclude_from_chat and cell.id in media_images
    ]
    if not candidates:
        return None
    try:
        prompt = build_image_judgment_prompt(
            prompt_set=prompt_set,
            sections=prompt_sections,
            scope="story",
            assistant_label=prompt_set.story_assistant_label,
            image_lines=media_cell_image_lines(candidates, names=names),
            history=history,
            user_message=user_message,
            assistant_message=assistant_message,
            names=names,
        )
    except PromptRenderError as exc:
        log.warning("미리보기 미디어 북 칸 판정 프롬프트 렌더 실패 — 이번 턴은 그림 없이 진행한다: %s", exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None
    return _MediaCellJudgment(prompt=prompt, candidate_ids={cell.entity_id for cell in candidates})


def _preview_ending_reached_event(
    payload: StoryDraftPayload,
    media_images: dict[uuid.UUID, MediaTagImage],
    ending_id: uuid.UUID,
    epilogue: str | None,
) -> ChatEndingReachedEvent:
    """미리보기 엔딩 이벤트. 에필로그는 페이로드 그대로라 이름 형태 태그다 — 실채팅처럼 칸 id 형태로 바꾸고(없는
    이름은 지운다) 가리키는 칸의 그림 맵을 싣는다."""
    if not epilogue:
        return ChatEndingReachedEvent(ending_id=ending_id, epilogue=epilogue)
    epilogue_text, refs = normalize_media_tags(epilogue, _preview_cells_by_name(payload, media_images))
    return ChatEndingReachedEvent(
        ending_id=ending_id,
        epilogue=epilogue_text,
        media_tag_images={cell_id: media_images[cell_id] for cell_id in refs if cell_id in media_images},
    )


@dataclass
class JudgmentContext:
    """한 턴의 판정들이 함께 읽는 입력. `stat_after` 만 판정 사이에 쓴다 — 스탯 판정의 반영 결과를 엔딩 판정이 읽는다.
    방(과 그 세션)·초안처럼 판정마다 출처가 다른 입력은 판정의 생성자가 받는다. 판정은 `prompt_sets` 에서 자기 종류의 세트를
    집는다(판정 종류마다 판정 모델이 따로다)."""

    prompt_sets: JudgmentPromptSets
    history: list[ChatMessage]
    user_message: str
    assistant_message: str
    names: PromptNames
    # 이번 턴 번호(새 턴은 쓰기 구간이 올릴 `turn_count`, 재생성은 지금 `turn_count`, 미리보기는 세션의 `turn_count` + 1)
    # — 엔딩 판정 차례를 정한다.
    turn: int
    log_subject: str
    stat_after: dict[str, float] | None = None
    # 방 판정이 자기 호출 컨텍스트에 넘겨 턴 기록에 실을 사용량 목록. `run_turn` 은 미리보기에도 이 목록을 넣지만,
    # 미리보기 판정 클래스는 기록이 없어 자기 호출 컨텍스트에 넘기지 않는다.
    usage_sink: list[CallUsage] | None = None


@dataclass
class TurnJudgmentResult:
    """쓰기 구간이 소비하는 판정 결과. 부르는 쪽이 판정 `try` 앞에서 만들고 판정이 차례로 채운다 — 중간에 예외가 나도
    그때까지 채운 칸은 그대로 쓰기 구간으로 간다(엔딩 판정이 실패해도 스탯 변화·칸 그림은 남는다)."""

    # 스탯 행(스탯 entity_id 문자열 → 행)과 바뀐 값만(같은 키 → 새 값). 쓰기는 `stat_writes` 의 키만 쓴다.
    stat_rows: dict[str, ChatRoomStat] = field(default_factory=dict)
    stat_writes: dict[str, float] = field(default_factory=dict)
    # 바뀐 스탯마다 `[반영 전, 반영 뒤]` — 턴 기록의 `stat_changes` 가 이 값이다. 반영 전 값이 없던 스탯은 `None` 이다.
    stat_changes: dict[str, list[float | None]] = field(default_factory=dict)
    # 재생성이 스탯을 다시 판정해 위 칸들을 채웠는가. 거짓이면 재생성 기록은 바꾸는 응답의 기록에서 스탯 변화를 이어받는다.
    stats_rejudged: bool = False
    stat_change_events: list[ChatStatChangeEvent] = field(default_factory=list)
    judged_cell_id: uuid.UUID | None = None
    matched_image: SituationalImage | None = None
    # 방 엔딩만 채운다 — 미리보기 엔딩은 DB 행이 없어 이벤트만 남긴다.
    reached_ending: Ending | None = None
    ending_reached_event: ChatEndingReachedEvent | None = None


class TurnJudgment(Protocol):
    """턴 판정 하나. `prepare` 는 입력을 읽고 프롬프트를 조립하고(방은 요청 세션으로 읽는다), `judge` 는 LLM 만 부르고,
    `apply` 는 결과를 옮긴다.

    `wave` 는 부르는 차례다 — 1 은 반납 뒤 함께 부르고(하나뿐이면 바로 기다린다) 곧바로 반영하며, 2 는 그 반영을 읽어야
    하는 판정이라 그 뒤에 목록 순서대로 하나씩 부르고 반영한다."""

    wave: int

    async def prepare(self, ctx: JudgmentContext) -> None: ...

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None: ...

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None: ...


def _apply_stat_result(
    ctx: JudgmentContext,
    result: TurnJudgmentResult,
    current: dict[str, float],
    updated: dict[str, float] | None,
) -> None:
    """스탯 판정의 반영 — 엔딩 판정이 읽을 값을 넘기고, 바뀐 스탯만 쓸 값과 `statChange` 이벤트(반영 결과의 키 순서)로
    옮긴다. 방·미리보기 스탯 판정이 함께 쓴다."""
    ctx.stat_after = updated
    if updated is None:
        return
    for stat_id, new_value in updated.items():
        if new_value != current.get(stat_id):
            result.stat_writes[stat_id] = new_value
            result.stat_changes[stat_id] = [current.get(stat_id), new_value]
            result.stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))


def _prepare_stat_request(
    ctx: JudgmentContext,
    stat_defs: list[StatDef],
    rules_by_stat_id: dict[uuid.UUID, list[StatRule]],
    *,
    log: logging.Logger,
) -> StatJudgmentRequest | None:
    """스탯 판정 프롬프트 조립 — 방·미리보기 스탯 판정이 함께 쓴다. 렌더 실패는 흡수해 `None` 이다: 판정 요청이 없으면
    스탯 판정을 부르지 않고 반영 결과도 `None` 이라 엔딩 판정도 건너뛴다(카운터도 굴리지 않는다 — LLM 실패와 같은 결과).
    흡수하지 않으면 예외가 준비 루프를 빠져나가 칸 판정의 준비와 판정까지 사라진다."""
    try:
        return prepare_stat_judgment(
            prompt_set=ctx.prompt_sets.stat[0],
            sections=ctx.prompt_sets.stat[1],
            stat_defs=stat_defs,
            rules_by_stat_id=rules_by_stat_id,
            user_message=ctx.user_message,
            assistant_message=ctx.assistant_message,
            names=ctx.names,
        )
    except PromptRenderError as exc:
        log.warning("%s 스탯 판정 프롬프트 렌더 실패 — 이번 턴의 스탯·엔딩 판정을 건너뛴다: %s", ctx.log_subject, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        return None


class StatJudgment:
    """스토리 스탯 규칙 판정. 최초 엔딩 전에만 돈다. 준비의 DB 읽기 실패와 렌더 실패는 흡수하고 그 턴의 스탯·엔딩 판정을
    건너뛴다(칸 판정은 그대로 돈다). DB 읽기는 SAVEPOINT 안에서 해 실패가 그 읽기만 되감는다 — 그래야 뒤의 엔딩·칸 준비가
    같은 요청 세션으로 읽을 수 있다. 준비가 실패하면 판정 요청이 없어 카운터 스탯도 굴리지 않는다. LLM 실패는
    `_await_stat_judgment` 가 흡수해 결과가 `None` 이고, 그러면 엔딩 판정도 건너뛴다. 경고는 부르는 쪽이 넘긴 로거로 남긴다."""

    wave = 1

    def __init__(self, db: AsyncSession, room: ChatRoom, setup: StartingSetup, *, log: logging.Logger) -> None:
        self._db = db
        self._room = room
        self._setup = setup
        self._log = log
        self._stat_defs: list[StatDef] = []
        self._stat_rows: dict[str, ChatRoomStat] = {}
        self._current_stats: dict[str, float] = {}
        self._request: StatJudgmentRequest | None = None
        self._updated: dict[str, float] | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        if self._room.ending_reached:
            return
        try:
            async with self._db.begin_nested():
                stat_defs, stat_rows, current_stats = await load_room_stats(self._db, self._room.id, self._setup.id)
                rules_by_stat_id = await _load_stat_rules(self._db, stat_defs)
        except SQLAlchemyError as exc:
            self._log.warning(
                "%s 스탯 판정 입력 조회 실패 — 이번 턴의 스탯·엔딩 판정을 건너뛴다: %s", ctx.log_subject, exc
            )
            capture_dependency_failure(exc, dependency="db")
            return
        self._stat_defs, self._stat_rows, self._current_stats = stat_defs, stat_rows, current_stats
        self._request = _prepare_stat_request(ctx, stat_defs, rules_by_stat_id, log=self._log)

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        if self._request is None:
            return
        self._updated = await _await_stat_judgment(
            llm_client,
            self._request,
            LLMCallContext(
                call_site="chat_stat_judgment",
                user_id=self._room.user_id,
                room_id=self._room.id,
                usage_sink=ctx.usage_sink,
            ),
            log_subject=ctx.log_subject,
            current_stats=self._current_stats,
            stat_defs=self._stat_defs,
        )

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        result.stat_rows = self._stat_rows
        _apply_stat_result(ctx, result, self._current_stats, self._updated)


def _starting_values(
    current_stats: dict[str, float], stat_changes: dict[str, list[float | None]], stat_defs: list[StatDef]
) -> dict[str, float]:
    """바꾸는 응답의 턴 기록에 남은 변화(`{스탯: [반영 전, 반영 뒤]}`)를 지금 값에서 되돌린 값 — 그 턴이 시작할 때의 값이다.
    기록에 없는 스탯은 그 턴이 바꾸지 않았으니 지금 값 그대로다. 반영 전 값이 비어 있으면 그 스탯의 시작값(`initial_value`)으로
    되돌린다 — `load_room_stats` 가 행이 없는 스탯을 시작값으로 채우는 것과 같은 뜻이다. 비어 있다고 판정 입력에서 빼면, 규칙이
    발동하지 않은 판정 스탯은 판정 결과에도 없어 쓰이지 않고 원 턴의 값이 그대로 굳는다. 지금 버전에 정의가 없는 스탯은 판정
    대상이 아니므로 지금 값 그대로 둔다. 기록은 JSON 이라 정수·실수가 섞여 오므로 실수로 맞춘다."""
    initial_values = {str(stat_def.entity_id): float(stat_def.initial_value) for stat_def in stat_defs}
    starting = dict(current_stats)
    for stat_id, (before, _after) in stat_changes.items():
        if before is not None:
            starting[stat_id] = float(before)
        elif stat_id in initial_values:
            starting[stat_id] = initial_values[stat_id]
    return starting


class RegenerateStatJudgment:
    """재생성의 스탯 재판정 — 바꾸는 응답의 턴 효과를 되돌린 값에서 새 응답으로 다시 판정한다. 그 응답의 턴 기록이 있고, 그
    기록에 엔딩이 없고, 방이 아직 엔딩 전이고, 그 기록의 턴이 방의 마지막 턴(`turn_number == turn_count`)일 때만 한다.

    - 엔딩이 난 턴은 되돌리면 사용자 단위 엔딩 수집과 엔딩 뒤 판정 정지까지 건드리므로 그대로 둔다.
    - 기록이 없는 턴(기록을 쓰기 전에 보낸 턴)은 무엇을 되돌릴지 모른다.
    - 마지막 턴이 아니면(메시지 삭제로 뒤 턴을 지워 앞 응답이 마지막이 된 방) 기록의 반영 전 값이 절대값이라 되돌리면 지운 턴들의
      효과까지 사라진다. 메시지 삭제는 지운 턴의 효과를 남기므로 그 의미를 지킨다.

    되돌린 값은 메모리에서 판정 입력으로만 쓰고, 되돌림과 새 값은 쓰기 구간이 한 커밋에 쓴다 — 생성 프롬프트는 이미 지금 DB 값으로
    조립됐고(상황 노트가 지금 스탯으로 고른다), 생성이 실패한 재생성은 이 판정까지 오지 않아 스탯이 그대로다. 판정이 반영 전 값에서
    출발하므로 카운터도 반영 전 값에서 한 번만 구른다(원 턴의 카운터는 되돌림으로 사라진다).

    판정 LLM 실패는 다시 부를 만한 종류(일시적인 서버·연결 오류와 파싱 실패)에 한해 한 번 더 부르고(`_await_stat_rejudgment`),
    끝내 실패하면 되돌리지 않는다 — 스탯 값과
    `statChange` 는 그대로이고 재생성 기록은 옛 기록의 변화를 이어받는다(재판정 전 재생성과 같은 화면이고, 다음 재생성이 그 기록으로
    정확히 되돌린다). 준비의 DB 읽기·렌더 실패도 같은 결과다. 엔딩 판정은 하지 않는다 — 엔딩 판정은 게이트를 넘긴 뒤 5턴마다
    판정 차례가 온 턴(`is_ending_check_due`)에만 돌므로, 재판정한 스탯이 엔딩 조건을 새로 채우면 그것을 보는 것은 다음에 판정
    차례가 오는 새 턴이다. 재생성한 턴 자신이 판정 차례였다면 그 차례의 엔딩 기회는 다음 차례(5턴 뒤)로 밀린다."""

    wave = 1

    def __init__(
        self,
        db: AsyncSession,
        room: ChatRoom,
        setup: StartingSetup,
        replaced_message_id: uuid.UUID,
        *,
        log: logging.Logger,
    ) -> None:
        self._db = db
        self._room = room
        self._setup = setup
        self._replaced_message_id = replaced_message_id
        self._log = log
        self._stat_defs: list[StatDef] = []
        self._stat_rows: dict[str, ChatRoomStat] = {}
        # 지금 DB 값(화면이 들고 있는 값)과 바꾸는 턴이 시작할 때의 값.
        self._current_stats: dict[str, float] = {}
        self._starting_stats: dict[str, float] = {}
        self._request: StatJudgmentRequest | None = None
        self._updated: dict[str, float] | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        if self._room.ending_reached:
            return
        try:
            async with self._db.begin_nested():
                record = await self._db.scalar(
                    select(ChatTurn).where(ChatTurn.assistant_message_id == self._replaced_message_id)
                )
                if record is None or record.ending_entity_id is not None or record.turn_number != self._room.turn_count:
                    return
                stat_defs, stat_rows, current_stats = await load_room_stats(self._db, self._room.id, self._setup.id)
                rules_by_stat_id = await _load_stat_rules(self._db, stat_defs)
        except SQLAlchemyError as exc:
            self._log.warning(
                "%s 스탯 재판정 입력 조회 실패 — 옛 응답의 스탯 효과를 그대로 둔다: %s", ctx.log_subject, exc
            )
            capture_dependency_failure(exc, dependency="db")
            return
        self._stat_defs, self._stat_rows, self._current_stats = stat_defs, stat_rows, current_stats
        self._starting_stats = _starting_values(current_stats, record.stat_changes, stat_defs)
        self._request = _prepare_stat_request(ctx, stat_defs, rules_by_stat_id, log=self._log)

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        if self._request is None:
            return
        self._updated = await _await_stat_rejudgment(
            llm_client,
            self._request,
            LLMCallContext(
                call_site="chat_stat_judgment",
                user_id=self._room.user_id,
                room_id=self._room.id,
                usage_sink=ctx.usage_sink,
            ),
            log_subject=ctx.log_subject,
            current_stats=self._starting_stats,
            stat_defs=self._stat_defs,
        )

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        """쓸 값과 `statChange` 는 지금 DB 값과 달라진 스탯이다 — 되돌리기만 하고 새 판정이 다시 바꾸지 않은 스탯도 써야 하고,
        화면은 지금 DB 값을 들고 있다. 기록에 남길 변화는 턴이 시작할 때의 값 대비다(이 응답에 귀속된 효과)."""
        updated = self._updated
        ctx.stat_after = updated
        if updated is None:
            return
        result.stat_rows = self._stat_rows
        result.stats_rejudged = True
        for stat_id, new_value in updated.items():
            if new_value != self._current_stats.get(stat_id):
                result.stat_writes[stat_id] = new_value
                result.stat_change_events.append(ChatStatChangeEvent(stat_id=stat_id, new_value=new_value))
            if new_value != self._starting_stats.get(stat_id):
                result.stat_changes[stat_id] = [self._starting_stats.get(stat_id), new_value]


class EndingJudgment:
    """스토리 엔딩 판정. 스탯 판정이 반영된 뒤(`ctx.stat_after`)에만 돈다 — 규칙은 반영 뒤 스탯으로 정해지므로 판정할 엔딩과
    그 프롬프트는 `judge` 에서 정한다. 준비는 판정할 때가 된 엔딩과 그 규칙·히스토리만 미리 읽는다(판정 LLM 을 기다리는
    동안 트랜잭션을 쥐지 않게).

    준비의 DB 읽기 실패는 SAVEPOINT 안에서 흡수하고(경고는 부르는 쪽이 넘긴 로거로) 그 턴의 엔딩 판정만 건너뛴다 — 스탯
    판정과 칸 판정은 이미 준비를 마쳤거나 같은 요청 세션으로 그대로 준비한다. 엔딩 판정의 렌더·LLM 실패는 흡수하지 않는다 —
    첫 실패에서 남은 엔딩을 보지 않고 부르는 쪽 `except` 로 간다."""

    wave = 2

    def __init__(self, db: AsyncSession, room: ChatRoom, setup: StartingSetup, *, log: logging.Logger) -> None:
        self._db = db
        self._room = room
        self._setup = setup
        self._log = log
        self._due: _DueEndings | None = None
        self._reached: Ending | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        if self._room.ending_reached:
            return
        try:
            async with self._db.begin_nested():
                self._due = await _load_due_endings(self._db, self._room, self._setup, ctx.history, ctx.turn)
        except SQLAlchemyError as exc:
            self._log.warning("%s 엔딩 판정 입력 조회 실패 — 이번 턴의 엔딩 판정을 건너뛴다: %s", ctx.log_subject, exc)
            capture_dependency_failure(exc, dependency="db")

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        # 엔딩 판정: 엔딩별 turn_count_gate를 넘긴 시점부터 5턴마다만 호출하고, 그 외 턴은 스킵한다.
        # 스탯 규칙을 통과한 엔딩만, `_endings_to_judge` 가 정한 순서(목록 순서, 우선 스탯을 채운 엔딩끼리는
        # 그 값이 가장 높은 것만, 그 뒤는 없음)로 판정해 첫 충족 엔딩에서 멈춘다(동시 충족 시 하나만 발동).
        # 스탯 반영 뒤라 순차다. 준비에서 엔딩을 읽지 못했으면(`_due` 가 없다) 이번 턴은 엔딩을 판정하지 않는다.
        if ctx.stat_after is None or self._due is None:
            return
        for ending in _endings_to_judge(
            [
                (ending, ending.entity_id, ending.priority_stat_def_entity_id, rule_items)
                for ending, rule_items in self._due.endings
            ],
            ctx.stat_after,
            log_subject=ctx.log_subject,
        ):
            ending_judgment_prompt = build_ending_judgment_prompt(
                prompt_set=ctx.prompt_sets.ending[0],
                sections=ctx.prompt_sets.ending[1],
                judgment_prompt=ending.judgment_prompt,
                history=self._due.history,
                user_message=ctx.user_message,
                assistant_message=ctx.assistant_message,
                memory_summary=self._due.summary,
                names=ctx.names,
            )
            ending_judgment = await llm_client.generate_structured(
                ending_judgment_prompt,
                EndingJudgmentResult,
                usage=LLMCallContext(
                    call_site="chat_ending_judgment",
                    user_id=self._room.user_id,
                    room_id=self._room.id,
                    usage_sink=ctx.usage_sink,
                ),
            )
            if not ending_judgment.triggered:
                continue
            self._reached = ending
            break

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        if self._reached is None:
            return
        result.reached_ending = self._reached
        result.ending_reached_event = ChatEndingReachedEvent(
            ending_id=self._reached.entity_id, epilogue=self._reached.epilogue
        )


class MediaCellJudgment:
    """스토리 미디어 북 칸 판정. 엔딩 여부와 무관하게 돈다. 준비(`_prepare_media_cell_judgment`)와 판정
    (`_judge_media_cell`)이 자기 실패를 전부 흡수해 그림만 포기한다."""

    wave = 1

    def __init__(self, db: AsyncSession, room: ChatRoom) -> None:
        self._db = db
        self._room = room
        self._judgment: _MediaCellJudgment | None = None
        self._cell_id: uuid.UUID | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        self._judgment = await _prepare_media_cell_judgment(
            self._db,
            self._room,
            prompt_set=ctx.prompt_sets.image[0],
            prompt_sections=ctx.prompt_sets.image[1],
            history=ctx.history,
            user_message=ctx.user_message,
            assistant_message=ctx.assistant_message,
            names=ctx.names,
        )

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        if self._judgment is None:
            return
        self._cell_id = await _judge_media_cell(
            llm_client,
            self._judgment,
            LLMCallContext(
                call_site="chat_media_book_image",
                user_id=self._room.user_id,
                room_id=self._room.id,
                usage_sink=ctx.usage_sink,
            ),
            log_subject=ctx.log_subject,
        )

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        result.judged_cell_id = self._cell_id


class SituationalImageJudgment:
    """캐릭터 상황별 이미지 판정. 후보 조회 실패는 `_load_situational_candidates` 가 흡수하고, 준비의 렌더 실패와 판정
    LLM 실패는 흡수하지 않는다(부르는 쪽 `except` 가 받는다)."""

    wave = 1

    def __init__(self, db: AsyncSession, room: ChatRoom) -> None:
        self._db = db
        self._room = room
        self._judgment: _SituationalImageJudgment | None = None
        self._matched: SituationalImage | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        self._judgment = await _prepare_situational_image_judgment(
            self._db,
            self._room,
            prompt_set=ctx.prompt_sets.image[0],
            prompt_sections=ctx.prompt_sets.image[1],
            history=ctx.history,
            user_message=ctx.user_message,
            assistant_message=ctx.assistant_message,
            names=ctx.names,
        )

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        if self._judgment is None:
            return
        self._matched = await _judge_situational_image(llm_client, self._judgment, self._room, ctx.usage_sink)

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        result.matched_image = self._matched


class PreviewStatJudgment:
    """미리보기 스탯 규칙 판정 — `StatJudgment` 의 초안판. 스탯 정의·규칙은 초안에서, 지금 값은 세션에서 읽는다(DB 읽기
    없음). 최초 엔딩 전에만 돈다. 준비의 렌더 실패는 방 판정처럼 흡수해(경고는 부르는 쪽이 넘긴 로거로) 스탯·엔딩 판정만
    건너뛰고 칸 판정은 그대로 돈다. LLM 실패는 `_await_stat_judgment` 가 흡수해 엔딩 판정도 건너뛴다. 스탯 행이 없어
    `stat_rows` 는 비워 둔다."""

    wave = 1

    def __init__(
        self,
        setup: StartingSetupDraftItem,
        stats: dict[str, float],
        *,
        ending_reached: bool,
        user_id: uuid.UUID,
        log: logging.Logger,
    ) -> None:
        self._setup = setup
        self._current_stats = stats
        self._ending_reached = ending_reached
        self._user_id = user_id
        self._log = log
        self._stat_defs: list[StatDef] = []
        self._request: StatJudgmentRequest | None = None
        self._updated: dict[str, float] | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        if self._ending_reached:
            return
        self._stat_defs = [_preview_stat_def(stat_def) for stat_def in self._setup.stat_defs]
        self._request = _prepare_stat_request(
            ctx,
            self._stat_defs,
            {stat_def.id: _preview_stat_rules(stat_def) for stat_def in self._setup.stat_defs},
            log=self._log,
        )

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        if self._request is None:
            return
        self._updated = await _await_stat_judgment(
            llm_client,
            self._request,
            LLMCallContext(call_site="preview_stat_judgment", user_id=self._user_id, room_id=None),
            log_subject=ctx.log_subject,
            current_stats=self._current_stats,
            stat_defs=self._stat_defs,
        )

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        _apply_stat_result(ctx, result, self._current_stats, self._updated)


class PreviewEndingJudgment:
    """미리보기 엔딩 판정 — `EndingJudgment` 의 초안판. 엔딩·규칙은 초안에서 읽고 요약이 없다(빈 요약으로 판정한다). 읽을
    DB 가 없어 판정 차례와 규칙 변환까지 `judge` 에서 한다. 렌더·LLM 실패는 흡수하지 않는다(방 엔딩 판정과 같다).

    발동한 엔딩의 이벤트는 에필로그의 이름 형태 태그를 칸 id 형태로 바꿔 싣는다 — 미리보기에는 커밋 뒤 조회가 없어 반영
    단계에서 만든다."""

    wave = 2

    def __init__(
        self,
        setup: StartingSetupDraftItem,
        payload: StoryDraftPayload,
        media_images: dict[uuid.UUID, MediaTagImage],
        *,
        user_id: uuid.UUID,
    ) -> None:
        self._setup = setup
        self._payload = payload
        self._media_images = media_images
        self._user_id = user_id
        self._reached: EndingDraftItem | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        return None

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        # 실채팅과 같은 순서 함수로 판정 차례·규칙 통과 엔딩의 판정 순서를 정한다.
        if ctx.stat_after is None:
            return
        for ending in _endings_to_judge(
            [
                (
                    ending,
                    ending.id,
                    ending.priority_stat_id,
                    [preview_ending_rule_list_item(item) for item in ending.stat_rules],
                )
                for ending in self._setup.endings
                if is_ending_check_due(ctx.turn, ending.turn_count_gate)
            ],
            ctx.stat_after,
            log_subject=ctx.log_subject,
        ):
            ending_judgment_prompt = build_ending_judgment_prompt(
                prompt_set=ctx.prompt_sets.ending[0],
                sections=ctx.prompt_sets.ending[1],
                judgment_prompt=ending.judgment_prompt,
                history=ctx.history,
                user_message=ctx.user_message,
                assistant_message=ctx.assistant_message,
                memory_summary="",
                names=ctx.names,
            )
            ending_judgment = await llm_client.generate_structured(
                ending_judgment_prompt,
                EndingJudgmentResult,
                usage=LLMCallContext(call_site="preview_ending_judgment", user_id=self._user_id, room_id=None),
            )
            if not ending_judgment.triggered:
                continue
            self._reached = ending
            break

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        if self._reached is None:
            return
        result.ending_reached_event = _preview_ending_reached_event(
            self._payload, self._media_images, self._reached.id, self._reached.epilogue
        )


class PreviewMediaCellJudgment:
    """미리보기 미디어 북 칸 판정 — `MediaCellJudgment` 의 초안판. 엔딩 여부·시작설정 유무와 무관하게 돈다. 준비와 판정이
    자기 실패를 전부 흡수해 그림만 포기한다. 노출(보관함 해금)은 기록하지 않는다."""

    wave = 1

    def __init__(
        self,
        payload: StoryDraftPayload,
        media_images: dict[uuid.UUID, MediaTagImage],
        *,
        user_id: uuid.UUID,
        log: logging.Logger,
    ) -> None:
        self._payload = payload
        self._media_images = media_images
        self._user_id = user_id
        self._log = log
        self._judgment: _MediaCellJudgment | None = None
        self._cell_id: uuid.UUID | None = None

    async def prepare(self, ctx: JudgmentContext) -> None:
        self._judgment = _prepare_preview_media_cell_judgment(
            self._payload,
            self._media_images,
            prompt_set=ctx.prompt_sets.image[0],
            prompt_sections=ctx.prompt_sets.image[1],
            history=ctx.history,
            user_message=ctx.user_message,
            assistant_message=ctx.assistant_message,
            names=ctx.names,
            log=self._log,
        )

    async def judge(self, llm_client: LLMClient, ctx: JudgmentContext) -> None:
        if self._judgment is None:
            return
        self._cell_id = await _judge_media_cell(
            llm_client,
            self._judgment,
            LLMCallContext(call_site="preview_media_book_image", user_id=self._user_id, room_id=None),
            log_subject=ctx.log_subject,
        )

    def apply(self, ctx: JudgmentContext, result: TurnJudgmentResult) -> None:
        result.judged_cell_id = self._cell_id


def new_turn_judgments(
    db: AsyncSession, room: ChatRoom, setup: StartingSetup | None, *, log: logging.Logger
) -> list[TurnJudgment]:
    """새 턴이 할 판정과 그 준비 순서. 스토리는 스탯 → 엔딩 → 칸 순으로 준비하고 스탯·칸을 함께 부른 뒤 엔딩을
    부른다(함께 부르는 순서도 이 목록 순서다). 캐릭터는 상황 이미지 하나다. 판정은 요청 세션(`db`)으로 방을 읽는다.
    `log` 는 스탯·엔딩 준비 실패 경고의 로거다."""
    if setup is not None:
        return [
            StatJudgment(db, room, setup, log=log),
            EndingJudgment(db, room, setup, log=log),
            MediaCellJudgment(db, room),
        ]
    return [SituationalImageJudgment(db, room)]


def regenerate_judgments(
    db: AsyncSession,
    room: ChatRoom,
    setup: StartingSetup | None,
    replaced_message_id: uuid.UUID,
    *,
    log: logging.Logger,
) -> list[TurnJudgment]:
    """재생성이 할 판정과 그 준비 순서. 스토리는 스탯 재판정 → 칸 순으로 준비하고 둘을 함께 부른다. 스탯은 바꾸는 응답의 턴
    효과를 되돌린 값에서 다시 판정하되 그럴 수 있는 턴에서만 한다(`RegenerateStatJudgment`). 엔딩 판정은 하지 않는다. 그림
    판정은 다시 한다 — 노출 기록은 첫 노출만 남겨 멱등이라 중복이 생기지 않고, 새 응답 글에 맞는 그림이 붙는다. 스토리 칸
    판정은 엔딩 뒤에도 한다(새 턴과 같다). 캐릭터는 상황 이미지 하나다. `log` 는 스탯 재판정 준비 실패 경고의 로거다."""
    if setup is not None:
        return [RegenerateStatJudgment(db, room, setup, replaced_message_id, log=log), MediaCellJudgment(db, room)]
    return [SituationalImageJudgment(db, room)]


def preview_judgments(
    state: PreviewSessionState,
    media_images: dict[uuid.UUID, MediaTagImage],
    user_id: uuid.UUID,
    *,
    log: logging.Logger,
) -> list[TurnJudgment]:
    """미리보기 턴이 할 판정과 그 준비 순서 — 새 턴과 같은 순서(스탯 → 엔딩 → 칸 준비, 스탯·칸을 함께 부른 뒤 엔딩)다.
    스토리 초안은 첫 시작설정으로 판정하고(미리보기는 그 시작설정으로만 시작한다), 시작설정이 없으면 칸 판정만 한다.
    캐릭터 초안은 판정이 없다(상황 이미지 매칭은 미리보기에서 돌지 않는다).

    스탯의 지금 값과 엔딩 도달 여부는 여기서 세션을 읽어 둔다 — 판정은 세션을 읽지 않고, 세션은 판정 뒤 쓰기 단계에서만
    바뀐다. `log` 는 스탯 준비 실패와 칸 판정 프롬프트 렌더 경고의 로거다."""
    payload = state.payload
    if isinstance(payload, CharacterDraftPayload):
        return []
    judgments: list[TurnJudgment] = []
    setup = payload.starting_setups[0] if payload.starting_setups else None
    if setup is not None:
        judgments += [
            PreviewStatJudgment(
                setup, dict(state.stats), ending_reached=state.ending_reached, user_id=user_id, log=log
            ),
            PreviewEndingJudgment(setup, payload, media_images, user_id=user_id),
        ]
    judgments.append(PreviewMediaCellJudgment(payload, media_images, user_id=user_id, log=log))
    return judgments
