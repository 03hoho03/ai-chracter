import type { components } from "@ai-character-chat/api-types";

import type { ResetPasswordFormValues } from "./schema";

type PasswordResetConfirmRequest = components["schemas"]["PasswordResetConfirmRequest"];

export function toPasswordResetConfirmRequest(
  values: ResetPasswordFormValues,
  token: string,
): PasswordResetConfirmRequest {
  return { token, newPassword: values.newPassword };
}
