import { z } from "zod";

export const notificationPreferenceSchema = z.object({
  isNewCommentEnabled: z.boolean(), isReplyEnabled: z.boolean(), isMentionEnabled: z.boolean(),
});

export type NotificationPreferenceFormValues = z.infer<typeof notificationPreferenceSchema>;
