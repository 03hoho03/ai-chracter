import { z } from "zod";

export const loginSchema = z.object({
  email: z.email({ message: "이메일 형식이 올바르지 않습니다" }),
  password: z.string().min(1, { message: "비밀번호를 입력해주세요" }),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

export const loginDefaultValues: LoginFormValues = {
  email: "",
  password: "",
};
