import { z } from "zod";

export const NOTIFICATION_PREFERENCE_SCHEMA = z.object({
  isNewCommentEnabled: z.boolean(), isReplyEnabled: z.boolean(), isMentionEnabled: z.boolean(),
});

export type NotificationPreferenceFormValues = z.infer<typeof NOTIFICATION_PREFERENCE_SCHEMA>;
