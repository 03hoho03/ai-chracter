"""실채팅 방에 턴을 쓰고, 커밋 뒤 화면에 실을 것을 조립하는 저장소(`RoomTurnStore`)와 그 헬퍼, 그리고 빌더 미리보기의
턴을 세션 상태에 쓰는 저장소(`PreviewTurnStore`).

턴 골격(`chat/turn_engine.py` 의 `run_turn`)이 단계의 순서를 정하고, 이 모듈은 각 단계에서 방에 무엇을 어떤 트랜잭션으로
쓰는지를 정한다. 헬퍼 중 칸 해금 기록은 방의 첫 메시지 삽입도 라우터에서 그대로 부른다. 이 모듈은 라우터를 import 하지
않는다(라우터가 이 모듈을 import 한다).

경고는 전부 부르는 쪽이 넘긴 로거(`log`)로 남긴다 — 이 경고들은 원래 라우터 안에 있던 것이라, 로거 이름으로 거르는
쪽(경고의 로거 이름까지 기록한 테스트, Bugsink breadcrumb 범주)이 옮긴 뒤에도 같은 이름(`api.chat.router`)으로
읽는다. 운영 stderr 로그 줄에는 로거 이름이 찍히지 않는다(앱에 로깅 설정이 없어 `logging.lastResort` 가 메시지만 낸다)."""

import logging
import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.chat.schemas import PreviewSessionState
from api.chat.turn_engine import TurnPresentation, TurnResult, TurnWrite, _turn_message_response
from api.chat.turn_settlement import TurnSettlement
from api.core.rate_limit_gate import ChatCharge
from api.content.media_book import normalize_texts, normalize_texts_for_display, resolve_media_tag_images
from api.content.media_tags import strip_media_tags
from api.content.schemas import MediaTagImage
from api.core.s3 import generate_presigned_get_url
from api.core.sentry import capture_dependency_failure
from api.db.models.chat import (
    CharacterImageExposure,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    ChatTurn,
    DiscardedResponse,
    StoryEndingUnlock,
    StoryMediaExposure,
)
from api.db.models.media import Asset
from api.db.models.story import StartingSetup

TurnStoreMode = Literal["append", "replace"]

# 커밋 뒤 상황 이미지 URL 조립 실패의 경고 문구. 재생성은 원래 자기 라우트 안에서 "재생성" 이 들어간 문구로 남겼고, 그
# 문장을 그대로 지킨다(턴 골격의 경로별 문구와 같은 이유).
_SITUATIONAL_URL_FAILURE_LOG: dict[TurnStoreMode, str] = {
    "append": "대화방 %s 상황이미지 URL 조립 실패 — 이미지 없이 진행한다: %s",
    "replace": "대화방 %s 재생성 상황이미지 URL 조립 실패 — 이미지 없이 진행한다: %s",
}


async def _lock_room_for_turn_write(db: AsyncSession, room: ChatRoom, *, log: logging.Logger) -> uuid.UUID | None:
    """턴 쓰기 구간의 첫 문장 — 방 행을 잠그고 아직 있는지 본다. 없으면(LLM 을 기다리는 사이 사용자가 방을 지웠다)
    경고를 남기고 트랜잭션을 반납한 뒤 `None` 이다. 호출부는 아무것도 쓰지 않고 오류 이벤트로 끝낸다 — 환불하지
    않는다(사용자가 지웠고 LLM 은 이미 탔다).

    `FOR NO KEY UPDATE` 라 응답 INSERT 의 외래 키 확인(KEY SHARE)과는 부딪히지 않고, 방 행을 고치는 다른 쓰기(요약 접기의
    버전 갱신, 방 삭제의 첫 UPDATE)와는 줄을 선다 — 쓰기 구간은 짧다."""
    room_id = await db.scalar(select(ChatRoom.id).where(ChatRoom.id == room.id).with_for_update(key_share=True))
    if room_id is None:
        log.warning("대화방 %s 이 응답을 만드는 사이 지워졌다 — 이번 턴은 저장하지 않는다", room.id)
        await db.commit()
    return room_id


