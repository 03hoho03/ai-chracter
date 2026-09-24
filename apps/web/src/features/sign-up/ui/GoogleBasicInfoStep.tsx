import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Link } from "@tanstack/react-router";
import { useFormContext } from "react-hook-form";

import { LOGIN_LINK_ERROR_TYPE } from "@/entities/session";

import type { SignUpFormValues } from "../model/signUpSchema";
import { LegalConsentFields } from "./LegalConsentFields";

const BASIC_INFO_FIELDS = [
  "nickname",
  "birthDate",
  "termsAgreed",
  "privacyAgreed",
  "transferAgreed",
] as const;

type GoogleBasicInfoStepProps = {
  onSubmit: () => void;
  isSubmitting: boolean;
}

export function GoogleBasicInfoStep({ onSubmit, isSubmitting }: GoogleBasicInfoStepProps) {
  const form = useFormContext<SignUpFormValues>();

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
      {errors.root && (
        <div role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          <p>{errors.root.message}</p>
          {/* 이 폼을 다시 내서는 풀리지 않는 실패의 출구(Q-10). 문장 밖 단독 줄이라 인라인 링크의
              `focus-visible:underline` 대신 링을 쓰고, 보더가 없어 링은 불투명이다(DESIGN §Focus). 색은 배너의
              `destructive-text`를 물려받고 항상 밑줄로 링크임을 보인다 — 빨간 틴트 안에 `primary`를 섞지 않는다. */}
          {errors.root.type === LOGIN_LINK_ERROR_TYPE && (
            <Link
              to="/login"
              className="mt-2 inline-block rounded-sm font-medium underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              로그인 화면으로 돌아가기
            </Link>
          )}
        </div>
      )}

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

      <LegalConsentFields />

      <Button type="submit" size="lg" disabled={isSubmitting}>
        {isSubmitting ? "처리 중..." : "다음"}
      </Button>
    </form>
  );
}
