import { useState } from "react";
import { Link } from "@tanstack/react-router";

import { SocialLoginButtons } from "@/features/login";
import { SignUpWizard, type SignUpStep } from "@/features/sign-up";

const STEP_COPY = {
  basicInfo: {
    title: "회원가입",
    description: "이메일과 기본 정보를 입력해주세요.",
  },
  emailVerify: {
    title: "이메일 인증",
    description: "받으신 인증코드를 입력해주세요.",
  },
} as const;

export function SignUpPage() {
  const [step, setStep] = useState<SignUpStep>("basicInfo");
  const { title, description } = STEP_COPY[step];

  return (
    <main className="flex min-h-below-header items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>

          <SignUpWizard mode="email" step={step} onStepChange={setStep} />

          {/* 소셜 버튼은 로그인 화면과 같은 묶음·같은 자리(폼 아래, 계정 전환 링크 위)다. 기본 정보 스텝에서만
              보인다 — 이메일 인증 스텝에서 누르면 이미 서버에 만든 가입을 두고 떠나게 된다. 간격은 로그인
              화면의 폼 컬럼 `gap-5`와 같게 둔다. */}
          {step === "basicInfo" && (
            <div className="mt-5 flex flex-col gap-5">
              <SocialLoginButtons />
              <p className="text-center text-sm text-muted-foreground">
                이미 계정이 있으신가요?{" "}
                <Link to="/login" className="font-medium text-primary hover:underline">
                  로그인
                </Link>
              </p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
