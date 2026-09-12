import { z } from "zod";

const requiredAgreement = (message: string) =>
  z.boolean().refine((value) => value === true, { message });

export const signUpSchema = z.object({
  email: z.email({ message: "이메일 형식이 올바르지 않습니다" }),
  password: z.string().min(8, { message: "비밀번호는 8자 이상이어야 합니다" }),
  nickname: z.string().min(1, { message: "닉네임을 입력해주세요" }),
  birthDate: z
    .string()
    .min(1, { message: "생년월일을 입력해주세요" })
    .refine((value) => new Date(value) <= new Date(), {
      message: "미래 날짜는 입력할 수 없습니다",
    }),
  termsAgreed: requiredAgreement("이용약관에 동의해주세요"),
  privacyAgreed: requiredAgreement("개인정보처리방침에 동의해주세요"),
  // 2단계(이메일 인증)에서만 실제로 채워진다 — techspec-auth-onboarding.md §2.
  emailVerificationCode: z.string().length(6, { message: "6자리 코드를 입력해주세요" }),
  // 3단계(법정대리인 동의)는 만 14세 미만일 때만 노출된다 — techspec-auth-onboarding.md §2.
  guardian: z.object({
    name: z.string().min(1, { message: "보호자 이름을 입력해주세요" }),
    contact: z.string().min(1, { message: "보호자 연락처를 입력해주세요" }),
    consentAgreed: requiredAgreement("법정대리인 동의가 필요합니다"),
  }),
});

export type SignUpFormValues = z.infer<typeof signUpSchema>;

export const signUpDefaultValues: SignUpFormValues = {
  email: "",
  password: "",
  nickname: "",
  birthDate: "",
  termsAgreed: false,
  privacyAgreed: false,
  emailVerificationCode: "",
  guardian: { name: "", contact: "", consentAgreed: false },
};
