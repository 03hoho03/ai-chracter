import { useQueryClient } from "@tanstack/react-query";

import { adminUserKeys } from "@/entities/admin-user";
import { useCommentReportActionMutation } from "@/entities/report";

export function useActOnCommentReportMutation(reportId: string) {
  const queryClient = useQueryClient();
  return useCommentReportActionMutation(reportId, {
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminUserKeys.all }),
  });
}
