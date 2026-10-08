/** 관례: `all`은 kebab-case 문자열 1개 배열 + `as const`, 나머지는 전부
 * 함수다(`entities/session`의 `sessionKeys`와 같은 모양). */
export const cloverKeys = {
  all: ["clover"] as const,
  balance: () => [...cloverKeys.all, "balance"] as const,
  missions: () => [...cloverKeys.all, "missions"] as const,
  pricing: () => [...cloverKeys.all, "pricing"] as const,
  // 내역 세 탭을 한꺼번에 무효화할 때의 접두어. 어느 탭에 실릴지는 서버의 범주 맵이 정하므로 화면은 셋을 함께 낡았다고 본다.
  ledgers: () => [...cloverKeys.all, "ledger"] as const,
  // category가 키에 들어가야 탭 전환이 그 자체로 새 쿼리다
  // (안 그러면 탭을 바꿔도 이전 탭의 캐시된 페이지가 그대로 보인다).
  ledger: (category: "use" | "earn" | "expire") => [...cloverKeys.ledgers(), category] as const,
};
