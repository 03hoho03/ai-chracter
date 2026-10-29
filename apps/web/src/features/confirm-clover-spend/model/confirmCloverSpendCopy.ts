/** 확인 모달의 본문 문구.
 *
 * 🔴 **표면마다 무료분이 다르다.** 채팅에는 하루 무료 대화가 없어 첫 턴부터 클로버를 쓰고, 이미지는 **시간당 충전
 * 토큰 버킷**이다(`IMAGE_TOKEN_CAPACITY = 10` · `IMAGE_TOKEN_REFILL_SECONDS = 3600`). 한 문구를 공유하면 어느 한쪽에서
 * 거짓이 된다.
 *
 * 같은 이유로 `widgets/image-studio`의 `imageRateLimitMessage.ts`가 이미 채팅 문구를 재사용하지
 * 않는다. 여기서도 그 어휘를 따라 **시점을 약속하지 않고 기전만**
 * 말한다 — `retryAfterSeconds`는 "무료 토큰이 찰 때까지"이지 "클로버가 생길 때까지"가 아니라
 * 이 문구에 쓸 수 없다(클로버는 시간이 지난다고 늘지 않는다).
 *
 * ⚠️ 빌더 미리보기는 `"chat"`이다 — 게이트가 채팅 4경로에 같은 확인을 건다. */
export type CloverSpendSurface = "chat" | "image";

/** `cost` 가 undefined 면 숫자 없이 차감 사실만 말한다 — 화면이 서버에서 가격을 아직 못 받은 경우다(가격 사본을 두지
 * 않는다). 정확한 금액은 서버가 차감할 때 정한다. */
export function formatCloverSpendConfirmDescription(
  surface: CloverSpendSurface,
  cost: number | undefined,
): string {
  const spend =
    cost === undefined ? "계속하면 클로버가 차감돼요." : `계속하면 한 번에 ${cost.toLocaleString()}개씩 차감돼요.`;
  switch (surface) {
    // 채팅에는 무료 대화가 없어 차감 사실만 말한다. 서버가 채팅 확인을 더 묻지 않아 실제로는 나오지 않는다.
    case "chat":
      return spend;
    case "image":
      return `무료 생성 횟수를 다 썼어요. ${spend} 무료 횟수는 시간이 지나면 다시 차요.`;
  }
}
