import type { components } from "@ai-character-chat/api-types";

import type { ResetPasswordFormValues } from "./resetPasswordSchema";

type PasswordResetConfirmRequest = components["schemas"]["PasswordResetConfirmRequest"];

export function formToServer(
  values: ResetPasswordFormValues,
  token: string,
): PasswordResetConfirmRequest {
  return { token, newPassword: values.newPassword };
}
