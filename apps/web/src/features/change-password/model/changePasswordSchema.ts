import { z } from "zod";

/** 현재/새 비밀번호 2개 필드뿐인 단순 폼이라 formToServer/serverToForm 분리 없이 API 요청 타입에 바로 맞춘다. */
export const CHANGE_PASSWORD_SCHEMA = z.object({
  currentPassword: z.string().min(1, { message: "현재 비밀번호를 입력해주세요" }),
  newPassword: z.string().min(8, { message: "비밀번호는 8자 이상이어야 합니다" }),
});

export type ChangePasswordFormValues = z.infer<typeof CHANGE_PASSWORD_SCHEMA>;

export const CHANGE_PASSWORD_DEFAULT_VALUES: ChangePasswordFormValues = {
  currentPassword: "",
  newPassword: "",
};
