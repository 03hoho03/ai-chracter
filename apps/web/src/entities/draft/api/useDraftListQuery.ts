import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { draftKeys } from "./keys";

export type DraftSummary = components["schemas"]["DraftSummary"];
export type DraftListResponse = components["schemas"]["DraftListResponse"];

/** techspec-builder-common.md §2 — 내 작품(`/my`)의 초안 목록.
 *
 * US-001로 커서 페이징이 들어가 응답이 `{ items, nextCursor }` 봉투가 됐다. 여기서는 첫 페이지만
 * 읽는다 — `nextCursor`를 실제로 따라가는 "더 보기"는 US-009가 붙인다. */
export function useDraftListQuery() {
  return useQuery({
    queryKey: draftKeys.list(),
    queryFn: async () => (await apiClient.get<DraftListResponse>("/me/drafts")).data,
  });
}
