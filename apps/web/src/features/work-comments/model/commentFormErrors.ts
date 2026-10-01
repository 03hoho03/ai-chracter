import { isApiError } from "@/shared/api/client";

import { commentErrorDetail, commentErrorMessage } from "./commentError";
import type { CommentFormValues } from "./schema";

type CommentFormError = { field: keyof CommentFormValues | "root"; message: string };

const FIELD_MESSAGES: Record<keyof CommentFormValues, string> = {
  body: "댓글 내용이나 스티커를 확인해주세요.",
  stickerId: "이 스티커는 더 이상 선택할 수 없어요. 다른 스티커를 선택해주세요.",
  mentions: "멘션할 수 없는 사용자가 있어요. 선택한 대상을 확인해주세요.",
  isSpoiler: "스포일러 표시를 확인해주세요.",
};
const SERVER_FIELDS: Record<string, keyof CommentFormValues | undefined> = {
  body: "body", stickerId: "stickerId", sticker_id: "stickerId",
  mentions: "mentions", mentionUserIds: "mentions", mention_user_ids: "mentions",
  isSpoiler: "isSpoiler", is_spoiler: "isSpoiler",
};

export function commentFormErrors(error: unknown): CommentFormError[] {
  if (isApiError(error) && error.status === 422) {
    const code = commentErrorDetail(error)?.code;
    if (code === "COMMENT_TEXT_TOO_LONG") return [{ field: "body", message: "댓글은 1,000자까지 입력할 수 있어요." }];
    if (code === "COMMENT_EMPTY") return [{ field: "body", message: "댓글 내용이나 스티커를 입력해주세요." }];
    if (code === "COMMENT_MENTION_INVALID") return [{ field: "mentions", message: FIELD_MESSAGES.mentions }];
    if (code === "COMMENT_STICKER_INVALID") return [{ field: "stickerId", message: FIELD_MESSAGES.stickerId }];
    const fields = new Set<keyof CommentFormValues>();
    for (const key of Object.keys(error.fields ?? {})) {
      const field = SERVER_FIELDS[key];
      if (field) fields.add(field);
    }
    if (fields.size) return Array.from(fields, (field) => ({ field, message: FIELD_MESSAGES[field] }));
  }
  return [{ field: "root", message: commentErrorMessage(error) }];
}
