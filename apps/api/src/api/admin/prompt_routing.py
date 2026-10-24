"""어드민 모델 배정 표 API — 실효 표 조회, 표 전체 저장, 이력 목록·상세, 이력으로 되돌리기.

저장은 표 전체를 갈아 끼우고 이력에 한 행을 쌓는다. 되돌리기는 옛 이력의 스냅샷을 지금의 env·게시 세트로 다시 검사해 저장과
같은 경로로 새 이력 행을 만든다 — 그 사이 env 배정이나 게시 세트가 바뀌었으면 옛 스냅샷이 지금은 다른 경로로 가거나 체인이 없는
행을 담을 수 있기 때문이다. "전부 env 로"는 빈 표 저장이라 따로 라우트를 두지 않는다.

조회는 캐시가 아니라 DB 를 읽는다 — 운영자가 보는 값은 방금 저장한 값이어야 하고, 저장 직후 조회가 캐시를 다시 채우지 않게 한다.

저장·되돌리기는 감사 로그(`admin_action_logs`)에도 이력 행과 같은 트랜잭션에서 한 행씩 남긴다. 이력 표는 표의 내용이고 감사
로그는 운영자의 행동이라, 프롬프트 세트 게시처럼 감사 로그 한 곳에서 운영 조치 전부를 시간순으로 볼 수 있게 한다. 이 행은 대상
회원·작품이 없다. 감사 로그를 읽는 곳은 회원 상세의 조치 이력 하나이고 그 회원이나 그 회원 작품이 대상인 행만 고르므로, 이 두
조치 종류를 모르는 옛 이미지로 되돌려도 그 응답 검증은 깨지지 않는다.

칸마다의 후보(`candidates`)는 그 칸이 고를 수 있는 쌍마다 호출 위치가 실제로 보낼 모델 id 와 단가다. 저장 전에 새로 고른 쌍의
단가를 화면이 보이려는 읽기 전용 계산이라, 운영 값(`effective`·`calls`)과 달리 지금 표·env 배정과 무관하다.
"""

import logging
import uuid
from collections.abc import Sequence
from typing import Any, get_args

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import (
    AdminPromptRouteAllowedPair,
    AdminPromptRouteCall,
    AdminPromptRouteCandidate,
    AdminPromptRouteCell,
    AdminPromptRouteChain,
    AdminPromptRouteChainReader,
    AdminPromptRouteEffective,
    AdminPromptRoutePrice,
    AdminPromptRouteRevisionDetailResponse,
    AdminPromptRouteRevisionListResponse,
    AdminPromptRouteRevisionSummary,
    AdminPromptRouteRow,
    AdminPromptRouteSkip,
    AdminPromptRoutingResponse,
    AdminPromptRoutingRestoreRequest,
    AdminPromptRoutingSaveRequest,
)
from api.chat.prompt_routing import (
    ALLOWED_ROUTE_PAIRS,
    PromptRoutes,
    RouteRow,
    RouteRowError,
    RouteRowInput,
    parse_route_row,
    resolve_stage_route,
    route_chain_errors,
    route_row_errors,
)
from api.chat.prompt_routing_cache import invalidate_prompt_routes, load_prompt_routes_from_db
from api.chat.prompt_stages import LANE_STAGES, STAGES, PromptStage, RoutingLane, stage_call_sites
from api.core.config import settings
from api.core.sentry import capture_dependency_failure
from api.db.models.moderation import AdminActionType
from api.db.models.prompt import PromptRoute, PromptRouteRevision
from api.db.session import get_db_session
from api.llm.call_policy import BackendId, LLMCallSite
from api.llm.chat_models import ChatRoomModelId, PromptSetModelId, backend_model_id
from api.llm.client import structured_model
from api.llm.pricing import MODEL_PRICES, PRICES_AS_OF

router = APIRouter(tags=["admin"])

logger = logging.getLogger(__name__)

_ROOM_MODELS: tuple[ChatRoomModelId, ...] = get_args(ChatRoomModelId)


def _row_out(row: RouteRow) -> AdminPromptRouteRow:
    return AdminPromptRouteRow(
        lane=row.lane,
        room_model=row.room_model,
        stage=row.stage,
        chain_model=row.chain_model,
        call_model=row.call_model,
        backend=row.backend,
    )


