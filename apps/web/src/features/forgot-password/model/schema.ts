import { z } from "zod";

export const forgotPasswordSchema = z.object({
  email: z.email({ message: "이메일 형식이 올바르지 않습니다" }),
});

export type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

export const forgotPasswordDefaultValues: ForgotPasswordFormValues = {
  email: "",
};
