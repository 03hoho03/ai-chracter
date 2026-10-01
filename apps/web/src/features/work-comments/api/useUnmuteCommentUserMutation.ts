import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { commentApi, commentKeys } from "@/entities/comment";
import { notificationKeys } from "@/entities/notification";

import { commentErrorMessage } from "../model/commentError";

export function useUnmuteCommentUserMutation(viewerId: string) {
  const client = useQueryClient();
  return useMutation({
    networkMode: "always",
    mutationFn: (userId: string) => commentApi.mute(userId, false),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: commentKeys.viewer(viewerId) }),
      client.invalidateQueries({ queryKey: notificationKeys.viewer(viewerId) }),
    ]),
    onError: (error) => { toast.error(commentErrorMessage(error)); },
  });
}
