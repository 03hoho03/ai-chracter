import { useMutation, useQueryClient } from "@tanstack/react-query";

import { commentApi, commentKeys } from "@/entities/comment";

import type { NotificationPreferenceFormValues } from "../model/notificationPreferenceSchema";
import { notificationPreferenceFormToServer } from "../model/formToServer";

export function useSaveCommentPreferencesMutation(viewerId: string) {
  const client = useQueryClient();
  return useMutation({
    networkMode: "always",
    mutationFn: (values: NotificationPreferenceFormValues) => commentApi.savePreferences(notificationPreferenceFormToServer(values)),
    onSuccess: (updated) => { client.setQueryData(commentKeys.preferences(viewerId), updated); },
  });
}
