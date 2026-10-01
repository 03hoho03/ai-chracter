import { isApiError } from "@/shared/api/client";

export function retryCommentRead(failureCount: number, error: unknown) {
  if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}
