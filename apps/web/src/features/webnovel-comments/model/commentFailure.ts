import { isApiError } from "@/shared/api/client";

/** 화 댓글 쓰기가 실패했을 때 입력칸 밑에 보일 문장. 쓴 글은 입력칸에 그대로 남는다. */
export function toCommentWriteError(error: unknown): string {
  if (!isApiError(error)) return "댓글을 남기지 못했어요. 잠시 후 다시 시도해 주세요.";
  const code = typeof error.detail === "object" && error.detail !== null ? error.detail.code : undefined;
  if (code === "NOVEL_COMMENT_EMPTY") return "댓글 내용을 입력해 주세요.";
  if (code === "NOVEL_COMMENT_TOO_LONG") return "댓글은 1,000자까지 쓸 수 있어요.";
  if (code === "NOVEL_COMMENT_RATE_LIMITED") return "댓글을 짧은 시간에 많이 남겼어요. 잠시 후 다시 남겨 주세요.";
  if (error.status === 403 && code === "NOVEL_CHAPTER_LOCKED") return "소장한 화에만 댓글을 남길 수 있어요.";
  if (error.status === 403) return "지금 이 계정으로는 댓글을 남길 수 없어요.";
  if (error.status === 404) return "지금은 이 화에 댓글을 남길 수 없어요.";
  return "댓글을 남기지 못했어요. 잠시 후 다시 시도해 주세요.";
}

/** 댓글 본문의 글자 수 상한 — 서버와 같은 값(화면에 보이는 글자 수). */
export const WEBNOVEL_COMMENT_MAX_LENGTH = 1000;

/** 화면에 보이는 글자 수(이모지·결합 문자를 한 글자로). 서버도 같은 단위로 센다. */
export function countVisibleCharacters(text: string): number {
  return [...new Intl.Segmenter("ko", { granularity: "grapheme" }).segment(text)].length;
}
