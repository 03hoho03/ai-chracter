import type { components } from "@ai-character-chat/api-types";

import type { CommentPreferences } from "@/entities/comment";

import type { NotificationPreferenceFormValues } from "../model/notificationPreferenceSchema";

export function notificationPreferenceServerToForm(preferences: CommentPreferences): NotificationPreferenceFormValues {
  return {
    isNewCommentEnabled: preferences.newComment,
    isReplyEnabled: preferences.reply,
    isMentionEnabled: preferences.mention,
  };
}

export function notificationPreferenceFormToServer(values: NotificationPreferenceFormValues): components["schemas"]["CommentNotificationPreferencesUpdateRequest"] {
  return { newComment: values.isNewCommentEnabled, reply: values.isReplyEnabled, mention: values.isMentionEnabled };
}