def _snapshot(row: RouteRow) -> dict[str, Any]:
    """이력 `rows` 의 한 원소 — 응답 스키마의 camelCase 꼴 그대로다."""
    return _row_out(row).model_dump(mode="json", by_alias=True)


def _snapshot_inputs(raw: Sequence[Any]) -> list[RouteRowInput]:
    """이력 스냅샷을 저장 검사가 받는 꼴로 읽는다. 스냅샷은 요청 검증을 거치지 않아 모르는 값이 있을 수 있으므로 문자열로만 옮기고
    판단은 저장 검사에 맡긴다."""

    def text(item: dict[str, Any], key: str) -> str:
        value = item.get(key)
        return value if isinstance(value, str) else ""

    inputs: list[RouteRowInput] = []
    for item in raw:
        entry: dict[str, Any] = item if isinstance(item, dict) else {}
        chain = entry.get("chainModel")
        inputs.append(
            RouteRowInput(
                lane=text(entry, "lane"),
                room_model=text(entry, "roomModel"),
                stage=text(entry, "stage"),
                chain_model=chain if isinstance(chain, str) else None,
                call_model=text(entry, "callModel"),
                backend=text(entry, "backend"),
            )
        )
    return inputs


def _model_id(call_site: LLMCallSite, backend: BackendId, model: PromptSetModelId) -> str:
    """그 호출 위치가 실제로 보낼 모델 id. Gemini 는 판정 종류별 모델명 설정이 있으면 그 값이고(생성은 기본 모델명), 나머지 구현은
    모델 축의 id 설정이다."""
    if backend == "gemini":
        return structured_model(call_site, settings.gemini_model_name)
    return backend_model_id(backend, model)


def _price(model_id: str) -> AdminPromptRoutePrice | None:
    price = MODEL_PRICES.get(model_id)
    if price is None:
        return None
    return AdminPromptRoutePrice(
        input_usd_per_million=price.input_usd_per_million,
        cached_input_usd_per_million=price.cached_input_usd_per_million,
        output_usd_per_million=price.output_usd_per_million,
        cache_write_usd_per_million=price.cache_write_usd_per_million,
    )


def _call(call_site: LLMCallSite, backend: BackendId, model: PromptSetModelId) -> AdminPromptRouteCall:
    model_id = _model_id(call_site, backend, model)
    return AdminPromptRouteCall(call_site=call_site, backend=backend, model_id=model_id, price=_price(model_id))


def _candidates(room_model: ChatRoomModelId, stage: PromptStage) -> list[AdminPromptRouteCandidate]:
    """그 칸의 행이 고를 수 있는 쌍마다 그 단계의 호출 위치가 보낼 모델 id·단가. 생성 단계는 방 모델로만 부르므로 방 모델의
    쌍뿐이다(저장 검사가 다른 모델을 거부한다)."""
    kind = STAGES[stage].kind
    return [
        AdminPromptRouteCandidate(
            model=model,
            backend=backend,
            calls=[_call(call_site, backend, model) for call_site in stage_call_sites(stage)],
        )
        for model, backend in sorted(ALLOWED_ROUTE_PAIRS[kind])
        if kind != "generation" or model == room_model
    ]


async def _latest_revision(db: AsyncSession) -> PromptRouteRevision | None:
    result: PromptRouteRevision | None = await db.scalar(
        select(PromptRouteRevision).order_by(PromptRouteRevision.number.desc()).limit(1)
    )
    return result


