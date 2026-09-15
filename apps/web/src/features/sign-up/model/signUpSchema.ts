import { z } from "zod";

const requiredAgreement = (message: string) =>
  z.boolean().refine((value) => value === true, { message });

// legal-revision-goal-prompt.md LR-9: 서버(auth/age.py MINIMUM_AGE_THRESHOLD)와 같은 임계값 —
// 서버가 진짜 게이트이고 이건 위저드 1스텝에서 거르는 UX다.
const MINIMUM_SIGNUP_AGE = 14;

function isUnderMinimumAge(birthDate: Date, today: Date): boolean {
  let age = today.getFullYear() - birthDate.getFullYear();
  const hasHadBirthdayThisYear =
    today.getMonth() > birthDate.getMonth() ||
    (today.getMonth() === birthDate.getMonth() && today.getDate() >= birthDate.getDate());
  if (!hasHadBirthdayThisYear) age -= 1;
  return age < MINIMUM_SIGNUP_AGE;
}

export const signUpSchema = z.object({
  email: z.email({ message: "이메일 형식이 올바르지 않습니다" }),
  password: z.string().min(8, { message: "비밀번호는 8자 이상이어야 합니다" }),
  nickname: z.string().min(1, { message: "닉네임을 입력해주세요" }),
  birthDate: z
    .string()
    .min(1, { message: "생년월일을 입력해주세요" })
    .refine((value) => new Date(value) <= new Date(), {
      message: "미래 날짜는 입력할 수 없습니다",
    })
    .refine((value) => !isUnderMinimumAge(new Date(value), new Date()), {
      message: "만 14세 미만은 가입할 수 없습니다",
    }),
  termsAgreed: requiredAgreement("이용약관에 동의해주세요"),
  privacyAgreed: requiredAgreement("개인정보 수집·이용에 동의해주세요"),
  // legal-revision-goal-prompt.md LR-1·LR-3 — 국외이전 동의를 수집·이용 동의에서 분리한다.
  transferAgreed: requiredAgreement("개인정보 국외이전에 동의해주세요"),
  // 2단계(이메일 인증)에서만 실제로 채워진다 — techspec-auth-onboarding.md §2.
  emailVerificationCode: z.string().length(6, { message: "6자리 코드를 입력해주세요" }),
});

export type SignUpFormValues = z.infer<typeof signUpSchema>;

export const signUpDefaultValues: SignUpFormValues = {
  email: "",
  password: "",
  nickname: "",
  birthDate: "",
  termsAgreed: false,
  privacyAgreed: false,
  transferAgreed: false,
  emailVerificationCode: "",
};
