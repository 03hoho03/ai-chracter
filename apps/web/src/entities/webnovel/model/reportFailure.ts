import { isApiError } from "@/shared/api/client";

/** 노벨·노벨 화·노벨 댓글 신고가 실패했을 때의 토스트 문장. */
export function toWebnovelReportErrorMessage(error: unknown): string {
  if (!isApiError(error)) return "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.";
  const code = typeof error.detail === "object" && error.detail !== null ? error.detail.code : undefined;
  if (code === "NOVEL_REPORT_OWN") return "내가 공개한 소설은 신고할 수 없어요.";
  if (code === "NOVEL_REPORT_RATE_LIMITED") return "신고를 짧은 시간에 많이 했어요. 잠시 후 다시 시도해주세요.";
  if (error.status === 404) return "지금은 신고할 수 없는 글이에요.";
  return "신고 접수에 실패했어요. 잠시 후 다시 시도해주세요.";
}
