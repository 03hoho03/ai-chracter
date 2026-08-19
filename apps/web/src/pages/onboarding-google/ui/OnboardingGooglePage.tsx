import { useAtomValue } from "jotai";

import { OnboardingGoogleWizard, onboardingGoogleStepAtom } from "../../../features/onboarding-google";

const STEP_COPY = {
  basicInfo: {
    title: "추가 정보 입력",
    description: "닉네임과 생년월일을 입력하고 약관에 동의해주세요.",
  },
  guardianConsent: {
    title: "법정대리인 동의",
    description: "보호자 정보를 입력하고 동의해주세요.",
  },
} as const;

interface OnboardingGooglePageProps {
  token: string;
}

export function OnboardingGooglePage({ token }: OnboardingGooglePageProps) {
  const step = useAtomValue(onboardingGoogleStepAtom);
  const { title, description } = STEP_COPY[step];

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md">
        <div className="rounded-xl border border-border bg-card p-8">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>

          <OnboardingGoogleWizard token={token} />
        </div>
      </div>
    </main>
  );
}
