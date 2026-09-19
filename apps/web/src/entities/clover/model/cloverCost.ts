/** 클로버 단가. BE `apps/api/src/api/core/clover.py`의 `CHAT_TURN_COST`/`IMAGE_UNIT_COST`와 같은
 * 값이며 **코드젠을 타지 않는 수동 사본이다** — 단가는 OpenAPI 스키마에 나가지 않아(429 계약과
 * 같은 성질) BE 상수를 바꾸면 여기도 손으로 고쳐야 한다. 이 파일이 그 사본의 **유일한 자리**다:
 * 처음엔 잔량 표시 두 곳에 각자 리터럴로 있었는데, 확인 모달(CL-19)이 같은 값을 다시 필요로 하면서
 * 사본이 넷이 될 참이었다.
 *
 * `entities`에 두는 이유는 소비자가 `features/generate-images`와 `widgets/chat-room` 등
 * 여러 레이어에 걸쳐 있어서다(같은 레이어 슬라이스끼리 import하지 않는다). */

/** clover-goal-prompt.md CL-10 — 채팅 1턴 = 10클로버. */
export const CHAT_TURN_CLOVER_COST = 10;

/** clover-goal-prompt.md CL-11 — 이미지 1장 = 30클로버(= 채팅 3턴분). */
export const IMAGE_CLOVER_COST = 30;
