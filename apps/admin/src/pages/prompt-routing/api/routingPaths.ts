import type { RoutingScope } from "../model/schema";

/** 범위마다 저장·되돌리기 경로. 소설 경로가 따로인 것은 서버가 그 경로로만 소설 레인을 갈아 끼우기 때문이다 — 소설 경로가 없는
 * 옛 서버로 되돌린 동안에는 소설 저장이 404 로 막혀, 옛 서버가 요청의 뜻을 모른 채 표를 바꾸는 일이 없다. */
export const ROUTING_SAVE_PATHS = {
  chat: "/admin/prompt-routing",
  novel: "/admin/prompt-routing/novel",
} satisfies Record<RoutingScope, string>;

export function routingRestorePath(scope: RoutingScope, id: string): string {
  return scope === "chat"
    ? `/admin/prompt-routing/revisions/${id}/restore`
    : `/admin/prompt-routing/novel/revisions/${id}/restore`;
}
