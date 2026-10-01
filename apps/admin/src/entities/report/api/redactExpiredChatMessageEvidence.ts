import type { ChatMessageReportDetail } from "./chatMessageReport";

/** 화면을 열어 둔 채 보관기간이 지나면 서버는 다음 조회부터 사본과 신고자 메모를 빼고 주지만 이미
 * 받은 캐시에는 남아 있다 — 만료 시각이 지났으면 캐시 쪽에서도 둘 다 지운다(댓글 신고의
 * `redactExpiredEvidence`와 같은 규칙, 증거 칸 모양이 달라 따로 둔다). */
export function redactExpiredChatMessageEvidence(report: ChatMessageReportDetail): ChatMessageReportDetail {
  if (!report.evidence.available || Date.parse(report.evidence.expiresAt) > Date.now()) return report;
  return {
    ...report,
    note: null,
    evidence: { ...report.evidence, available: false, response: null, userMessage: null },
  };
}
