/** 목록과 이력이 한 접두를 쓴다 — 저장이 `all` 하나로 둘을 함께 무효화한다. */
export const featureSwitchKeys = {
  all: ["featureSwitches"] as const,
  list: () => [...featureSwitchKeys.all, "list"] as const,
  changes: (params: { page: number; switchName?: string }) =>
    [...featureSwitchKeys.all, "changes", params.page, params.switchName ?? "all"] as const,
};
