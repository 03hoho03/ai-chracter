import { isApiError } from "@/shared/api/client";

import { commentErrorMessage } from "./commentError";
import type { NotificationPreferenceFormValues } from "./notificationPreferenceSchema";

type NotificationPreferenceError = { field: keyof NotificationPreferenceFormValues | "root"; message: string };

const SERVER_FIELDS: Record<string, keyof NotificationPreferenceFormValues | undefined> = {
  newComment: "isNewCommentEnabled", new_comment: "isNewCommentEnabled",
  reply: "isReplyEnabled", mention: "isMentionEnabled",
};
const FIELD_MESSAGES: Record<keyof NotificationPreferenceFormValues, string> = {
  isNewCommentEnabled: "새 원댓글 알림 설정을 확인해주세요.",
  isReplyEnabled: "답글 알림 설정을 확인해주세요.",
  isMentionEnabled: "멘션 알림 설정을 확인해주세요.",
};

export function notificationPreferenceErrors(error: unknown): NotificationPreferenceError[] {
  if (isApiError(error) && error.status === 422) {
    const fields = new Set<keyof NotificationPreferenceFormValues>();
    for (const key of Object.keys(error.fields ?? {})) {
      const field = SERVER_FIELDS[key];
      if (field) fields.add(field);
    }
    if (fields.size) return Array.from(fields, (field) => ({ field, message: FIELD_MESSAGES[field] }));
  }
  return [{ field: "root", message: commentErrorMessage(error) }];
}
