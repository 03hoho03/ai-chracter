import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import type { UseFormReturn } from "react-hook-form";

import { LegalConsentFields, type SignUpFormValues } from "@/entities/registration";

const BASIC_INFO_FIELDS = ["nickname", "birthDate", "termsAgreed", "privacyAgreed"] as const;

type BasicInfoStepProps = {
  form: UseFormReturn<SignUpFormValues>;
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function BasicInfoStep({ form, onSubmit, isSubmitting }: BasicInfoStepProps) {
  const {
    register,
    trigger,
    formState: { errors },
  } = form;

  async function handleSubmit() {
    const isValid = await trigger(BASIC_INFO_FIELDS);
    if (isValid) onSubmit();
  }

  return (
    <form
      className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-2 flex flex-col gap-5 motion-safe:duration-200"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit();
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="onboarding-google-nickname">닉네임</Label>
        <Input
          id="onboarding-google-nickname"
          placeholder="다른 사용자에게 보여질 이름"
          aria-invalid={!!errors.nickname}
          aria-describedby={errors.nickname ? "onboarding-google-nickname-error" : undefined}
          {...register("nickname")}
        />
        {errors.nickname && (
          <p id="onboarding-google-nickname-error" role="alert" className="text-xs text-destructive-text">
            {errors.nickname.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="onboarding-google-birth-date">생년월일</Label>
        <Input
          id="onboarding-google-birth-date"
          type="date"
          max={new Date().toISOString().slice(0, 10)}
          aria-invalid={!!errors.birthDate}
          aria-describedby={errors.birthDate ? "onboarding-google-birth-date-error" : undefined}
          {...register("birthDate")}
        />
        {errors.birthDate && (
          <p id="onboarding-google-birth-date-error" role="alert" className="text-xs text-destructive-text">
            {errors.birthDate.message}
          </p>
        )}
      </div>

      <LegalConsentFields form={form} />

      <Button type="submit" size="lg" className="h-10" disabled={isSubmitting}>
        {isSubmitting ? "처리 중..." : "다음"}
      </Button>
    </form>
  );
}
