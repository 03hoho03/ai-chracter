"""채팅 턴 하나의 골격 — 생성 스트림 → 판정 → 쓰기 → 커밋 뒤 표시 → 사후 이벤트.

보내기(`send_message`)·수정(`edit_message`)·재생성(`regenerate_message`)·빌더 미리보기(`send_preview_message`)가 같은
`run_turn` 을 지난다. 보내기와 수정은 실제로는 같은 "새 턴"이고, 차이는 라우트가 그 앞에서 하는 선행 작업(새 사용자 메시지
커밋 / 되감기·절단·편집 커밋)과 넘기는 히스토리·단축어뿐이다. 재생성은 같은 턴의 마지막 응답을 바꾸는 것이라 판정 목록(그림
판정만)과 저장소(옛 응답을 지우고 바꿔 넣으며 `turn_count` 를 올리지 않는다)가 다르고, 커밋 뒤 사후 작업(요약 접기 예약)이
없다. 미리보기는 방이 없는 새 턴이다 — 판정 입력을 초안 페이로드에서 읽고(미리보기판 판정), 턴을 DB 대신 미리보기 세션
상태에 쓴다(`PreviewTurnStore`). 세션을 Redis 에 저장하는 것은 라우트가 이 골격이 끝난 뒤에 한다. 생성 프롬프트는 라우트가
조립해 `TurnInput` 에 싣는다 — 조립 입력이 경로마다 달라서다(재생성은 마지막 응답을 뺀 히스토리, 미리보기는 초안 페이로드).
조립이 실패하면 라우트가 그 자리에서 오류로 끝내고 이 골격에는 들어오지 않는다.

방(또는 미리보기 세션)에 무엇을 언제 쓰는지는 저장소(`TurnStore`, `chat/turn_store.py` 의 `RoomTurnStore`·`PreviewTurnStore`)가
정하고, 이 모듈은 단계의 순서·예외 범위·이벤트 순서만 정한다. 이 모듈은 라우터를 import 하지 않는다(라우터가 이 모듈을
import 한다)."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from api.chat.prompt_builder import PromptRenderError
from api.chat.schemas import (
    ChatDoneEvent,
    ChatEndingReachedEvent,
    ChatErrorEvent,
    ChatMessageResponse,
    ChatPolicyWarningEvent,
    ChatStreamEvent,
    ChatTokenEvent,
)
from api.chat.turn_judgments import JudgmentContext, TurnJudgment, TurnJudgmentResult, _llm_dependency_tag
from api.chat.turn_prompt import GenerationPrompt
from api.chat.turn_settlement import TurnSettlement
from api.content.schemas import MediaTagImage
from api.core.config import settings
from api.core.rate_limit_gate import ChatCharge
from api.core.sentry import capture_dependency_failure
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatRoom
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import ChatModelId
from api.llm.client import (
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
)
from api.llm.routing import resolve_backend

_POLICY_WARNING_MESSAGE = "메시지 생성이 콘텐츠 정책에 의해 중단되었습니다."
# 문구의 유일한 자리. 턴 골격은 `_policy_warning_message`로만 고른다.
_PERSONA_POLICY_WARNING_MESSAGE = f"{_POLICY_WARNING_MESSAGE} 대화 프로필 내용이 원인일 수 있어요."
_NOTE_POLICY_WARNING_MESSAGE = f"{_POLICY_WARNING_MESSAGE} 기억 노트 내용이 원인일 수 있어요."
_PERSONA_AND_NOTE_POLICY_WARNING_MESSAGE = (
    f"{_POLICY_WARNING_MESSAGE} 대화 프로필이나 기억 노트 내용이 원인일 수 있어요."
)
_GENERATION_ERROR_MESSAGE = "메시지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."


def _policy_warning_message(persona_description_rendered: bool, note_rendered: bool) -> str:
    """그 턴 생성 프롬프트에 대화 프로필·기억 노트 섹션이 실제로
    들어갔을 때만(`user_persona_rendered`·`memory_note_rendered`) 그 안내를 붙이고, 둘 다면 한 문장으로
    합친다. 프로필은 설명이 있을 때만 안내한다 — 이름은 거의 모두가 정하므로 이름만으로 붙이면 거의 모든 차단에 붙는다.
    원인이 그것인지는 알 수 없어서 "~일 수 있다"로 쓴다. 요약은 대화에서 나온 것이라 안내에
    넣지 않는다. 턴 골격의 `yield ChatPolicyWarningEvent` 가 모든 경로에서 이것으로 고른다(미리보기는 노트가 없어
    `note_rendered` 가 늘 거짓)."""
    if persona_description_rendered and note_rendered:
        return _PERSONA_AND_NOTE_POLICY_WARNING_MESSAGE
    if persona_description_rendered:
        return _PERSONA_POLICY_WARNING_MESSAGE
    if note_rendered:
        return _NOTE_POLICY_WARNING_MESSAGE
    return _POLICY_WARNING_MESSAGE


def _dump_prompt(
    *,
    room_id: uuid.UUID | None,
    call_site: LLMCallSite,
    model: ChatModelId,
    turn: int,
    prompt: str,
    system_instruction: str,
) -> None:
    """회차 재현용으로 조립된 프롬프트를 JSONL 한
    줄로 남긴다. 호출부는 `settings.prompt_dump_path is not None`일 때만 부른다.

    바닥 지시문도 함께 남긴다 — 실험에서 바꿔 가며 비교하는 것이 바로 그것이라, 대화록만 남고 그때
    어떤 지시문이 실렸는지 모르면 회차를 나중에 설명할 수 없다. 모델은 고른 모델(`chatModel`)과 실제로 보낸 모델 id
    (`model`)를 함께 남기고, 시드는 Gemini 만 받는 설정이라 Gemini 턴에만 적는다. 보낸 id 는 라우터와 같은 해석
    (`resolve_backend`)으로 얻는다 — 호출 위치의 배정으로 구현이 바뀌면 그 구현의 id 다."""
    record = {
        "roomId": str(room_id) if room_id is not None else None,
        "turn": turn,
        "chatModel": model,
        "model": resolve_backend(call_site, model)[1],
        "seed": settings.gemini_seed if model == "gemini" else None,
        "systemInstruction": system_instruction,
        "prompt": prompt,
    }
    assert settings.prompt_dump_path is not None
    with open(settings.prompt_dump_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _stream_generated_tokens(
    llm_client: LLMClient,
    prompt: str,
    chunks: list[str],
    system_instruction: str,
    user_label: str,
    *,
    usage: LLMCallContext,
    turn: int,
    log: logging.Logger,
) -> AsyncIterator[ChatTokenEvent]:
    """`llm_client.generate()`의 각 델타를 그대로 relay하며 호출부가 넘긴 빈 리스트 `chunks`에
    누적한다 — 제너레이터는 반환값과 yield를 동시에 쓸 수 없어, 스트림 종료 후 조립할 전체
    텍스트를 이 out-param으로 호출부에 넘긴다.

    바닥 지시문은 호출부가 골라 넘긴다(`system_instruction_for`) — 여기서 고를 수 없다.
    스토리/캐릭터 구분이 실제 방·미리보기에서 서로 다른 값(`setup`/`payload` 타입)으로
    드러나기 때문이다. `stop_sequences`는 `user_label`에서 파생한다 — 이 함수가 실채팅·미리보기 공용이라 한 번만 고치면 둘 다 덮인다.

    진입부에서 `settings.prompt_dump_path`가 설정돼 있으면(기본값 None, 프로덕션 방어) 조립된
    프롬프트와 그때 실린 지시문을 그 파일에 덤프한다. **덤프 실패는 절대 스트림을
    막지 않는다** — SSE 제너레이터 본문에서 새 예외가 새면 요청 스코프 DB 세션이 강제 종료돼
    무관한 다른 요청까지 500이 된다(apps/api/CLAUDE.md 의 SSE 스트리밍 절). 덤프 실패 경고는 부르는 쪽 로거(`log`)로
    남긴다(`run_turn` 의 같은 이유)."""
    if settings.prompt_dump_path is not None:
        try:
            _dump_prompt(
                room_id=usage.room_id,
                call_site=usage.call_site,
                model=usage.model,
                turn=turn,
                prompt=prompt,
                system_instruction=system_instruction,
            )
        except Exception:
            log.warning("프롬프트 덤프 실패 (room=%s, turn=%s)", usage.room_id, turn, exc_info=True)
    async for delta in llm_client.generate(
        prompt, system_instruction, stop_sequences=[f"\n{user_label}:"], usage=usage
    ):
        chunks.append(delta)
        yield ChatTokenEvent(delta=delta)


def _turn_message_response(
    message: ChatMessage,
    matched_image: SituationalImage | None,
    matched_image_url: str | None,
    judged_cell_id: uuid.UUID | None,
    judged_cell_image: MediaTagImage | None,
) -> ChatMessageResponse:
    """턴(새 턴·재생성)의 `done.finalMessage`. 스토리 칸은 원본 비율로 그리게 너비·높이를 싣고, 캐릭터 상황별
    이미지는 싣지 않는다(지금의 고정 비율 칸 그대로). 칸 그림을 서명하지 못했으면 이미지 없이 보낸다 —
    상황별 이미지 URL 조립 실패와 같은 규칙이다."""
    if judged_cell_id is not None and judged_cell_image is not None:
        return ChatMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            image_id=judged_cell_id,
            image_url=judged_cell_image.url,
            image_width=judged_cell_image.width,
            image_height=judged_cell_image.height,
        )
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        image_id=matched_image.entity_id if matched_image is not None else None,
        image_url=matched_image_url,
    )


TurnKind = Literal["send", "edit", "regenerate", "preview"]

# 생성 호출의 호출 위치. 미리보기는 방이 없는 턴이라 사용량·라우팅에서 실채팅과 갈라 본다.
_GENERATE_CALL_SITE: dict[TurnKind, LLMCallSite] = {
    "send": "chat_generate",
    "edit": "chat_generate",
    "regenerate": "chat_generate",
    "preview": "preview_generate",
}
# 경로별 경고 문구. 재생성·미리보기는 원래 자기 라우트 안에서 자기 문구로 남겼고(재생성은 "재생성" 이 들어가고, 미리보기는
# 방 id 없이 "미리보기" 로 시작한다), 그 문장을 그대로 지킨다 — 로그와 Bugsink breadcrumb 를 문구로 찾는 쪽이 골격으로 옮긴
# 뒤에도 같은 문장을 읽는다. 포맷 문자열 자체를 경로마다 따로 둬야 기록의 메시지 틀과 인자가 옮기기 전과 같다(방 경로는
# 방 id 가 첫 인자이고, 미리보기에는 그 인자가 없다).
_GENERATION_FAILURE_LOG: dict[TurnKind, str] = {
    "send": "대화방 %s 메시지 생성 실패: %s",
    "edit": "대화방 %s 메시지 생성 실패: %s",
    "regenerate": "대화방 %s 응답 재생성 실패: %s",
    "preview": "미리보기 메시지 생성 실패: %s",
}
_JUDGMENT_FAILURE_LOG: dict[TurnKind, str] = {
    "send": "대화방 %s 판정 실패 — 이번 턴의 판정을 건너뛴다: %s",
    "edit": "대화방 %s 판정 실패 — 이번 턴의 판정을 건너뛴다: %s",
    "regenerate": "대화방 %s 재생성 이미지 매칭 실패 — 이번 재생성의 매칭을 건너뛴다: %s",
    "preview": "미리보기 판정 실패 — 이번 턴의 판정을 건너뛴다: %s",
}
# 방 경로에서 판정 헬퍼가 자기 경고 앞에 붙이는 주어(`JudgmentContext.log_subject`)의 꼬리. 미리보기의 주어는 "미리보기" 다.
_JUDGMENT_LOG_SUBJECT_SUFFIX: dict[TurnKind, str] = {"send": "", "edit": "", "regenerate": " 재생성"}


@dataclass(frozen=True)
class TurnInput:
    """한 턴을 돌리는 데 필요한 값. 라우트가 선행 작업과 생성 프롬프트 조립을 끝낸 뒤 만든다."""

    kind: TurnKind
    # 미리보기는 방이 없다.
    room: ChatRoom | None
    # 생성·판정 호출을 귀속할 사용자(방 경로는 방 주인).
    user_id: uuid.UUID
    # 생성·판정이 보는 이번 입력 앞까지의 메시지.
    history: list[ChatMessage]
    user_content: str
    generation: GenerationPrompt
    # 생성 프롬프트를 조립한 세트 — 정지 시퀀스의 사용자 라벨을 여기서 읽는다.
    generation_set: PromptSet
    # 판정(과 요약 접기)은 고른 모델과 무관하게 Gemini 세트로 한다.
    judgment_set: PromptSet
    judgment_sections: list[PromptSection]
    # 생성 호출의 모델을 정한다.
    charge: ChatCharge


@dataclass
class TurnResult:
    """한 턴(새 턴이나 재생성)이 만든 것 — 생성된 글과 판정이 고른 그대로의 결과. 쓰기·표시 단계에서 노출 기록·서명 실패로 그림을 버린
    결과는 여기 넣지 않고 `TurnWrite`·`TurnPresentation` 에 둔다. "판정이 고른 것"과 "실제로 보여 준 것"을 섞지 않아야,
    나중에 턴마다 남기는 기록이 이 값을 그대로 원천으로 쓸 수 있다."""

    kind: TurnKind
    turn_number: int
    assistant_content: str
    # 생성 스트림이 끝난 시각. 미리보기 저장소가 응답 시각으로 쓴다(방은 쓰기 구간의 DB 시각을 쓴다).
    generated_at: datetime
    judgments: TurnJudgmentResult


@dataclass
class TurnWrite:
    """쓰기 구간이 실제로 저장한 것. 그림은 노출 기록이 실패하면 `None` 이다."""

    message: ChatMessage
    matched_image: SituationalImage | None
    judged_cell_id: uuid.UUID | None


@dataclass
class TurnPresentation:
    """커밋 뒤 화면에 실을 것 — 커밋 뒤 조회에서 흡수한 실패를 반영한 값이다."""

    # 상황 이미지 URL 을 만들지 못했으면 `None`.
    matched_image: SituationalImage | None
    matched_image_url: str | None
    judged_cell_image: MediaTagImage | None
    # 에필로그의 미디어 북 태그를 화면용으로 해석한 엔딩 이벤트.
    ending_reached_event: ChatEndingReachedEvent | None


class TurnStore(Protocol):
    """턴 골격이 방(또는 그 대신의 상태)에 닿는 자리. 골격은 이 네 멤버만 쓴다."""

    def turn_number(self) -> int:
        """이번 턴 번호(재생성은 바꾸는 응답의 턴 번호). 생성 전 반납 뒤에 읽는다."""
        ...

    async def release(self) -> None:
        """LLM 을 기다리기 전에 요청 세션의 트랜잭션을 반납한다."""
        ...

    async def write(self, turn: TurnResult, settlement: TurnSettlement) -> TurnWrite | None:
        """턴을 한 트랜잭션으로 쓰고 커밋한다. 쓸 곳이 사라졌으면 정산을 끝낸 뒤 `None` 이다. 응답이 저장돼 그 뒤로
        끊겨도 소모인 자리가 여기면 정산 표시를 여기서 세운다(방)."""
        ...

    async def present(self, turn: TurnResult, written: TurnWrite) -> TurnPresentation:
        """커밋 뒤 화면에 실을 그림·에필로그를 조립하고, 그 조회가 연 트랜잭션을 반납한다."""
        ...


async def run_turn(
    inp: TurnInput,
    *,
    llm: LLMClient,
    judgments: Sequence[TurnJudgment],
    store: TurnStore,
    settlement: TurnSettlement,
    after_commit: Callable[[TurnResult], None] | None,
    log: logging.Logger,
) -> AsyncIterator[ChatStreamEvent]:
    """생성 + 판정 + 쓰기까지 턴 하나(새 턴·재생성·미리보기)를 전부 실행한다. 캐릭터 챗은 상황별 이미지 매칭만, 스토리 챗은
    스탯 변경·엔딩 판정과 미디어 북 칸 판정을 한다(그림 결과는 둘 다 `chat_messages.image_id`에 저장돼 done 이벤트의
    finalMessage와 `GET /chat-rooms/{id}` 재조회 둘 다에 실린다 — 캐릭터는 상황별 이미지 entity_id, 스토리는 칸 entity_id).
    스토리 챗은 최초 엔딩 도달(room.ending_reached) 이후로 스탯·엔딩 판정이 멈추고 칸 판정만 계속한다 — 메시지 생성
    자체는 계속 허용. 어떤 판정을 어떤 차례로 할지는 `judgments` 목록이 정한다(새 턴은 `new_turn_judgments`, 재생성은
    그림 판정만 하는 `regenerate_judgments`, 미리보기는 초안에서 읽는 `preview_judgments`).

    LLM(생성·판정)을 기다리는 동안 요청 세션은 트랜잭션을 쥐지 않는다 — 쥐면 그동안 커넥션 하나를 통째로 점유해,
    동시에 진행할 수 있는 턴 수가 커넥션 풀 크기에 묶인다. 그래서 턴은 세 구간으로 나뉜다: ① 읽기(생성 프롬프트,
    판정 입력) → 반납 → ② LLM(생성 스트림, 판정) → ③ 쓰기(응답 메시지·turn_count·노출·스탯·엔딩을 한 트랜잭션으로).
    쓰기를 마지막 한 구간에 모으는 이유는 "응답 메시지와 판정 결과가 한 커밋"이라는 원자성을 지키려는 것이다 — 그래서
    응답 메시지의 `created_at` 은 판정이 끝난 시각이다. 같은 방의 다른 턴은 방 락이 막는다. 방 삭제는 락 대상이 아니라
    LLM 을 기다리는 사이 방이 사라질 수 있다 — 그때는 아무것도 쓰지 않고 오류 이벤트로 끝내며 환불하지 않는다(사용자가
    지웠고 LLM 은 이미 탔다).

    턴을 커밋하고 커밋 뒤 조회까지 반납한 다음 `after_commit` 을 부른다(보내기·수정은 요약 접기 예약, 재생성·미리보기는
    `None` 이라 부르지 않는다). 첫 사후 `yield`
    **앞**이다 — 그 뒤에 두면 `done`을 받고 연결을 끊은 클라이언트의 턴에서 예약 자체가 사라진다.

    경고 로그는 부르는 쪽 로거(`log`)로 남긴다 — 이 경고들은 원래 라우트 안에 있던 것이라, 로거 이름으로 거르는 쪽(Bugsink
    breadcrumb 범주, 경고의 로거 이름까지 기록한 테스트)이 옮긴 뒤에도 같은 이름으로 읽는다. 이 함수 안에는 await 하는 `finally`·`async with` 정리를 두지 않는다 — 끊긴 SSE 제너레이터는
    나중에 다른 태스크에서 닫히므로, 그런 정리는 요청 세션이 닫힌 뒤에 돈다."""
    room = inp.room
    # 방 경로의 경고는 방 id 를 첫 인자로 남기고, 미리보기는 그 인자가 없다(`_GENERATION_FAILURE_LOG` 의 같은 이유).
    room_log_args: tuple[uuid.UUID, ...] = (room.id,) if room is not None else ()
    generation = inp.generation
    # 생성 프롬프트에 필요한 읽기는 끝났다 — 생성 스트림을 기다리는 동안 커넥션을 쥐지 않게 반납한다.
    await store.release()

    next_turn = store.turn_number()
    chunks: list[str] = []
    try:
        async for token_event in _stream_generated_tokens(
            llm,
            generation.prompt,
            chunks,
            generation.system_instruction,
            inp.generation_set.user_label,
            usage=LLMCallContext(
                call_site=_GENERATE_CALL_SITE[inp.kind],
                user_id=inp.user_id,
                room_id=room.id if room is not None else None,
                model=inp.charge.model,
            ),
            turn=next_turn,
            log=log,
        ):
            yield token_event
    except LLMPolicyViolationError:
        # 환불하지 않는다 — 사용자 입력이 원인이고 LLM 을 실제로
        # 태웠다. 이미지 가드 차단이 환불되는 것과 결론이 갈리는 자리다.
        settlement.mark_settled()
        yield ChatPolicyWarningEvent(
            message=_policy_warning_message(generation.persona_description_rendered, generation.note_rendered)
        )
        return
    except LLMClientError as exc:
        log.warning(_GENERATION_FAILURE_LOG[inp.kind], *room_log_args, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))
        await settlement.refund()
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    assistant_content = "".join(chunks)
    generated_at = datetime.now(UTC)

    # 판정이 채우는 결과 — 쓰기 구간이 한꺼번에 쓴다(스탯 행·바뀐 스탯 값·도달한 엔딩·그림). `try` 앞에서 만들어, 판정
    # 도중 예외가 나도 그때까지 채운 결과는 쓰기 구간으로 간다.
    result = TurnJudgmentResult()
    ctx = JudgmentContext(
        prompt_set=inp.judgment_set,
        prompt_sections=inp.judgment_sections,
        history=inp.history,
        user_message=inp.user_content,
        assistant_message=assistant_content,
        names=generation.names,
        turn=next_turn,
        log_subject=f"대화방 {room.id}{_JUDGMENT_LOG_SUBJECT_SUFFIX[inp.kind]}" if room is not None else "미리보기",
    )
    # 판정 단계의 LLM 실패는 반드시 이 안에서 흡수한다 — 예외가 SSE 제너레이터 밖으로 새면
    # ASGI 태스크가 취소되면서 요청 스코프 DB 세션이 강제 종료되고, 망가진 asyncpg 커넥션이
    # 풀로 돌아가 그걸 집어간 **무관한 다른 요청**이 InterfaceError로 500이 난다(부하 실측).
    # 이미 응답은 스트리밍됐으니, 그 턴의 판정만 포기하고(그 전까지 나온 판정 결과는 그대로 쓴다)
    # 정상적으로 커밋 → done 이벤트까지 마무리하는 것이 실패의 폭발 반경을 그 턴에 가둔다.
    try:
        # 입력 읽기(방은 DB 읽기)는 전부 목록 순서대로 판정 LLM 앞(그리고 반납 앞)에서 하고, 쓰기는 전부 쓰기 구간이다.
        for judgment in judgments:
            await judgment.prepare(ctx)
        await store.release()

        # 첫 물결(스토리는 스탯·칸)은 동시에 부른다 — 둘 다 LLM 만 부르고 자기 LLM 실패를 흡수해 한쪽이 실패해도 다른 쪽
        # 결과가 남는다. 판정이 하나뿐이면(캐릭터의 상황 이미지) 묶지 않고 바로 기다린다.
        first_wave = [judgment for judgment in judgments if judgment.wave == 1]
        if len(first_wave) == 1:
            await first_wave[0].judge(llm, ctx)
        else:
            await asyncio.gather(*(judgment.judge(llm, ctx) for judgment in first_wave))
        # 두 번째 물결(엔딩) **앞**에서 반영한다 — 엔딩 판정이 실패해도 스탯 변화·칸 그림은 남는다.
        for judgment in first_wave:
            judgment.apply(ctx, result)
        # 엔딩은 스탯 반영 뒤 값으로 판정하므로 차례로 부른다.
        for judgment in judgments:
            if judgment.wave == 2:
                await judgment.judge(llm, ctx)
                judgment.apply(ctx, result)
    except (LLMClientError, PromptRenderError) as exc:
        log.warning(_JUDGMENT_FAILURE_LOG[inp.kind], *room_log_args, exc)
        capture_dependency_failure(exc, dependency=_llm_dependency_tag(exc))

    turn = TurnResult(
        kind=inp.kind,
        turn_number=next_turn,
        assistant_content=assistant_content,
        generated_at=generated_at,
        judgments=result,
    )
    # 쓰기 구간은 예외를 흡수하지 않는다 — 쓰기·커밋 실패는 제너레이터를 뚫고 정산 가드가 응답 행을 확인해 정산한다.
    written = await store.write(turn, settlement)
    if written is None:
        yield ChatErrorEvent(message=_GENERATION_ERROR_MESSAGE)
        return

    shown = await store.present(turn, written)

    if after_commit is not None:
        after_commit(turn)

    for stat_change_event in result.stat_change_events:
        yield stat_change_event

    if shown.ending_reached_event is not None:
        yield shown.ending_reached_event

    # `done` 을 내보내는 순간 응답이 확정된다 — 이 앞의 이벤트에서 끊기면 환급하고, `done` 에 멈춘 뒤 끊기면 소모다. 방은
    # 쓰기 구간의 커밋에서 이미 세웠으니 다시 세워도 같다. 미리보기는 DB 에 남기는 것이 없어 여기서 처음 선다 — 쓰기
    # 단계에서 세우면 `statChange`·`endingReached` 에서 끊긴 사용자의 차감이 소모로 바뀐다.
    settlement.mark_settled()
    yield ChatDoneEvent(
        final_message=_turn_message_response(
            written.message,
            shown.matched_image,
            shown.matched_image_url,
            written.judged_cell_id,
            shown.judged_cell_image,
        )
    )
