import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import type { ContentType } from "../model/content";
import { contentKeys } from "./keys";

export type HomeCurationItem = components["schemas"]["HomeCurationItem"];
type HomeCurationResponse = components["schemas"]["HomeCurationResponse"];

/** 홈 첫 화면의 운영자 지정작(유형마다 한 편). `null` 이면 지정이 없거나 지정 작품이 지금 공개 목록에 없다.
 *
 * 상세 GET 이 아니라 전용 조회다 — 상세는 조회수를 올리므로 홈 방문마다 그 작품의 조회수가 오른다.
 *
 * `retry: false` — 홈은 이 응답이 올 때까지 목록 그리드도 스켈레톤으로 잡아 두므로(그리드가 뒤늦게 밀려 내려가지
 * 않게), 실패를 재시도하면 그 백오프만큼 목록까지 늦어진다. 실패하면 섹션 없이 목록만 보인다.
 *
 * 응답에 서명 주소가 있지만 `gcTime` 을 0 으로 두지 않는다 — 홈 목록 쿼리와 같은 구간 서명이라 같은 창 안의
 * 재방문은 같은 주소를 받고, 그리드에 같은 작품이 또 나오면 이미지 요청이 하나로 합쳐진다. */
export function useHomeCurationQuery(type: ContentType) {
  return useQuery<HomeCurationItem | null, ApiError>({
    queryKey: contentKeys.homeCuration(type),
    queryFn: async () => (await apiClient.get<HomeCurationResponse>("/home-curation", { params: { type } })).data.item,
    retry: false,
  });
}
