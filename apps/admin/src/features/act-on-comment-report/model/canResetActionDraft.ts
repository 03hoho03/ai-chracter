import type { CommentReportActionValues } from "./schema";

export function canResetActionDraft(
  submitted: CommentReportActionValues,
  current: CommentReportActionValues,
  submittedRevision: number,
  currentRevision: number,
): boolean {
  return submittedRevision === currentRevision
    && submitted.action === current.action
    && submitted.adminComment === current.adminComment;
}
