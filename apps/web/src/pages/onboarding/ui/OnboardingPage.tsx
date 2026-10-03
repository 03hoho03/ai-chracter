import { useState } from "react";

import type { SocialProvider } from "@/entities/session";
import { SignUpWizard, type SocialSignUpStep } from "@/features/sign-up";

type OnboardingPageProps = {
  provider: SocialProvider;
}

const STEP_COPY = {
  basicInfo: {
    title: "추가 정보 입력",
    description: "닉네임과 생년월일을 입력하고 약관에 동의해주세요.",
  },
} as const;

/** 소셜 로그인 신규 가입자의 온보딩. 제공자는 라우트(`/onboarding/google`·`/onboarding/kakao`)가 정하고,
 * 화면은 제공자와 무관하게 같다. */
export function OnboardingPage({ provider }: OnboardingPageProps) {
  const [step, setStep] = useState<SocialSignUpStep>("basicInfo");
  const { title, description } = STEP_COPY[step];

  return (
    <main className="flex min-h-below-header items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>

          <SignUpWizard mode={provider} step={step} onStepChange={setStep} />
        </div>
      </div>
    </main>
  );
}
