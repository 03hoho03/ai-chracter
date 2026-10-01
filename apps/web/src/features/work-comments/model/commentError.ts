import { z } from "zod";

import { isApiError } from "@/shared/api/client";

const detailSchema = z.object({ code: z.string().optional(), retryAfterSeconds: z.number().nonnegative().optional() });

export function commentErrorDetail(error: unknown) {
  if (!isApiError(error)) return undefined;
  const detail = detailSchema.safeParse(error.detail);
  return detail.success ? detail.data : undefined;
}

export function commentErrorMessage(error: unknown): string {
  if (!isApiError(error)) return "요청을 처리하지 못했어요. 입력은 그대로 남아 있어요.";
  const detail = commentErrorDetail(error);
  const code = detail?.code;
  if (error.status === 401) return "로그인이 만료됐어요. 다시 로그인해주세요. 작성 중인 내용은 유지돼요.";
  if (code === "COMMENTS_PAUSED") return "작가가 새 댓글 작성을 중지했어요. 입력은 그대로 남아 있어요.";
  if (code === "LEGAL_RECONSENT_REQUIRED") return "변경된 약관에 동의한 뒤 다시 시도해주세요.";
  if (error.status === 429) {
    const seconds = detail?.retryAfterSeconds;
    return seconds ? seconds + "초 후 다시 시도할 수 있어요. 입력은 유지돼요." : "댓글을 너무 빠르게 남겼어요. 잠시 후 다시 시도해주세요.";
  }
  if (error.status === 403) return "현재 계정이나 작품 상태에서는 이 행동을 할 수 없어요.";
  if (error.status === 404 || code === "COMMENT_DELETED") return "현재 이 댓글을 이용할 수 없어요.";
  if (error.status === 409) return "댓글 상태가 바뀌었어요. 목록을 확인한 뒤 다시 시도해주세요.";
  if (code === "COMMENT_MENTION_INVALID") return "멘션할 수 없는 사용자가 있어요. 선택한 대상을 확인해주세요.";
  if (code === "COMMENT_STICKER_INVALID") return "이 스티커는 더 이상 선택할 수 없어요. 다른 스티커를 선택해주세요.";
  if (error.status === 422) return "댓글 내용·멘션·스티커를 확인해주세요.";
  return "요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.";
}
