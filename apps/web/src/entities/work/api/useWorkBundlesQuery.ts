import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { WorkBundleKind, WorkBundleListResponse } from "../model/workItem";
import { workBundleKeys } from "./keys";

/** `GET /me/work-bundles` — 내 묶음 전부(최근에 바뀐 것부터, 한도 안이라 페이지 없음). 묶음 화면의 이름도 여기서 id 로
 * 찾는다(단건 조회가 없다). */
export function useWorkBundlesQuery() {
  return useQuery<WorkBundleListResponse, ApiError>({
    queryKey: workBundleKeys.list(),
    queryFn: async () => (await apiClient.get<WorkBundleListResponse>("/me/work-bundles")).data,
  });
}

/** 작품 하나를 기준으로 본 내 묶음들 — 각 묶음의 `containsWork` 가 참·거짓으로 온다(작품 메뉴의 체크 표시). */
export function useWorkBundlesForWorkQuery(kind: WorkBundleKind, workId: string) {
  return useQuery<WorkBundleListResponse, ApiError>({
    queryKey: workBundleKeys.forWork(kind, workId),
    queryFn: async () =>
      (await apiClient.get<WorkBundleListResponse>("/me/work-bundles", { params: { kind, workId } })).data,
  });
}
