import { queryOptions } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import type { AdminPromptRoutingResponse } from "../model/types";
import { promptRoutingKeys } from "./keys";

/** 배정 표의 실효 해석(칸마다 지금 운영 값·출처·건너뛴 행·호출 단가·후보 단가와, 체인마다 읽는 칸). 서버가 DB 를 읽어 푼 값이라
 * 화면은 이것을 다시 조합하지 않는다. */
export const routingQueryOptions = queryOptions({
  queryKey: promptRoutingKeys.table(),
  queryFn: async () => (await apiClient.get<AdminPromptRoutingResponse>("/admin/prompt-routing")).data,
});
