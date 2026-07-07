import { z } from "zod";

export const resetPasswordSchema = z
  .object({
    newPassword: z.string().min(8, { message: "비밀번호는 8자 이상이어야 합니다" }),
    confirmPassword: z.string().min(1, { message: "비밀번호를 다시 입력해주세요" }),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "비밀번호가 일치하지 않습니다",
    path: ["confirmPassword"],
  });

export type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

export const resetPasswordDefaultValues: ResetPasswordFormValues = {
  newPassword: "",
  confirmPassword: "",
};
