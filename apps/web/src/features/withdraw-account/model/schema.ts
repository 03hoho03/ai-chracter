import { z } from "zod";

/** 비밀번호 계정의 탈퇴 재확인. 필드 하나뿐이라 formToServer/serverToForm 분리 없이 API 요청 타입에 바로 맞춘다. */
export const withdrawPasswordSchema = z.object({
  currentPassword: z.string().min(1, { message: "현재 비밀번호를 입력해주세요" }),
});

export type WithdrawPasswordFormValues = z.infer<typeof withdrawPasswordSchema>;

export const withdrawPasswordDefaultValues: WithdrawPasswordFormValues = {
  currentPassword: "",
};
