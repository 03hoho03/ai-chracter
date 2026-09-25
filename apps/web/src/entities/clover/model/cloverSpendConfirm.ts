import { getRateLimitDetail } from "@/shared/api/rateLimit";

/** 429가 **"오늘치 동의가 없다"**인가.
 *
 * 🔴 이 판정이 BE에 있는 이유: FE는 "이번 요청이 무료분을 넘는가"를 보내기 전에 알 수 없다.
 * `GET /me/clover`는 잔액·확인여부·출석가능만 주고 무료분 소진은 429가 와야 안다 — 미확인인
 * 모든 첫 요청에 모달을 띄우면 **무료분을 안 쓴 사용자까지 매일 붙잡는다.** 그래서 게이트가
 * 단일 판정자이고, FE는 그 판정을 이 한 줄로 읽기만 한다.
 *
 * 채팅(`window: "clover"`)과 이미지(`window: "image"`)가 **같은 코드**를 쓰므로 표면마다
 * 투영을 따로 둘 필요가 없다 — 확인 상태가 `users` 컬럼 하나라 동의도 하나다.
 *
 * ⚠️ 부족(`CLOVER_REQUIRED`)과 섞지 마라. 저쪽은 배너·토스트로 끝나는 안내이고 이쪽은 모달 →
 * 동의 → 재시도라 **화면 동작이 정반대**다. BE는 잔액이 모자라면 아예 묻지 않으므로(게이트의
 * `_needs_clover_spend_confirmation`) 이 코드를 받았다는 것은 **동의만 하면 쓸 수 있다**는 뜻이다. */
export function isCloverSpendConfirmRequired(error: unknown): boolean {
  return getRateLimitDetail(error)?.code === "CLOVER_CONFIRM_REQUIRED";
}

/** 확인 요청의 결과.
 *
 * - `retry` — 동의가 서버에 기록됐다. 호출부는 같은 요청을 한 번 더 보낸다.
 * - `declined` — 사용자가 스스로 그만뒀다. 🔴 **아무것도 실패하지 않았으므로 오류 문구를 쓰면
 *   거짓이다**(불리언이었을 때 세 표면이 전부 *"응답 생성에 실패했습니다"* 를 띄웠다).
 * - `unhandled` — 확인이 필요한 오류가 아니거나 **동의 기록이 실패**했다. 둘 다 실제 실패라
 *   호출부는 평소의 오류 처리를 그대로 한다.
 *
 * 🔴 **이 타입이 `entities`에 있는 이유**는 FSD다. 판정·모달은 `features/confirm-clover-spend`에
 * 있지만 소비하는 곳이 `features/send-message`·`features/preview-chat`·`widgets/image-studio`로
 * 갈리는데, **feature가 다른 feature를 import하는 선례가 이 저장소에 0건**이다. 함수는 위젯이
 * 주입해 그 문제를 피했고, 타입은 공통 상위인 여기 둔다. */
export type CloverSpendConfirmOutcome = "retry" | "declined" | "unhandled";
