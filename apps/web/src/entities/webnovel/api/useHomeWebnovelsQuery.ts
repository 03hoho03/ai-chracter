import type { ApiError, components } from "@ai-character-chat/api-types";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { webnovelKeys } from "./keys";

export type HomeWebnovelItem = components["schemas"]["PublicNovelHomeItem"];
type HomeWebnovelsResponse = components["schemas"]["PublicNovelHomeResponse"];

/** `GET /webnovels/home-curation` — 홈 노벨 섹션, 운영자가 고른 노벨 가운데 지금 읽을 수 있는 것(자리 순). 로그인
 * 회원만 받는 API 라 로그인했고 노벨이 열려 있을 때만 부른다(`enabled`). 비어 있으면 홈은 섹션을 그리지 않는다. */
export function useHomeWebnovelsQuery({ enabled }: { enabled: boolean }) {
  return useQuery<HomeWebnovelItem[], ApiError>({
    enabled,
    queryKey: webnovelKeys.home(),
    queryFn: async () => (await apiClient.get<HomeWebnovelsResponse>("/webnovels/home-curation")).data.items,
  });
}
