import type { CommentReportDetail } from "./commentReport";

export function redactExpiredEvidence(report: CommentReportDetail): CommentReportDetail {
  if (!report.evidence.available || Date.parse(report.evidence.expiresAt) > Date.now()) return report;
  return {
    ...report,
    evidence: { ...report.evidence, available: false, body: null, stickerId: null, mentionUserIds: [] },
  };
}
