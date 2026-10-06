import type { components } from "@ai-character-chat/api-types";
import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/api/client";

import { sessionKeys } from "./keys";

export type MeResponse = components["schemas"]["MeResponse"];

/** 계정별로 열리는 기능 이름. 서버가 라우트 게이트와 같은 판정으로 `GET /me` 에 실어 보낸다. */
export type EnabledFeature = MeResponse["enabledFeatures"][number];

/** 세션도 서버 상태이므로 useQuery(훅)와
 * beforeLoad 라우터 가드(ensureQueryData) 양쪽이 동일한 옵션을 공유한다. */
export const sessionQueryOptions = queryOptions({
  queryKey: sessionKeys.current(),
  queryFn: async () => (await apiClient.get<MeResponse>("/me")).data,
  staleTime: Infinity,
  retry: false,
  // staleTime: Infinity라 기본값(true)으로는 포커스 복귀에도 다시 묻지
  // 않는다. 다른 탭에서 로그아웃했거나 정지된 탭이 돌아왔을 때 로그인된 척하지 않도록 이 쿼리만 매번 묻는다
  // (401이면 `resetSessionIfLost`가 옛 data를 비운다).
  refetchOnWindowFocus: "always",
});
