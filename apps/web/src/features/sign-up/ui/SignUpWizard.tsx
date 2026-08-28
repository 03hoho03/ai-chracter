import type { ApiError } from "@ai-character-chat/api-types";
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
import {
  useSignUpLoginMutation,
  useSignUpMutation,
  useVerifyEmailMutation,
} from "../api/mutations";
import { signUpStepAtom } from "../model/atom";
import { BasicInfoStep } from "./BasicInfoStep";
import { EmailVerifyStep } from "./EmailVerifyStep";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

export function SignUpWizard() {
  const [step, setStep] = useAtom(signUpStepAtom);
  const form = useForm<SignUpFormValues>({
    resolver: zodResolver(signUpSchema),
    defaultValues: signUpDefaultValues,
  });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const signUpMutation = useSignUpMutation();
  const verifyEmailMutation = useVerifyEmailMutation();
  const guardianConsentMutation = useGuardianConsentMutation();
  const loginMutation = useSignUpLoginMutation();

  async function completeSignUp() {
    await queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    toast.success("가입을 환영해요!");
    await navigate({ to: "/" });
  }

  async function handleBasicInfoSubmit() {
    const { email, password, nickname, birthDate, termsAgreed, privacyAgreed } =
      form.getValues();
    try {
      await signUpMutation.mutateAsync({
        email,
        password,
        nickname,
        birthDate,
        termsAgreed,
        privacyAgreed,
      });
      setStep("emailVerify");
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.status === 409) {
        form.setError("email", { message: "이미 가입된 이메일이에요." });
      } else {
        toast.error(GENERIC_ERROR_MESSAGE);
      }
    }
  }

  async function handleEmailVerifySubmit() {
    const { email, password, emailVerificationCode } = form.getValues();
    try {
      const { isMinorGuardianRequired } = await verifyEmailMutation.mutateAsync({
        email,
        code: emailVerificationCode,
      });

      if (isMinorGuardianRequired) {
        setStep("guardianConsent");
        return;
      }

      // 성인 경로: 이메일 인증만으로는 세션이 발급되지 않으므로, 방금 만든 계정으로
      // 직접 로그인해 세션을 발급시킨다 (apps/api/CLAUDE.md의 me_router 세션 발급 규약 참고).
      await loginMutation.mutateAsync({ email, password });
      await completeSignUp();
    } catch (error) {
      const apiError = error as ApiError;
      if (apiError.status === 400) {
        form.setError("emailVerificationCode", {
          message: "인증 코드가 올바르지 않거나 만료되었어요.",
        });
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
      await completeSignUp();
    } catch {
      toast.error(GENERIC_ERROR_MESSAGE);
    }
  }

  if (step === "emailVerify") {
    return (
      <EmailVerifyStep
        form={form}
        onSubmit={() => void handleEmailVerifySubmit()}
        isSubmitting={verifyEmailMutation.isPending || loginMutation.isPending}
      />
    );
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
      isSubmitting={signUpMutation.isPending}
    />
  );
}
