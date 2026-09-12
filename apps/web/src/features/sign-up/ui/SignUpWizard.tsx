import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";

import { sessionKeys } from "@/entities/session";
import { isApiError } from "@/shared/api/client";

import {
  useSignUpLoginMutation,
  useSignUpMutation,
  useVerifyEmailMutation,
} from "../api/mutations";
import { useGuardianConsentMutation } from "../api/useGuardianConsentMutation";
import { useOnboardingGoogleMutation } from "../api/useOnboardingGoogleMutation";
import {
  toGuardianConsentRequest,
  toOnboardingGoogleRequest,
  toSignUpLoginRequest,
  toSignupRequest,
  toVerifyEmailRequest,
} from "../model/formToServer";
import { signUpDefaultValues, signUpSchema, type SignUpFormValues } from "../model/signUpSchema";
import { BasicInfoStep } from "./BasicInfoStep";
import { EmailVerifyStep } from "./EmailVerifyStep";
import { GoogleBasicInfoStep } from "./GoogleBasicInfoStep";
import { GuardianConsentStep } from "./GuardianConsentStep";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

export type SignUpStep = "basicInfo" | "emailVerify" | "guardianConsent";

/** 구글 온보딩은 비밀번호를 받지 않아 이메일 인증 스텝에 도달하지 않는다. */
export type GoogleSignUpStep = Exclude<SignUpStep, "emailVerify">;

// 현재 스텝은 page의 `useState`가 소유한다 — 위저드가 전역 atom을 들고 있으면 라우트를 떠난 뒤에도
// 스텝이 살아남아, 폼 값만 비워진 채 중간 스텝으로 재진입하는 막다른 상태가 된다.
type SignUpWizardProps =
  | {
      mode: "email";
      step: SignUpStep;
      onStepChange: (step: SignUpStep) => void;
    }
  | {
      mode: "google";
      token: string;
      step: GoogleSignUpStep;
      onStepChange: (step: GoogleSignUpStep) => void;
    };

export function SignUpWizard(props: SignUpWizardProps) {
  const { step } = props;
  const form = useForm<SignUpFormValues>({
    resolver: zodResolver(signUpSchema),
    defaultValues: signUpDefaultValues,
  });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const signUpMutation = useSignUpMutation();
  const verifyEmailMutation = useVerifyEmailMutation();
  const onboardingMutation = useOnboardingGoogleMutation();
  const guardianConsentMutation = useGuardianConsentMutation();
  const loginMutation = useSignUpLoginMutation();

  async function completeSignUp() {
    await queryClient.invalidateQueries({ queryKey: sessionKeys.current() });
    toast.success("가입을 환영해요!");
    await navigate({ to: "/" });
  }

  async function handleEmailBasicInfoSubmit(onStepChange: (step: SignUpStep) => void) {
    try {
      await signUpMutation.mutateAsync(toSignupRequest(form.getValues()));
      onStepChange("emailVerify");
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      if (apiError?.status === 409) {
        form.setError("email", { message: "이미 가입된 이메일이에요." });
      } else {
        toast.error(GENERIC_ERROR_MESSAGE);
      }
    }
  }

  async function handleEmailVerifySubmit(onStepChange: (step: SignUpStep) => void) {
    const values = form.getValues();
    try {
      const { isMinorGuardianRequired } = await verifyEmailMutation.mutateAsync(
        toVerifyEmailRequest(values),
      );

      if (isMinorGuardianRequired) {
        onStepChange("guardianConsent");
        return;
      }

      // 성인 경로: 이메일 인증만으로는 세션이 발급되지 않으므로, 방금 만든 계정으로
      // 직접 로그인해 세션을 발급시킨다 (apps/api/CLAUDE.md의 me_router 세션 발급 규약 참고).
      await loginMutation.mutateAsync(toSignUpLoginRequest(values));
      await completeSignUp();
    } catch (error) {
      const apiError = isApiError(error) ? error : null;
      if (apiError?.status === 400) {
        form.setError("emailVerificationCode", {
          message: "인증 코드가 올바르지 않거나 만료되었어요.",
        });
      } else {
        toast.error(GENERIC_ERROR_MESSAGE);
      }
    }
  }

  async function handleGoogleBasicInfoSubmit(
    token: string,
    onStepChange: (step: GoogleSignUpStep) => void,
  ) {
    try {
      const { isMinorGuardianRequired, email } = await onboardingMutation.mutateAsync(
        toOnboardingGoogleRequest(form.getValues(), token),
      );

      if (isMinorGuardianRequired) {
        // guardian-consent가 계정을 email로 식별한다 — 이 폼엔 사용자가 직접 입력하는
        // 이메일 필드가 없으므로 온보딩 응답이 내려준 값을 재사용을 위해 폼에 채워둔다.
        form.setValue("email", email);
        onStepChange("guardianConsent");
        return;
      }

      await completeSignUp();
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
    try {
      await guardianConsentMutation.mutateAsync(toGuardianConsentRequest(form.getValues()));
      await completeSignUp();
    } catch {
      toast.error(GENERIC_ERROR_MESSAGE);
    }
  }

  // 스텝 분기를 평범한 함수로 뽑아 `FormProvider`가 모든 갈래를 한 번에 감싸게 한다
  // (컴포넌트가 아니라 함수라 호출부에서 새 identity가 생기지 않는다 — 스텝 전환에 리마운트 없음).
  // `mode === "google"` 분기를 `emailVerify`보다 먼저 두는 이유: 이메일 전용 `onStepChange`(`SignUpStep` 콜백)를
  // 꺼내려면 구글 갈래가 먼저 return해야 narrowing이 된다. 구글이 이메일 인증 스텝에 닿지 않는 보증 자체는
  // 이 순서가 아니라 props 유니언(`GoogleSignUpStep`)이 page 경계에서 이미 하고 있다.
  function renderStep() {
    if (step === "guardianConsent") {
      return (
        <GuardianConsentStep
          onSubmit={() => void handleGuardianConsentSubmit()}
          isSubmitting={guardianConsentMutation.isPending}
        />
      );
    }

    if (props.mode === "google") {
      const { token, onStepChange } = props;
      return (
        <GoogleBasicInfoStep
          onSubmit={() => void handleGoogleBasicInfoSubmit(token, onStepChange)}
          isSubmitting={onboardingMutation.isPending}
        />
      );
    }

    const { onStepChange } = props;

    if (step === "emailVerify") {
      return (
        <EmailVerifyStep
          onSubmit={() => void handleEmailVerifySubmit(onStepChange)}
          isSubmitting={verifyEmailMutation.isPending || loginMutation.isPending}
        />
      );
    }

    return (
      <BasicInfoStep
        onSubmit={() => void handleEmailBasicInfoSubmit(onStepChange)}
        isSubmitting={signUpMutation.isPending}
      />
    );
  }

  return <FormProvider {...form}>{renderStep()}</FormProvider>;
}