async def _routing_response(db: AsyncSession) -> AdminPromptRoutingResponse:
    parsed = [parse_route_row(raw) for raw in await load_prompt_routes_from_db(db)]
    routes = PromptRoutes.from_rows(row for row in parsed if row is not None)
    latest = await _latest_revision(db)

    cells: list[AdminPromptRouteCell] = []
    readers: dict[tuple[RoutingLane, PromptSetModelId], list[AdminPromptRouteChainReader]] = {}
    for lane, stages in LANE_STAGES.items():
        for room_model in _ROOM_MODELS:
            for stage in stages:
                calls: list[AdminPromptRouteCall] = []
                for call_site in stage_call_sites(stage):
                    route = resolve_stage_route(
                        routes, lane=lane, room_model=room_model, stage=stage, call_site=call_site
                    )
                    calls.append(_call(call_site, route.backend, route.call_model))
                # 칸의 대표 값은 채팅 호출 위치로 푼 값이다(호출 위치마다의 값은 `calls`).
                route = resolve_stage_route(routes, lane=lane, room_model=room_model, stage=stage)
                configured = routes.get(lane, room_model, stage)
                cells.append(
                    AdminPromptRouteCell(
                        lane=lane,
                        room_model=room_model,
                        stage=stage,
                        kind=STAGES[stage].kind,
                        configured=None if configured is None else _row_out(configured),
                        effective=AdminPromptRouteEffective(
                            chain_model=route.chain_model,
                            call_model=route.call_model,
                            backend=route.backend,
                            source=route.source,
                            source_detail=route.source_detail,
                        ),
                        skipped=None
                        if route.skipped is None
                        else AdminPromptRouteSkip(
                            stage=route.skipped.stage, reason=route.skipped.reason, message=route.skipped.message
                        ),
                        calls=calls,
                        candidates=_candidates(room_model, stage),
                    )
                )
                readers.setdefault((lane, route.chain_model), []).append(
                    AdminPromptRouteChainReader(
                        room_model=room_model, stage=stage, channels=list(STAGES[stage].channels)
                    )
                )

    return AdminPromptRoutingResponse(
        revision_id=None if latest is None else latest.id,
        revision_number=None if latest is None else latest.number,
        prices_as_of=PRICES_AS_OF,
        allowed_pairs=[
            AdminPromptRouteAllowedPair(kind=kind, model=model, backend=backend)
            for kind, pairs in ALLOWED_ROUTE_PAIRS.items()
            for model, backend in sorted(pairs)
        ],
        cells=cells,
        chains=[
            AdminPromptRouteChain(lane=lane, model=model, read_by=read_by) for (lane, model), read_by in readers.items()
        ],
    )


def _rule_error(rows: Sequence[RouteRowInput], errors: Sequence[RouteRowError]) -> HTTPException:
    """저장 검사 거부. 맨 위의 `rule`·`message` 는 첫 위반이고(프롬프트 게시 검증 거부와 같은 꼴이라 화면의 처리가 같다), `row` 는
    그 행의 칸, `errors` 는 행마다의 첫 위반 전부다."""

    def item(error: RouteRowError) -> dict[str, Any]:
        row = rows[error.index]
        return {
            "rule": error.rule,
            "message": error.message,
            "row": {"lane": row.lane, "roomModel": row.room_model, "stage": row.stage},
        }

    items = [item(error) for error in errors]
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={**items[0], "errors": items})


async def _save_routes(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    base_revision_id: uuid.UUID | None,
    note: str,
    rows: Sequence[RouteRowInput],
    restored_from_id: uuid.UUID | None,
    action_type: AdminActionType,
) -> None:
    """저장과 되돌리기가 함께 쓰는 순서: 최신 이력 확인 → 행 검사 → 체인 검사 → 한 트랜잭션에서 이력 행 + 표 교체 + 감사 로그 →
    커밋 → 캐시 무효화."""
    latest = await _latest_revision(db)
    if (None if latest is None else latest.id) != base_revision_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "rule": "stale-revision",
                "message": "다른 저장이 먼저 반영됐습니다. 새로 고친 뒤 다시 저장해 주세요.",
            },
        )

    row_errors = route_row_errors(rows)
    if row_errors:
        raise _rule_error(rows, row_errors)
    parsed: list[RouteRow] = []
    for raw in rows:
        row = parse_route_row(raw)
        if row is None:
            raise AssertionError(f"저장 검사를 통과한 행을 읽지 못했다: {raw}")
        parsed.append(row)
    chain_errors = await route_chain_errors(db, parsed)
    if chain_errors:
        raise _rule_error(rows, chain_errors)

    # 번호는 낡은 기준 확인에 쓴 그 최신 이력에서 정한다. 검사 뒤에 최대 번호를 다시 읽으면 READ COMMITTED 의 새 스냅샷에 그 사이
    # 커밋된 다른 저장이 보여 그 다음 번호를 잡고, 다른 저장의 표를 지운 채 성공한다. 이 번호를 다른 저장이 이미 쥐었으면 번호 유니크
    # 인덱스가 막는다 — 프롬프트 세트 게시와 같은 이유로 SAVEPOINT 로 감싸, 서로 다른 두 표 중 하나를 잃는 경쟁을 덮어쓰지 않고
    # 409 로 다시 저장하게 한다. 감사 로그 행도 같은 SAVEPOINT 안에 두어, 번호 경쟁으로 되감긴 저장이 감사 로그에만 남지 않게 한다.
    number = 1 if latest is None else latest.number + 1
    try:
        async with db.begin_nested():
            db.add(
                PromptRouteRevision(
                    number=number,
                    rows=[_snapshot(row) for row in parsed],
                    note=note,
                    admin_id=admin_id,
                    restored_from_id=restored_from_id,
                )
            )
            await db.execute(delete(PromptRoute))
            for row in parsed:
                db.add(
                    PromptRoute(
                        lane=row.lane,
                        room_model=row.room_model,
                        stage=row.stage,
                        chain_model=row.chain_model,
                        call_model=row.call_model,
                        backend=row.backend,
                    )
                )
            await record_admin_action(db, admin_id=admin_id, action_type=action_type, reason_text=note)
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="방금 다른 저장과 이력 번호가 겹쳤습니다. 새로 고친 뒤 다시 저장해 주세요.",
        ) from None
    await db.commit()

    # 반드시 커밋 뒤에 지운다 — 커밋 전에 지우면 그 사이의 캐시 미스가 옛 표를 다시 채워 이 저장이 TTL 만큼 씹힌다. Redis 실패는
    # 프롬프트 세트 게시 뒤 무효화와 같이 삼키고 경고만 남긴다: 저장은 이미 커밋됐고 옛 표가 나가는 시간은 캐시 TTL 이 상한이다.
    try:
        await invalidate_prompt_routes()
    except RedisError:
        logger.warning("배정 표 저장 후 캐시 무효화 실패 — 캐시 TTL 동안 옛 표가 나간다", exc_info=True)
        capture_dependency_failure(dependency="redis")


