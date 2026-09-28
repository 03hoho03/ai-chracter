import { useQuery } from "@tanstack/react-query";

import { imageGenerationListQueryOptions } from "./imageGenerationListQueryOptions";
import type { AdminImageGenerationListParams } from "./keys";

/** offset 페이지네이션(20건), 프롬프트·이미지는
 * 응답에 없다(사유 게이트 뒤 유저 단위 열람 화면 몫). */
export function useImageGenerationListQuery(params: AdminImageGenerationListParams) {
  return useQuery(imageGenerationListQueryOptions(params));
}
