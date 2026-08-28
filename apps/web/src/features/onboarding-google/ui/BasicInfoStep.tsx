import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Controller, type UseFormReturn } from "react-hook-form";

import type { SignUpFormValues } from "../../../entities/registration";

const BASIC_INFO_FIELDS = ["nickname", "birthDate", "termsAgreed", "privacyAgreed"] as const;

interface BasicInfoStepProps {
  form: UseFormReturn<SignUpFormValues>;
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function BasicInfoStep({ form, onSubmit, isSubmitting }: BasicInfoStepProps) {
  const {
    register,
    control,
    trigger,
    setValue,
    formState: { errors },
  } = form;
  const [termsAgreed, privacyAgreed] = form.watch(["termsAgreed", "privacyAgreed"]);

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

      <fieldset className="flex flex-col gap-3 rounded-lg border border-border p-4">
        <legend className="sr-only">약관 동의</legend>
        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Checkbox
            checked={termsAgreed && privacyAgreed}
            onCheckedChange={(checked) => {
              setValue("termsAgreed", checked === true, { shouldValidate: true });
              setValue("privacyAgreed", checked === true, { shouldValidate: true });
            }}
          />
          전체 동의
        </label>

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <Controller
            name="termsAgreed"
            control={control}
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={field.value}
                  onCheckedChange={(checked) => field.onChange(checked === true)}
                  aria-invalid={!!errors.termsAgreed}
                />
                (필수) 이용약관 동의
              </label>
            )}
          />
          {errors.termsAgreed && (
            <p role="alert" className="pl-6 text-xs text-destructive-text">
              {errors.termsAgreed.message}
            </p>
          )}

          <Controller
            name="privacyAgreed"
            control={control}
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={field.value}
                  onCheckedChange={(checked) => field.onChange(checked === true)}
                  aria-invalid={!!errors.privacyAgreed}
                />
                (필수) 개인정보처리방침 동의
              </label>
            )}
          />
          {errors.privacyAgreed && (
            <p role="alert" className="pl-6 text-xs text-destructive-text">
              {errors.privacyAgreed.message}
            </p>
          )}
        </div>
      </fieldset>

      <Button type="submit" size="lg" className="h-10" disabled={isSubmitting}>
        {isSubmitting ? "처리 중..." : "다음"}
      </Button>
    </form>
  );
}
