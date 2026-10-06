import type { ApiError } from "@ai-character-chat/api-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { cloverKeys } from "@/entities/clover";
import { novelKeys } from "@/entities/novel";
import { apiClient } from "@/shared/api/client";

/** `DELETE /novels/{novelId}` — 소설과 그 장·판·작업을 모두 지운다(204). 진행 중이던 작업은 서버가 같은
 * 트랜잭션에서 환불한다. 원래 대화방은 그대로다. 소설화 허용이 회수된 계정도 자기 소설은 지울 수 있다.
 *
 * 성공 뒤 늘 일어나야 할 캐시 정리: 목록은 낡았고, 환불이 있었을 수 있어 잔액도 낡았다. 이 소설의 상세·본문
 * 캐시를 버리는 일은 호출부(모달)가 화면을 떠난 **뒤에** 한다 — 보고 있는 상세를 먼저 버리면 그 화면이 다시
 * 받아 "찾을 수 없어요"를 한 번 그린다. */
export function useDeleteNovelMutation() {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, string>({
    mutationFn: async (novelId) => {
      await apiClient.delete(`/novels/${novelId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: novelKeys.list() });
      void queryClient.invalidateQueries({ queryKey: cloverKeys.all });
    },
  });
}
