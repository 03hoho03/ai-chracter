/** 관례: `all`은 kebab-case 문자열 1개 배열 + `as const`, 나머지는 전부 함수다(`cloverKeys`와 같은 모양). */
export const creatorPayoutKeys = {
  all: ["creator-payout"] as const,
  summary: () => [...creatorPayoutKeys.all, "summary"] as const,
  statements: () => [...creatorPayoutKeys.all, "statements"] as const,
  payouts: () => [...creatorPayoutKeys.all, "payouts"] as const,
};
