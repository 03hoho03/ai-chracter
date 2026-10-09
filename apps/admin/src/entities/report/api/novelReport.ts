import type { components } from "@ai-character-chat/api-types";

export type NovelReportList = components["schemas"]["AdminNovelReportListResponse"];
export type NovelReportListItem = components["schemas"]["AdminNovelReportListItem"];
export type NovelReportDetail = components["schemas"]["AdminNovelReportDetailResponse"];
export type NovelReportAction = components["schemas"]["AdminNovelReportActionRequest"];

export type NovelCommentReportList = components["schemas"]["AdminNovelCommentReportListResponse"];
export type NovelCommentReportDetail = components["schemas"]["AdminNovelCommentReportDetailResponse"];
export type NovelCommentReportAction = components["schemas"]["AdminNovelCommentReportActionRequest"];
export type NovelCommentCurrent = components["schemas"]["AdminNovelCommentItem"];

/** 보유 기간이 지난 신고 시점 사본은 서버가 비워 보내지만, 화면을 열어 둔 채 기한을 넘기면 받아 둔 응답에 남는다 —
 * 그 순간 캐시에서도 지운다(댓글·채팅 응답 신고 상세와 같은 처리). */
export function redactExpiredNovelEvidence(report: NovelReportDetail): NovelReportDetail {
  if (!report.evidence.available || Date.parse(report.evidence.expiresAt) > Date.now()) return report;
  return {
    ...report,
    evidence: { ...report.evidence, available: false, title: null, synopsis: null, chapterTitle: null, body: null },
  };
}

export function redactExpiredNovelCommentEvidence(report: NovelCommentReportDetail): NovelCommentReportDetail {
  if (!report.evidence.available || Date.parse(report.evidence.expiresAt) > Date.now()) return report;
  return { ...report, evidence: { ...report.evidence, available: false, body: null } };
}
