import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Controller, type UseFormReturn } from "react-hook-form";

import type { SignUpFormValues } from "../model/schema";

const GUARDIAN_FIELDS = [
  "guardian.name",
  "guardian.contact",
  "guardian.consentAgreed",
] as const;

interface GuardianConsentStepProps {
  form: UseFormReturn<SignUpFormValues>;
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function GuardianConsentStep({ form, onSubmit, isSubmitting }: GuardianConsentStepProps) {
  const {
    register,
    control,
    trigger,
    formState: { errors },
  } = form;

  async function handleSubmit() {
    const isValid = await trigger(GUARDIAN_FIELDS);
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
      <p className="text-sm text-muted-foreground">
        만 14세 미만은 법정대리인(보호자)의 동의가 있어야 가입을 완료할 수 있어요.
      </p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-guardian-name">법정대리인 이름</Label>
        <Input
          id="signup-guardian-name"
          aria-invalid={!!errors.guardian?.name}
          aria-describedby={errors.guardian?.name ? "signup-guardian-name-error" : undefined}
          {...register("guardian.name")}
        />
        {errors.guardian?.name && (
          <p id="signup-guardian-name-error" role="alert" className="text-xs text-destructive">
            {errors.guardian.name.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-guardian-contact">법정대리인 연락처</Label>
        <Input
          id="signup-guardian-contact"
          type="tel"
          placeholder="010-0000-0000"
          aria-invalid={!!errors.guardian?.contact}
          aria-describedby={
            errors.guardian?.contact ? "signup-guardian-contact-error" : undefined
          }
          {...register("guardian.contact")}
        />
        {errors.guardian?.contact && (
          <p
            id="signup-guardian-contact-error"
            role="alert"
            className="text-xs text-destructive"
          >
            {errors.guardian.contact.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border p-4">
        <Controller
          name="guardian.consentAgreed"
          control={control}
          render={({ field }) => (
            <label className="flex items-center gap-2 text-sm text-foreground">
              <Checkbox
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                aria-invalid={!!errors.guardian?.consentAgreed}
              />
              (필수) 법정대리인 동의
            </label>
          )}
        />
        {errors.guardian?.consentAgreed && (
          <p role="alert" className="pl-6 text-xs text-destructive">
            {errors.guardian.consentAgreed.message}
          </p>
        )}
      </div>

      <Button type="submit" size="lg" className="h-10" disabled={isSubmitting}>
        {isSubmitting ? "처리 중..." : "동의하고 가입 완료"}
      </Button>
    </form>
  );
}
