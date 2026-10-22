import type { ApiError, components } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/shared/lib/api/client";

import { adminNovelKeys } from "./keys";

type AdminNovelIllustrationTakedownRequest = components["schemas"]["AdminNovelIllustrationTakedownRequest"];
type AdminNovelIllustrationTakedownResponse = components["schemas"]["AdminNovelIllustrationTakedownResponse"];

/** 소설 삽화로 쓰인 그림 하나를 모든 소설의 모든 판에서 내린다(환급 없음, 되돌리는 길이 없다). 내림은 파일(바이트) 단위라
 * 같은 파일이 다른 자산으로 이미 내려가 있으면 200 에 `alreadyTakenDown` 이 참이다. 사유가 공백뿐이면 422, 어느 화에도 쓰인
 * 적 없는 자산이면 404, 그 자산이 이미 내려가 있으면 409, 그림 파일을 못 읽으면 503 이다. 끝나면(실패 포함) 노벨 쿼리 전체를
 * 무효화한다 — 같은 그림이 다른 노벨의 화에도 걸려 있을 수 있어 펼쳐 둔 화가 모두 낡는다. */
export function useNovelIllustrationTakedownMutation(assetId: string) {
  const queryClient = useQueryClient();

  return useMutation<AdminNovelIllustrationTakedownResponse, ApiError, AdminNovelIllustrationTakedownRequest>({
    mutationFn: async (payload) =>
      (await apiClient.post<AdminNovelIllustrationTakedownResponse>(`/admin/novel-illustrations/${assetId}/takedown`, payload))
        .data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminNovelKeys.all }),
  });
}
