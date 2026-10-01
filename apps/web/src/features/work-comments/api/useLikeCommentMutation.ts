import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { commentApi, commentKeys } from "@/entities/comment";

import { commentErrorMessage } from "../model/commentError";

export function useLikeCommentMutation(commentId: string, contentId: string, viewerId: string) {
  const client = useQueryClient();
  return useMutation({
    networkMode: "always",
    mutationFn: (isLiked: boolean) => commentApi.like(commentId, isLiked),
    onSuccess: () => client.invalidateQueries({ queryKey: commentKeys.content(viewerId, contentId) }),
    onError: (error) => toast.error(commentErrorMessage(error)),
  });
}
