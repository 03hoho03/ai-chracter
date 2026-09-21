/** clover-techspec.md CT-11 — 관례: `all`은 kebab-case 문자열 1개 배열 + `as const`, 나머지는 전부
 * 함수다(`entities/session`의 `sessionKeys`와 같은 모양). */
export const cloverKeys = {
  all: ["clover"] as const,
  balance: () => [...cloverKeys.all, "balance"] as const,
  missions: () => [...cloverKeys.all, "missions"] as const,
};
