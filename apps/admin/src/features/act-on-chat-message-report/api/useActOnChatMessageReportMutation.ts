import { useQueryClient } from "@tanstack/react-query";

import { adminUserKeys } from "@/entities/admin-user";
import { useChatMessageReportActionMutation } from "@/entities/report";

/** 처리 감사 로그의 대상 유저가 신고자라 그 유저 상세의 조치 이력도 바뀐다 — entity끼리 물리지 않도록
 * 유저 쿼리는 이 feature에서 끊는다(댓글 신고 처리와 같은 모양). */
export function useActOnChatMessageReportMutation(reportId: string) {
  const queryClient = useQueryClient();
  return useChatMessageReportActionMutation(reportId, {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
