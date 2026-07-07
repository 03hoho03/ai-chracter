import type { components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../../shared/lib/api/client";
import { draftKeys } from "./keys";

export type DraftSummary = components["schemas"]["DraftSummary"];

/** techspec-builder-common.md §2 — 마이페이지 초안 목록. */
export function useDraftListQuery() {
  return useQuery({
    queryKey: draftKeys.list(),
    queryFn: async () => (await apiClient.get<DraftSummary[]>("/me/drafts")).data,
  });
}
