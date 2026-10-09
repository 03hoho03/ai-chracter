"""노벨 독자 라우트(`/webnovels`)의 모든 응답에 `Cache-Control: no-store` 를 붙이는 라우트 클래스.

독자 라우트의 404·410 은 노벨이 거둬지거나 스위치가 꺼진 동안의 일시 상태다. 그런데 캐시 지시 없이 나간 404·410 은 브라우저가
휴리스틱으로 캐시할 수 있는 응답이라, 다시 공개한 뒤에도 브라우저가 붙잡아 둔 410 을 계속 보여 준 일이 있었다. 그래서 성공
응답뿐 아니라 `HTTPException`·요청 검증 오류로 끝나는 응답에도 같은 헤더를 붙인다. 앱 전역 미들웨어가 아니라 이 라우터들에만
거는 것은 다른 라우트의 캐시 동작을 바꾸지 않으려는 것이다."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

NO_STORE = "no-store"


class NoStoreRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def no_store_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except StarletteHTTPException as exc:
                # 오류 응답은 앱의 기본 처리기가 만든다 — 그 처리기가 예외의 `headers` 를 응답에 싣는다.
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=exc.detail,
                    headers={**(exc.headers or {}), "Cache-Control": NO_STORE},
                ) from exc
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(request, exc)
            response.headers["Cache-Control"] = NO_STORE
            return response

        return no_store_handler
