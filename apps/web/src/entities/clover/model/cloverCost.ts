/** 이미지 1장의 클로버. BE `apps/api/src/api/core/clover.py`의 `IMAGE_UNIT_COST`와 같은 값이며 **코드젠을 타지 않는
 * 수동 사본이다** — 이 단가는 OpenAPI 스키마에 나가지 않아(429 계약과 같은 성질) BE 상수를 바꾸면 여기도 손으로
 * 고쳐야 한다. 이 파일이 그 사본의 **유일한 자리**다.
 *
 * 채팅 한 턴의 가격은 여기 없다 — 방마다 모델이 달라 가격이 갈리므로 서버가 방 응답(`turnCost`)과 모델 목록
 * (`GET /chat-models`)에 실어 보내고 화면은 그 값을 쓴다.
 *
 * `entities`에 두는 이유는 소비자가 `features/generate-images` 등 여러 레이어에 걸쳐 있어서다(같은 레이어
 * 슬라이스끼리 import하지 않는다). */

/** 이미지 1장 = 30클로버. */
export const IMAGE_CLOVER_COST = 30;
