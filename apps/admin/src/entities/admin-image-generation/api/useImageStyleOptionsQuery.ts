import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { imageGenerationListQueryOptions } from "./imageGenerationListQueryOptions";
import type { AdminImageGenerationListParams } from "./keys";

/** 스타일 필터 선택지(id·표시명, 서버 레지스트리 순서). 이름은 서버 레지스트리가 유일한 소스라
 * 어드민이 사본을 들지 않고 목록 응답에서 읽는다.
 *
 * 필터를 바꿀 때마다 목록 키가 바뀌어 새 응답이 올 때까지 데이터가 비는데, 선택지는 어느 응답에서나
 * 같으므로 이 구독만 직전 응답을 유지한다(`keepPreviousData`) — 그래야 필터를 누를 때마다 드롭다운
 * 이름이 id 로 깜빡이지 않는다. 표는 자기 구독이라 로딩 표시가 그대로다. */
export function useImageStyleOptionsQuery(params: AdminImageGenerationListParams) {
  return useQuery({
    ...imageGenerationListQueryOptions(params),
    select: (data) => data.styleOptions,
    placeholderData: keepPreviousData,
  });
}
