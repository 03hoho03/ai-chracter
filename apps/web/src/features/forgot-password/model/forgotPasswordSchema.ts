import { z } from "zod";

export const FORGOT_PASSWORD_SCHEMA = z.object({
  email: z.email({ message: "이메일 형식이 올바르지 않습니다" }),
});

export type ForgotPasswordFormValues = z.infer<typeof FORGOT_PASSWORD_SCHEMA>;

export const FORGOT_PASSWORD_DEFAULT_VALUES: ForgotPasswordFormValues = {
  email: "",
};
