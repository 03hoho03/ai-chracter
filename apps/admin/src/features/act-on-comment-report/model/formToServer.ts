import type { CommentReportAction } from "@/entities/report";

import type { CommentReportActionValues } from "./schema";

export function formToServer(values: CommentReportActionValues): CommentReportAction {
  return { action: values.action, adminComment: values.adminComment };
}
