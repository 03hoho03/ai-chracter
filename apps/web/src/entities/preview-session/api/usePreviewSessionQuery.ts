import { useQuery } from "@tanstack/react-query";

import { previewSessionKeys } from "./keys";
import type { PreviewSessionState } from "./preview-session";

/**
 * 미리보기 세션엔 GET 엔드포인트가 없다(techspec-builder-common.md §3 — Redis뿐인 세션이라 조회
 * API 자체가 없음, apps/api/CLAUDE.md 참고) — 이 쿼리는 서버에서 데이터를 가져오지 않고
 * (`enabled: false`), useStartPreviewMutation/applyPreviewStreamEvent가 채워둔
 * previewSessionKeys.detail 캐시를 그대로 구독만 한다. previewSessionId가 아직 없으면(세션 시작
 * 전) 항상 data가 undefined인 채로 남는다.
 */
export function usePreviewSessionQuery(previewSessionId: string | undefined) {
  return useQuery<PreviewSessionState>({
    queryKey: previewSessionKeys.detail(previewSessionId ?? ""),
    queryFn: () => {
      throw new Error("Preview session state is only populated via useStartPreviewMutation / SSE events");
    },
    enabled: false,
    staleTime: Infinity,
  });
}
