/** 이력 키도 여기 둔다 — 저장·되돌리기가 `all` 접두 하나로 표·이력을 함께 무효화하고, 표를 읽는 다른 화면(프롬프트 화면)도
 * 같은 접두를 본다. */
export const promptRoutingKeys = {
  all: ["promptRouting"] as const,
  table: () => [...promptRoutingKeys.all, "table"] as const,
  revisions: () => [...promptRoutingKeys.all, "revisions"] as const,
  revision: (id: string) => [...promptRoutingKeys.all, "revision", id] as const,
};
