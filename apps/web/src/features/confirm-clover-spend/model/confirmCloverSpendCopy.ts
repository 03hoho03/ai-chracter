/** 확인 모달의 본문 문구.
 *
 * 🔴 **표면마다 무료분이 다시 차는 방식이 다르다.** 채팅은 KST 일일 키라 자정에 열리지만
 * (`core/rate_limit_gate.py`의 `CHAT_DAILY_LIMIT = 30`), 이미지는 **시간당 충전 토큰 버킷**이다
 * (`IMAGE_TOKEN_CAPACITY = 10` · `IMAGE_TOKEN_REFILL_SECONDS = 3600`). 한 문구를 공유하면
 * 이미지에서 **최대 24시간짜리 거짓**이 된다.
 *
 * 같은 이유로 `widgets/image-studio`의 `imageRateLimitMessage.ts`가 이미 채팅 문구를 재사용하지
 * 않는다. 여기서도 그 어휘를 따라 **시점을 약속하지 않고 기전만**
 * 말한다 — `retryAfterSeconds`는 "무료 토큰이 찰 때까지"이지 "클로버가 생길 때까지"가 아니라
 * 이 문구에 쓸 수 없다(클로버는 시간이 지난다고 늘지 않는다).
 *
 * ⚠️ 빌더 미리보기는 `"chat"`이다 — 게이트가 채팅 4경로에 **같은 일일 버킷**을 쓰므로 자정
 * 사유가 그대로 참이다. */
export type CloverSpendSurface = "chat" | "image";

export function formatCloverSpendConfirmDescription(surface: CloverSpendSurface, cost: number): string {
  const spend = `계속하면 한 번에 ${cost.toLocaleString()}개씩 차감돼요.`;
  switch (surface) {
    case "chat":
      return `오늘 무료 한도를 다 썼어요. ${spend} 자정이 지나면 무료 한도가 다시 열려요.`;
    case "image":
      return `무료 생성 횟수를 다 썼어요. ${spend} 무료 횟수는 시간이 지나면 다시 차요.`;
  }
}
