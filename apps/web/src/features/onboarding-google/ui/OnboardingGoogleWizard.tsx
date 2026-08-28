import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  GuardianConsentStep,
  signUpDefaultValues,
  signUpSchema,
  useGuardianConsentMutation,
  type SignUpFormValues,
} from "@/entities/registration";
import { sessionKeys } from "@/entities/session";
import { useOnboardingGoogleMutation } from "../api/mutations";
import { onboardingGoogleStepAtom } from "../model/atom";
import { BasicInfoStep } from "./BasicInfoStep";
import { isApiError } from "@/shared/lib/api/client";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

type OnboardingGoogleWizardProps = {
  token: string;
}

export function OnboardingGoogleWizard({ token }: OnboardingGoogleWizardProps) {
  const [step, setStep] = useAtom(onboardingGoogleStepAtom);
  const form = useForm<SignUpFormValues>({
    resolver: zodResolver(signUpSchema),
    defaultValues: signUpDefaultValues,
  });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const onboardingMutation = useOnboardingGoogleMutation();
  const guardianConsentMutation = useGuardianConsentMutation();

  async function completeOnboarding() {
    await queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    toast.success("가입을 환영해요!");
    await navigate({ to: "/" });
  }

  async function handleBasicInfoSubmit() {
    const { nickname, birthDate, termsAgreed, privacyAgreed } = form.getValues();
    try {
      const { isMinorGuardianRequired, email } = await onboardingMutation.mutateAsync({
        token,
        nickname,
        birthDate,
        termsAgreed,
        privacyAgreed,
      });

      if (isMinorGuardianRequired) {
        // guardian-consent가 계정을 email로 식별한다 — 이 폼엔 사용자가 직접 입력하는
        // 이메일 필드가 없으므로 온보딩 응답이 내려준 값을 재사용을 위해 폼에 채워둔다.
        form.setValue("email", email);
        setStep("guardianConsent");
        return;
      }

      await completeOnboarding();
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      if (apiError?.status === 400) {
        toast.error("인증이 만료되었어요. 처음부터 다시 시도해주세요.");
      } else {
        toast.error(GENERIC_ERROR_MESSAGE);
      }
    }
  }

  async function handleGuardianConsentSubmit() {
    const { email, guardian } = form.getValues();
    try {
      await guardianConsentMutation.mutateAsync({
        email,
        guardianName: guardian.name,
        guardianContact: guardian.contact,
        consentAgreed: guardian.consentAgreed,
      });
      await completeOnboarding();
    } catch {
      toast.error(GENERIC_ERROR_MESSAGE);
    }
  }

  if (step === "guardianConsent") {
    return (
      <GuardianConsentStep
        form={form}
        onSubmit={() => void handleGuardianConsentSubmit()}
        isSubmitting={guardianConsentMutation.isPending}
      />
    );
  }

  return (
    <BasicInfoStep
      form={form}
      onSubmit={() => void handleBasicInfoSubmit()}
      isSubmitting={onboardingMutation.isPending}
    />
  );
}