async def _get_revision(db: AsyncSession, id: uuid.UUID) -> PromptRouteRevision:
    revision = await db.get(PromptRouteRevision, id)
    if revision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 이력을 찾을 수 없습니다.")
    return revision


def _summary_fields(revision: PromptRouteRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "number": revision.number,
        "note": revision.note,
        "admin_id": revision.admin_id,
        "restored_from_id": revision.restored_from_id,
        "created_at": revision.created_at,
        "row_count": len(revision.rows),
    }


@router.get("/admin/prompt-routing")
async def get_prompt_routing(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRoutingResponse:
    return await _routing_response(db)


@router.put("/admin/prompt-routing")
async def save_prompt_routing(
    body: AdminPromptRoutingSaveRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRoutingResponse:
    rows = [
        RouteRowInput(
            lane=row.lane,
            room_model=row.room_model,
            stage=row.stage,
            chain_model=row.chain_model,
            call_model=row.call_model,
            backend=row.backend,
        )
        for row in body.rows
    ]
    await _save_routes(
        db,
        admin_id=admin_id,
        base_revision_id=body.base_revision_id,
        note=body.note,
        rows=rows,
        restored_from_id=None,
        action_type="prompt-routing-save",
    )
    return await _routing_response(db)


@router.get("/admin/prompt-routing/revisions")
async def list_prompt_route_revisions(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRouteRevisionListResponse:
    revisions = (await db.scalars(select(PromptRouteRevision).order_by(PromptRouteRevision.number.desc()))).all()
    return AdminPromptRouteRevisionListResponse(
        items=[AdminPromptRouteRevisionSummary(**_summary_fields(revision)) for revision in revisions]
    )


@router.get("/admin/prompt-routing/revisions/{id}")
async def get_prompt_route_revision(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRouteRevisionDetailResponse:
    revision = await _get_revision(db, id)
    parsed = [parse_route_row(raw) for raw in _snapshot_inputs(revision.rows)]
    known = [_row_out(row) for row in parsed if row is not None]
    return AdminPromptRouteRevisionDetailResponse(
        **_summary_fields(revision), rows=known, dropped_row_count=len(parsed) - len(known)
    )


@router.post("/admin/prompt-routing/revisions/{id}/restore")
async def restore_prompt_route_revision(
    id: uuid.UUID,
    body: AdminPromptRoutingRestoreRequest,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptRoutingResponse:
    revision = await _get_revision(db, id)
    await _save_routes(
        db,
        admin_id=admin_id,
        base_revision_id=body.base_revision_id,
        note=body.note,
        rows=_snapshot_inputs(revision.rows),
        restored_from_id=revision.id,
        action_type="prompt-routing-restore",
    )
    return await _routing_response(db)