def _write_room_stat(
    db: AsyncSession, room_id: uuid.UUID, stat_rows: dict[str, ChatRoomStat], stat_id: str, value: float
) -> None:
    """버전을 옮긴 방에는 새 버전에 생긴 스탯의 행이 없을 수 있다. 바뀐 값을 쓸 행이 없으면 만들어 쓴다."""
    row = stat_rows.get(stat_id)
    if row is None:
        row = ChatRoomStat(chat_room_id=room_id, stat_entity_id=uuid.UUID(stat_id), current_value=Decimal(str(value)))
        db.add(row)
        stat_rows[stat_id] = row
    else:
        row.current_value = Decimal(str(value))


async def _record_character_image_exposure(
    db: AsyncSession, room: ChatRoom, image_entity_id: uuid.UUID, *, log: logging.Logger
) -> bool:
    """첫 노출만 기록한다(멱등). 실패는 SAVEPOINT 안에 가두고 `False` — 그 턴은 이미지를 붙이지 않는다(판정은
    성공했는데 노출 기록만 실패한 경우도 매칭을 절반만 살려두지 않는다)."""
    try:
        async with db.begin_nested():
            existing_exposure = await db.scalar(
                select(CharacterImageExposure).where(
                    CharacterImageExposure.user_id == room.user_id,
                    CharacterImageExposure.content_id == room.content_id,
                    CharacterImageExposure.image_entity_id == image_entity_id,
                )
            )
            if existing_exposure is None:
                db.add(
                    CharacterImageExposure(
                        user_id=room.user_id,
                        content_id=room.content_id,
                        image_entity_id=image_entity_id,
                    )
                )
    except SQLAlchemyError as exc:
        log.warning("대화방 %s 이미지 노출 기록 실패 — 이번 턴은 매칭을 건너뛴다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return False
    return True


async def _record_story_media_exposure(
    db: AsyncSession, room: ChatRoom, cell_entity_id: uuid.UUID, *, log: logging.Logger
) -> bool:
    """보관함 해금 기록 — 사용자·스토리별로 처음 본 칸만 남는다(멱등, 겹친 두 턴도 복합 PK 충돌 없이). 실패는
    SAVEPOINT 안에 가두고 `False` — 그 턴은 칸을 붙이지 않는다(캐릭터 노출 기록과 같은 규칙)."""
    try:
        async with db.begin_nested():
            await db.execute(
                pg_insert(StoryMediaExposure)
                .values(user_id=room.user_id, content_id=room.content_id, cell_entity_id=cell_entity_id)
                .on_conflict_do_nothing()
            )
    except SQLAlchemyError as exc:
        log.warning("대화방 %s 미디어 북 칸 노출 기록 실패 — 이번 턴은 그림 없이 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")
        return False
    return True


async def _record_story_media_unlocks(db: AsyncSession, room: ChatRoom, cell_entity_ids: set[uuid.UUID]) -> None:
    """첫 메시지·에필로그에 나온 칸의 보관함 해금 기록. 메시지와 같은 트랜잭션에 쓰고, 이미 본 칸과 겹치면 그대로
    둔다(대화 초기화가 같은 첫 메시지를 다시 넣어도 실패하지 않는다)."""
    if not cell_entity_ids:
        return
    await db.execute(
        pg_insert(StoryMediaExposure)
        .values(
            [
                {"user_id": room.user_id, "content_id": room.content_id, "cell_entity_id": cell_entity_id}
                for cell_entity_id in cell_entity_ids
            ]
        )
        .on_conflict_do_nothing()
    )


async def _unlock_epilogue_cells(
    db: AsyncSession, room: ChatRoom, epilogue: str | None, *, log: logging.Logger
) -> None:
    """도달한 엔딩의 에필로그에 나온 칸을 해금한다. 스트림 본문에서 불리므로 실패는 SAVEPOINT 안에 가두고 기록만
    포기한다 — 엔딩 도달 자체는 그대로 남는다."""
    if not epilogue:
        return
    # SAVEPOINT 를 열면 세션이 먼저 flush 된다. 그때 터지는 것은 바로 앞의 엔딩 도달 기록이지 칸 해금이 아니다 —
    # 여기서 따로 flush 해 그 실패가 아래 경고로 잘못 기록되지 않게 한다(이 실패는 전처럼 커밋 실패와 같은 길을 간다).
    await db.flush()
    try:
        async with db.begin_nested():
            _, refs = await normalize_texts(db, room.content_version_id, [epilogue])
            await _record_story_media_unlocks(db, room, refs)
    except SQLAlchemyError as exc:
        log.warning("대화방 %s 에필로그 칸 해금 기록 실패 — 엔딩은 그대로 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="db")


async def _sign_judged_cell(
    db: AsyncSession, room: ChatRoom, cell_entity_id: uuid.UUID, *, log: logging.Logger
) -> MediaTagImage | None:
    """커밋 뒤 판정 칸의 그림을 서명한다(원본, 너비·높이). 방 버전에서 칸·자산을 못 찾거나 서명이 실패하면
    `None` — 커밋 뒤라 예외가 새면 SSE 제너레이터를 뚫으므로 전부 흡수하고 그림 없이 마무리한다.
    `fold_memory` 예약 **앞**에서 부른다(예약 뒤에는 요청 세션 쿼리를 더하지 않는다)."""
    try:
        images = await resolve_media_tag_images(db, room.content_version_id, [cell_entity_id])
    except Exception as exc:
        log.warning("대화방 %s 미디어 북 칸 URL 조립 실패 — 그림 없이 진행한다: %s", room.id, exc)
        capture_dependency_failure(exc, dependency="s3")
        return None
    return images.get(cell_entity_id)


class RoomTurnStore:
    """실채팅 방의 턴 저장소. `mode="append"` 는 새 턴을 덧붙인다(보내기·수정) — 응답 메시지를 새로 넣고 `turn_count` 를
    하나 올린다. `mode="replace"` 는 재생성이다 — 같은 턴의 마지막 응답(`replaced_message_id`)을 지우고 새 응답으로 바꿔
    넣으며, 응답이 실제로 지워졌다는 폐기 기록을 같은 트랜잭션에 남긴다. 턴 번호는 지금 `turn_count` 그대로이고 올리지
    않는다. 노출 기록·그림·커밋·정산과 커밋 뒤 표시는 두 모드가 같다.

    턴 기록(`chat_turns`)도 응답과 같은 커밋에 쓴다 — 응답이 저장됐는데 기록이 없거나, 응답 없이 기록만 남는 턴이 생기지
    않는다. append 는 이 턴의 값으로 한 행을 쓴다. replace 는 바꾸는 응답의 기록이 있을 때만 한 행을 쓰고, 모델·차감·LLM 호출은
    이 재생성의 것, 턴 번호·엔딩·단축어는 그 기록의 값 그대로다. 스탯 변화는 재생성이 스탯을 다시 판정했으면 그 결과(턴이 시작할
    때의 값 대비)이고, 아니면(재판정 조건을 못 채웠거나 재판정이 끝내 실패했다) 그 기록의 값 그대로다 — 그때 방에 남아 있는
    효과는 원 턴의 것이고, 그 효과를 이 응답에 귀속해 두어야 다음 재생성이 무엇을 되돌릴지 안다. 엔딩은 재생성이 판정하지 않으므로
    늘 이어받는다. 턴 번호를 이어받는
    것은 메시지 삭제로 앞 응답이 마지막이 된 방에서 재생성의 턴 번호(지금 `turn_count`)가 그 응답의 턴보다 크기 때문이다.
    바꾸는 응답에 기록이 없으면(기록을 쓰기 전에 보낸 턴) 쓰지 않는다 — 빈 효과로 쓰면 "원 턴이 아무것도 바꾸지 않았다"와
    구별되지 않는다. 바꾼 응답의 옛 기록은 지우지 않는다(그 호출의 원가도 실제로 났다).

    트랜잭션 반납은 `commit()` 이다 — 읽기만 한 트랜잭션이라 끝내기만 하고, `expire_on_commit=False` 라 읽어 둔 객체를
    그대로 쓴다(`rollback()` 은 객체를 만료시켜 다음 속성 접근이 실패한다)."""

    def __init__(
        self,
        db: AsyncSession,
        room: ChatRoom,
        setup: StartingSetup | None,
        *,
        mode: TurnStoreMode,
        replaced_message_id: uuid.UUID | None = None,
        shortcut_entity_id: uuid.UUID | None = None,
        log: logging.Logger,
    ) -> None:
        # 바꿀 응답은 replace 에만 있고 replace 에는 반드시 있다 — 어긋나면 append 가 남의 응답을 지우거나 replace 가 지울
        # 것 없이 응답을 하나 더 넣는다.
        assert (mode == "replace") == (replaced_message_id is not None)
        self.db = db
        self._log = log
        self._room = room
        self._setup = setup
        self._mode = mode
        self._replaced_message_id = replaced_message_id
        # 보내기에서 고른 단축어. 재생성은 바꾸는 응답의 기록에서 이어받으므로 넘기지 않는다.
        self._shortcut_entity_id = shortcut_entity_id

    def turn_number(self) -> int:
        if self._mode == "replace":
            # 재생성은 같은 턴의 응답을 바꾸는 것이라 턴 번호가 그대로다.
            return self._room.turn_count
        return self._room.turn_count + 1

    async def release(self) -> None:
        await self.db.commit()

    async def write(self, turn: TurnResult, settlement: TurnSettlement) -> TurnWrite | None:
        """쓰기 구간. 방 행을 먼저 잠그며 존재를 확인한다 — 쓰기 구간끼리(요약 접기의 버전 갱신 포함) 줄을 서고, LLM 을
        기다리는 사이 방이 지워졌으면 응답 INSERT 가 외래 키 위반으로 제너레이터를 뚫기 전에 갈라진다. 그 밖의 쓰기·커밋
        실패는 흡수하지 않는다.

        append 는 새 응답을 넣고 flush 해 id 를 얻은 뒤 `turn_count` 를 올린다. replace 는 옛 응답 DELETE → 폐기 기록 →
        미리 정한 id 의 새 응답 순서이고 flush 하지 않는다(재생성이 원래 쓰던 모양 그대로다). 그 뒤 노출 기록·스탯·엔딩·그림·
        커밋은 두 모드가 같은 코드를 지난다 — 재생성은 엔딩 판정을 하지 않아 그 칸이 비어 있고, 스탯 칸은 재판정했을 때만 찬다(되돌린
        값과 새 값이 함께 들어 있다)."""
        db, room, setup = self.db, self._room, self._setup
        result = turn.judgments
        # 노출 기록 실패 때 그림을 `None` 으로 덮으므로 지역 이름으로 읽는다(판정 결과는 그대로 둔다).
        matched_image = result.matched_image
        judged_cell_id = result.judged_cell_id

        if await _lock_room_for_turn_write(db, room, log=self._log) is None:
            settlement.mark_settled()
            return None

        # 바꾸는 응답의 기록은 그 응답을 지우기 전에, 아직 아무것도 쓰지 않은 자리에서 읽는다.
        replaced_record = (
            await db.scalar(select(ChatTurn).where(ChatTurn.assistant_message_id == self._replaced_message_id))
            if self._replaced_message_id is not None
            else None
        )

        if self._replaced_message_id is None:
            assistant_message = ChatMessage(
                chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=turn.assistant_content
            )
            db.add(assistant_message)
            await db.flush()
            # 여기부터 아래 커밋이 돌아올 때까지 끊기면 응답이 저장됐는지 알 수 없다 — 정산이 응답 행을 직접 확인한다.
            settlement.set_pending_message(db, room.id, assistant_message.id)
            room.turn_count = turn.turn_number
        else:
            await db.execute(delete(ChatMessage).where(ChatMessage.id == self._replaced_message_id))
            # 옛 응답 DELETE 와 같은 트랜잭션이라 응답이 실제로 지워진 재생성만 센다 — 렌더 실패·정책 위반·LLM 오류는 이
            # 쓰기 구간에 오기 전에 옛 응답을 남긴 채 끝나므로 기록되지 않는다.
            db.add(DiscardedResponse(user_id=room.user_id, chat_room_id=room.id, kind="regenerate", discarded_count=1))
            # id 를 여기서 정한다 — 컬럼 기본값(`uuid4`)은 flush 때에야 채워지는데, 정산은 커밋 전에 이 id 를 알아야 한다.
            assistant_message = ChatMessage(
                id=uuid.uuid4(), chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=turn.assistant_content
            )
            db.add(assistant_message)
            # 여기부터 아래 커밋이 돌아올 때까지 끊기면 응답이 저장됐는지 알 수 없다(위 append 의 같은 자리). 턴 수는
            # 올리지 않는다.
            settlement.set_pending_message(db, room.id, assistant_message.id)

        if judged_cell_id is not None and not await _record_story_media_exposure(
            db, room, judged_cell_id, log=self._log
        ):
            judged_cell_id = None
        if matched_image is not None and not await _record_character_image_exposure(
            db, room, matched_image.entity_id, log=self._log
        ):
            matched_image = None

        for stat_id, new_value in result.stat_writes.items():
            _write_room_stat(db, room.id, result.stat_rows, stat_id, new_value)

        reached_ending = result.reached_ending
        if reached_ending is not None:
            assert setup is not None  # 엔딩은 스토리 방에만 있다.
            room.ending_reached = True
            room.ending_entity_id = reached_ending.entity_id
            room.ending_reached_at_turn = turn.turn_number

            existing_unlock = await db.scalar(
                select(StoryEndingUnlock).where(
                    StoryEndingUnlock.user_id == room.user_id,
                    StoryEndingUnlock.starting_setup_entity_id == setup.entity_id,
                    StoryEndingUnlock.ending_entity_id == reached_ending.entity_id,
                )
            )
            if existing_unlock is None:
                db.add(
                    StoryEndingUnlock(
                        user_id=room.user_id,
                        starting_setup_entity_id=setup.entity_id,
                        ending_entity_id=reached_ending.entity_id,
                    )
                )
            await _unlock_epilogue_cells(db, room, reached_ending.epilogue, log=self._log)

        if matched_image is not None:
            assistant_message.image_id = matched_image.entity_id
        elif judged_cell_id is not None:
            assistant_message.image_id = judged_cell_id

        self._add_turn_record(turn, settlement.charge, assistant_message.id, replaced_record)

        await db.commit()
        # 응답이 저장됐다 — 이 뒤로 끊겨도 차감은 소모다.
        settlement.mark_settled()
        return TurnWrite(message=assistant_message, matched_image=matched_image, judged_cell_id=judged_cell_id)

    def _add_turn_record(
        self,
        turn: TurnResult,
        charge: ChatCharge,
        assistant_message_id: uuid.UUID,
        replaced_record: ChatTurn | None,
    ) -> None:
        """쓰기 구간 안에서 턴 기록 한 행을 더한다(규칙은 클래스 설명). 차감은 이 턴의 정산이 쥔 영수증이다. 커밋은 부르는
        쪽의 것이다."""
        record = ChatTurn(
            chat_room_id=self._room.id,
            assistant_message_id=assistant_message_id,
            chat_model=charge.model,
            charge_source=charge.source,
            clover_amount=charge.clover_amount,
            spend_ledger_id=charge.spend_ledger_id,
            llm_calls=[call.as_record() for call in turn.llm_calls],
        )
        if self._replaced_message_id is None:
            assert turn.kind in ("send", "edit")
            reached_ending = turn.judgments.reached_ending
            record.kind = turn.kind
            record.turn_number = turn.turn_number
            record.stat_changes = turn.judgments.stat_changes
            record.ending_entity_id = reached_ending.entity_id if reached_ending is not None else None
            record.shortcut_entity_id = self._shortcut_entity_id
        else:
            if replaced_record is None:
                return
            record.kind = "regenerate"
            record.turn_number = replaced_record.turn_number
            record.stat_changes = (
                turn.judgments.stat_changes if turn.judgments.stats_rejudged else replaced_record.stat_changes
            )
            record.ending_entity_id = replaced_record.ending_entity_id
            record.shortcut_entity_id = replaced_record.shortcut_entity_id
        self.db.add(record)

    async def present(self, turn: TurnResult, written: TurnWrite) -> TurnPresentation:
        """커밋 뒤 조회(상황 이미지 URL·칸 서명·에필로그). 커밋 뒤라 여기서 예외가 새면 SSE 제너레이터를 뚫으므로 자리마다
        흡수하고 그림 없이 마무리한다. 끝에서 이 조회가 연 트랜잭션을 반납한다 — 요청 세션은 턴 뒤 background 일(요약
        접기의 LLM 호출)이 끝난 뒤에야 닫히므로, 반납하지 않으면 열린 트랜잭션이 그 내내 커넥션을 쥔다."""
        db, room = self.db, self._room
        matched_image = written.matched_image
        matched_image_url: str | None = None
        if matched_image is not None:
            # 매칭 필터가 image_asset_id가 NULL인
            # 후보를 판단 프롬프트에서 걸러내지만, 그 필터를 통과한 뒤에도 `db.get(Asset, ...)`
            # 실패와 S3 presign 실패는 남는다 — 이미 db.commit() 뒤라 예외가 여기서 새면
            # SSE 스트리밍 절(apps/api/CLAUDE.md)의 폭발 반경(커넥션 강제종료 → 무관한 다른 요청 500)이 그대로 열린다.
            # 실패하면 이 턴의 이미지 매칭만 포기하고 이미지 없이 done 이벤트로 마무리한다.
            try:
                assert matched_image.image_asset_id is not None
                image_asset = await db.get(Asset, matched_image.image_asset_id)
                assert image_asset is not None
                matched_image_url = await run_in_threadpool(generate_presigned_get_url, image_asset.storage_key)
            except Exception as exc:
                self._log.warning(_SITUATIONAL_URL_FAILURE_LOG[self._mode], room.id, exc)
                capture_dependency_failure(exc, dependency="s3")
                matched_image = None
                matched_image_url = None

        judged_cell_id = written.judged_cell_id
        judged_cell_image = (
            await _sign_judged_cell(db, room, judged_cell_id, log=self._log) if judged_cell_id is not None else None
        )

        ending_reached_event = turn.judgments.ending_reached_event
        if ending_reached_event is not None and ending_reached_event.epilogue:
            # 에필로그의 미디어 북 태그를 방 버전의 칸 id 형태로 바꾸고 그림을 서명한다. 커밋 뒤라 여기서 예외가
            # 새면 SSE 제너레이터를 뚫으므로 흡수하고, 그때는 태그를 지운 글로 그림 없이 보낸다(이름 형태 태그를
            # 화면에 남기지 않는다). `fold_memory` 예약 앞이어야 한다 — 예약 뒤에는 요청 세션 쿼리를 더하지 않는다.
            epilogue = ending_reached_event.epilogue
            try:
                [epilogue_text], epilogue_images = await normalize_texts_for_display(
                    db, room.content_version_id, [epilogue]
                )
            except Exception as exc:
                self._log.warning("대화방 %s 에필로그 그림 해석 실패 — 태그 없이 보낸다: %s", room.id, exc)
                capture_dependency_failure(exc, dependency="db")
                epilogue_text, epilogue_images = strip_media_tags(epilogue), {}
            ending_reached_event = ending_reached_event.model_copy(
                update={"epilogue": epilogue_text, "media_tag_images": epilogue_images}
            )

        # 커밋 뒤 조회가 다시 연 트랜잭션을 반납한다 — 요청 세션은 요약 접기(LLM 호출)가 끝난 뒤에야 닫힌다.
        await db.commit()

        return TurnPresentation(
            matched_image=matched_image,
            matched_image_url=matched_image_url,
            judged_cell_image=judged_cell_image,
            ending_reached_event=ending_reached_event,
        )


class PreviewTurnStore:
    """빌더 미리보기의 턴 저장소. 방 대신 미리보기 세션 상태(`PreviewSessionState`)에 쓰고, 그 상태를 Redis 에 저장하는
    것은 라우트가 턴 골격이 끝난 뒤 정산 가드 밖에서 한다 — 저장 자리와 그 저장을 패치하는 테스트를 옮기지 않으려는
    것이고, 이벤트 루프가 끝난 뒤에 저장해야 끊긴 턴은 저장을 건너뛴다. DB 에 닿지 않는다 — 요청
    세션은 라우트가 본문 첫머리에서 이미 반납했다.

    정산 표시는 여기서 세우지 않는다. 미리보기는 응답을 DB 에 남기지 않아 `done` 을 내보내는 순간이 응답 확정이고, 그
    표시는 골격이 `done` 바로 앞에서 세운다 — 여기서 세우면 `statChange`·`endingReached` 에서 끊긴 사용자의 차감이
    환급되지 않는다."""

    def __init__(self, state: PreviewSessionState, media_images: dict[uuid.UUID, MediaTagImage]) -> None:
        self._state = state
        self._media_images = media_images

    def turn_number(self) -> int:
        return self._state.turn_count + 1

    async def release(self) -> None:
        return None

    async def write(self, turn: TurnResult, settlement: TurnSettlement) -> TurnWrite:
        """응답을 세션 메시지에 덧붙이고 턴 수·바뀐 스탯·엔딩 도달을 반영한다. 응답 시각은 생성이 끝난 시각이다. 판정이
        고른 칸은 그 그림을 서명해 둔 칸일 때만 메시지에 싣는다(`done` 과 같은 값)."""
        result = turn.judgments
        message = ChatMessage(
            id=uuid.uuid4(),
            role=ChatMessageRole.ASSISTANT,
            content=turn.assistant_content,
            created_at=turn.generated_at,
        )
        judged_cell_id = result.judged_cell_id
        judged_cell_image = self._media_images.get(judged_cell_id) if judged_cell_id is not None else None
        self._state.messages.append(_turn_message_response(message, None, None, judged_cell_id, judged_cell_image))
        self._state.turn_count = turn.turn_number
        # 판정은 지금 값에서 시작해 바뀐 스탯(새로 생긴 카운터 포함)만 넘기므로, 덮어 쓰면 반영 뒤 값 전체와 같다.
        self._state.stats.update(result.stat_writes)
        if result.ending_reached_event is not None:
            self._state.ending_reached = True
        return TurnWrite(message=message, matched_image=None, judged_cell_id=judged_cell_id)

    async def present(self, turn: TurnResult, written: TurnWrite) -> TurnPresentation:
        """칸 그림은 의존성이 서명해 둔 것을 그대로 쓰고, 엔딩 이벤트는 판정이 이미 화면용으로 만들었다. 커밋 뒤 조회가
        없다."""
        judged_cell_id = written.judged_cell_id
        return TurnPresentation(
            matched_image=None,
            matched_image_url=None,
            judged_cell_image=self._media_images.get(judged_cell_id) if judged_cell_id is not None else None,
            ending_reached_event=turn.judgments.ending_reached_event,
        )
