import { Link } from "@tanstack/react-router";
import { useAtomValue } from "jotai";

import { SignUpWizard, signUpStepAtom } from "@/features/sign-up";

const STEP_COPY = {
  basicInfo: {
    title: "회원가입",
    description: "이메일과 기본 정보를 입력해주세요.",
  },
  emailVerify: {
    title: "이메일 인증",
    description: "받으신 인증코드를 입력해주세요.",
  },
  guardianConsent: {
    title: "법정대리인 동의",
    description: "보호자 정보를 입력하고 동의해주세요.",
  },
} as const;

export function SignUpPage() {
  const step = useAtomValue(signUpStepAtom);
  const { title, description } = STEP_COPY[step];

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>

          <SignUpWizard />

          {step === "basicInfo" && (
            <p className="mt-6 text-center text-sm text-muted-foreground">
              이미 계정이 있으신가요?{" "}
              <Link to="/login" className="font-medium text-primary hover:underline">
                로그인
              </Link>
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
