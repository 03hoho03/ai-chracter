import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { Controller, type UseFormReturn } from "react-hook-form";

import type { SignUpFormValues } from "../model/schema";

type LegalConsentFieldsProps = {
  form: UseFormReturn<SignUpFormValues>;
};

/** 이메일 가입과 구글 온보딩 두 스텝이 이 fieldset을 바이트 단위로 똑같이 갖고 있어 내렸다 —
 * 문구·링크 수정이 한쪽에만 적용되는 사고를 막는 게 목적이다. `GuardianConsentStep`과 같은 결로
 * 폼을 통째로 받는다(두 스텝 모두 같은 `SignUpFormValues`를 쓴다). */
export function LegalConsentFields({ form }: LegalConsentFieldsProps) {
  const {
    control,
    setValue,
    formState: { errors },
  } = form;
  const [termsAgreed, privacyAgreed] = form.watch(["termsAgreed", "privacyAgreed"]);

  return (
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
              <span>
                (필수){" "}
                <a
                  href="/terms"
                  target="_blank"
                  rel="noopener noreferrer"
                  // 링크가 체크박스 라벨 안에 있으면 클릭이 label까지 버블링해 체크박스도 함께
                  // 토글된다 — stopPropagation으로 링크 클릭과 체크박스 토글을 분리한다.
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium text-primary hover:underline focus-visible:underline"
                >
                  이용약관
                </a>{" "}
                동의
              </span>
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
              <span>
                (필수){" "}
                <a
                  href="/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(event) => event.stopPropagation()}
                  className="font-medium text-primary hover:underline focus-visible:underline"
                >
                  개인정보처리방침
                </a>{" "}
                동의
              </span>
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
  );
}
