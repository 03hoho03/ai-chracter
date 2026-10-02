import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.admin.dependencies import get_current_admin_id
from api.admin.schemas import AdminLlmModelPrice, AdminLlmUsageResponse, AdminLlmUsageRow
from api.llm.client import JUDGMENT_CALL_SITES
from api.llm.pricing import MODEL_PRICES, PRICES_AS_OF, estimate_cost_usd
from api.llm.usage_store import UsageRow, read_usage, sum_by_call_site_and_model

router = APIRouter(tags=["admin"])

# 보존은 400일이지만 일자별 줄이 call_site × 모델 수만큼 늘어 화면 표가 감당할 길이로 묶는다.
# 석 달(연속한 세 달 중 가장 긴 92일)이면 모델 전환 전후를 한 번에 비교할 수 있다.
MAX_RANGE_DAYS = 92


def _generation_call_site(call_site: str) -> str:
    """판정의 분모가 되는 생성 call_site. 빌더 미리보기 판정은 미리보기 생성과, 나머지는 채팅
    생성과 짝이다 — call_site 이름의 `preview_` 접두가 그 구분이다."""
    return "preview_generate" if call_site.startswith("preview_") else "chat_generate"


def _to_response_rows(rows: Iterable[UsageRow]) -> list[AdminLlmUsageRow]:
    rows = list(rows)
    generation_calls: dict[tuple[date | None, str], int] = defaultdict(int)
    for row in rows:
        generation_calls[(row.day, row.call_site)] += row.calls

    result = []
    for row in rows:
        # 이미지가 실린 호출은 입력 토큰이 비고 total 만 오므로, 입력 전체는 total 에서 출력·사고를
        # 빼서 복원한다. total 마저 없는 호출(메타데이터 자체가 없음)은 보고된 입력을 그대로 쓴다.
        input_tokens = max(row.prompt, row.total - row.candidates - row.thoughts)
        judgment_ratio = None
        if row.call_site in JUDGMENT_CALL_SITES:
            denominator = generation_calls[(row.day, _generation_call_site(row.call_site))]
            judgment_ratio = row.calls / denominator if denominator else None
        result.append(
            AdminLlmUsageRow(
                day=row.day,
                call_site=row.call_site,
                model=row.model,
                calls=row.calls,
                prompt_tokens=row.prompt,
                cached_tokens=row.cached,
                output_tokens=row.candidates,
                thoughts_tokens=row.thoughts,
                total_tokens=row.total,
                missing_calls=row.missing,
                input_tokens=input_tokens,
                cache_hit_rate=row.cached / row.prompt if row.prompt else None,
                judgment_ratio=judgment_ratio,
                estimated_cost_usd=estimate_cost_usd(
                    row.model,
                    input_tokens=input_tokens,
                    cached_tokens=row.cached,
                    output_tokens=row.candidates,
                    thoughts_tokens=row.thoughts,
                ),
            )
        )
    return result


@router.get("/admin/llm-usage")
async def get_llm_usage(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
) -> AdminLlmUsageResponse:
    """LLM 호출 사용량 집계(일자 × call_site × 모델)와 단가표로 낸 추정 원가. `from`·`to` 는 KST
    날짜다 — 집계 키가 KST 하루라서, UTC 날짜로 자르는 `/admin/usage-metrics` 와 경계가 9시간
    어긋난다. 응답을 받은 호출만 세므로 응답을 못 받은 판정 실패(없는 모델·429·네트워크 오류)는
    호출 수에서 빠지고, 그래서 판정 비율이 떨어지는 것이 조용한 판정 누락의 신호가 된다. 응답은
    왔지만 스키마로 파싱되지 않은 실패는 토큰이 이미 과금된 호출이라 정상 호출과 똑같이 세어져
    비율에 드러나지 않는다 — Bugsink 의 `dependency=gemini` 태그 이벤트 가운데 메시지가
    `Gemini structured response could not be parsed` 로 시작하는 것으로 본다."""
    if to_date < from_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="to must not be before from")
    if to_date - from_date >= timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"range must not exceed {MAX_RANGE_DAYS} days"
        )

    daily = await read_usage(from_date, to_date)
    totals = _to_response_rows(sum_by_call_site_and_model(daily))
    return AdminLlmUsageResponse(
        rows=_to_response_rows(daily),
        totals=totals,
        estimated_cost_usd_total=sum(r.estimated_cost_usd for r in totals if r.estimated_cost_usd is not None),
        unpriced_calls=sum(r.calls for r in totals if r.estimated_cost_usd is None),
        prices_as_of=PRICES_AS_OF,
        prices=[
            AdminLlmModelPrice(
                model=model,
                input_usd_per_million=price.input_usd_per_million,
                cached_input_usd_per_million=price.cached_input_usd_per_million,
                output_usd_per_million=price.output_usd_per_million,
            )
            for model, price in MODEL_PRICES.items()
        ],
    )
