import type { ApiError } from "@ai-character-chat/api-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiClient } from "@/shared/lib/api/client";

import type { ChatMessageReportDetail } from "./chatMessageReport";
import { reportKeys } from "./keys";
import { redactExpiredChatMessageEvidence } from "./redactExpiredChatMessageEvidence";

/** 대화 사본은 보관기간(90일)이 지나면 보여서는 안 된다 — 비활성 캐시에 남지 않게 `gcTime: 0`,
 * 화면을 열어 둔 채 만료되면 아래 타이머가 활성 캐시에서도 지운다(댓글 신고 상세와 같은 처리). */
export function useChatMessageReportDetailQuery(reportId: string) {
  const queryClient = useQueryClient();
  const query = useQuery<ChatMessageReportDetail, ApiError>({
    queryKey: reportKeys.chatMessageDetail(reportId),
    queryFn: async () => redactExpiredChatMessageEvidence(
      (await apiClient.get<ChatMessageReportDetail>(`/admin/chat-message-reports/${reportId}`)).data,
    ),
    gcTime: 0,
  });
  const expiresAt = query.data?.evidence.available ? query.data.evidence.expiresAt : undefined;

  // 외부 시계와 동기화한다. 만료된 사본은 화면뿐 아니라 활성 쿼리 캐시에서도 제거한다.
  useEffect(() => {
    if (!expiresAt) return;
    const scrub = () => {
      queryClient.setQueryData<ChatMessageReportDetail>(reportKeys.chatMessageDetail(reportId), (report) =>
        report ? redactExpiredChatMessageEvidence(report) : report,
      );
    };
    let timer: number;
    const schedule = () => {
      const remaining = Date.parse(expiresAt) - Date.now();
      if (remaining <= 0) { scrub(); return; }
      timer = window.setTimeout(schedule, Math.min(remaining, 2_147_483_647));
    };
    schedule();
    document.addEventListener("visibilitychange", scrub);
    window.addEventListener("focus", scrub);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", scrub);
      window.removeEventListener("focus", scrub);
    };
  }, [expiresAt, queryClient, reportId]);

  return query;
}
