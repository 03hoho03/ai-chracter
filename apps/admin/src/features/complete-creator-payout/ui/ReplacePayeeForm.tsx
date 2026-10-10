import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useRef, useState } from "react";
import { Controller, useForm, type FieldError } from "react-hook-form";
import { toast } from "sonner";

import {
  BANK_OPTIONS,
  isBankCode,
  toCreatorPayoutFailure,
  useReplaceCreatorPayoutPayeeMutation,
} from "@/entities/creator-payout";
import { apiErrorCode } from "@/shared/lib/api/client";

import {
  replacePayeeDefaultValues,
  replacePayeeFormToServer,
  replacePayeeSchema,
  type ReplacePayeeFormValues,
} from "../model/schema";

/** 주민등록번호 칸 하나를 가리키는 거절. 그 칸에 오류를 달고 포커스를 옮긴다. */
const RRN_FAILURE_CODES: ReadonlySet<string> = new Set([
  "CREATOR_PAYOUT_RRN_MISMATCH",
  "CREATOR_PAYOUT_FOREIGNER_UNSUPPORTED",
]);

type ReplacePayeeFormProps = {
  payoutId: string;
  onSuccess: () => void;
};

/**
 * 탈퇴한 회원에게 문의로 받은 새 수취 정보로 바꾼다. 넷을 모두 새로 받는다(서버는 원문을 돌려주지 않는다).
 *
 * 주민등록번호·계좌번호 칸은 브라우저 자동 완성·저장을 끈다 — 운영자 브라우저에 남의 값이 남으면 다음 입력에 제안으로
 * 뜬다. 성공하면 칸을 비우고, 이 폼이 사라지면(다른 처리를 고르거나 화면을 떠나면) 값도 함께 사라진다.
 *
 * 제출 중에는 버튼이 `disabled` 라 누른 버튼의 포커스가 `<body>` 로 떨어진다. 그래서 거절되면 포커스를 옮긴다 —
 * 주민등록번호 거절은 그 칸으로, 나머지는 실패 문장으로.
 */
export function ReplacePayeeForm({ payoutId, onSuccess }: ReplacePayeeFormProps) {
  const id = useId();
  const replaceMutation = useReplaceCreatorPayoutPayeeMutation(payoutId);
  const [failureMessage, setFailureMessage] = useState<string | null>(null);
  const shouldFocusFailureRef = useRef(false);
  const focusFailureIfJustFailed = (element: HTMLElement | null) => {
    if (!element || !shouldFocusFailureRef.current) return;
    shouldFocusFailureRef.current = false;
    element.focus();
  };
  const {
    control,
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ReplacePayeeFormValues>({
    resolver: zodResolver(replacePayeeSchema),
    defaultValues: replacePayeeDefaultValues,
  });

  const onSubmit = async (values: ReplacePayeeFormValues) => {
    // 검증이 은행을 목록 안으로 보장한다 — 타입을 좁히려는 확인이다.
    if (values.bankCode === null) return;
    setFailureMessage(null);
    try {
      await replaceMutation.mutateAsync(replacePayeeFormToServer({ ...values, bankCode: values.bankCode }));
      reset(replacePayeeDefaultValues);
      // 요청 본문을 뮤테이션 상태(`variables`)에 남기지 않는다.
      replaceMutation.reset();
      toast.success("수취 정보를 바꿨어요. 새 정보로 이체한 뒤 이체 완료를 기록해주세요.");
      onSuccess();
    } catch (error) {
      const failure = toCreatorPayoutFailure(error);
      if (failure.kind === "stale") {
        reset(replacePayeeDefaultValues);
        replaceMutation.reset();
        toast.error(failure.message);
        return;
      }
      const code = apiErrorCode(error);
      if (code !== null && RRN_FAILURE_CODES.has(code)) {
        setError("rrn", { type: "server", message: failure.message }, { shouldFocus: true });
        return;
      }
      shouldFocusFailureRef.current = true;
      setFailureMessage(failure.message);
    }
  };

  const fieldId = (name: string) => `${id}-${name}`;
  const errorId = (name: string) => `${id}-${name}-error`;

  return (
    <form
      noValidate
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-sm break-keep text-foreground">
        원천징수와 금액은 그대로이고 수취인만 바뀌어요. 새 주민등록번호의 생년월일은 지금 수취인 정보와 같아야 해요.
      </p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("name")}>실명</Label>
        <Input
          id={fieldId("name")}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={!!errors.legalName}
          aria-describedby={errors.legalName ? errorId("name") : undefined}
          {...register("legalName")}
        />
        <FieldErrorText id={errorId("name")} error={errors.legalName} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("rrn")}>주민등록번호</Label>
        <Input
          id={fieldId("rrn")}
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          placeholder="000000-0000000"
          aria-invalid={!!errors.rrn}
          aria-describedby={errors.rrn ? errorId("rrn") : undefined}
          {...register("rrn")}
        />
        <FieldErrorText id={errorId("rrn")} error={errors.rrn} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("bank")}>은행</Label>
        <Controller
          name="bankCode"
          control={control}
          render={({ field }) => (
            <Select
              value={field.value ?? ""}
              onValueChange={(value) => field.onChange(isBankCode(value) ? value : null)}
            >
              <SelectTrigger
                id={fieldId("bank")}
                className="w-full"
                aria-invalid={!!errors.bankCode}
                aria-describedby={errors.bankCode ? errorId("bank") : undefined}
              >
                <SelectValue placeholder="은행을 고르세요" />
              </SelectTrigger>
              <SelectContent>
                {BANK_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        <FieldErrorText id={errorId("bank")} error={errors.bankCode} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("account")}>계좌번호</Label>
        <Input
          id={fieldId("account")}
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          placeholder="숫자만 또는 하이픈 포함"
          aria-invalid={!!errors.accountNumber}
          aria-describedby={errors.accountNumber ? errorId("account") : undefined}
          {...register("accountNumber")}
        />
        <FieldErrorText id={errorId("account")} error={errors.accountNumber} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("reason")}>사유 (필수)</Label>
        <p id={`${id}-reason-hint`} className="text-xs break-keep text-muted-foreground">
          운영자만 보는 사유예요. 어느 문의로 받은 정보인지 적어주세요. 입력한 값은 기록에 남지 않아요.
        </p>
        <Textarea
          id={fieldId("reason")}
          rows={3}
          aria-invalid={!!errors.reasonText}
          aria-describedby={[`${id}-reason-hint`, errors.reasonText && errorId("reason")].filter(Boolean).join(" ")}
          {...register("reasonText")}
        />
        <FieldErrorText id={errorId("reason")} error={errors.reasonText} />
      </div>

      {failureMessage && (
        <p
          ref={focusFailureIfJustFailed}
          tabIndex={-1}
          role="alert"
          className="text-sm break-keep text-destructive-text outline-none"
        >
          {failureMessage}
        </p>
      )}

      <Button type="submit" className="self-end" disabled={isSubmitting}>
        {isSubmitting ? "바꾸는 중..." : "수취 정보 교체"}
      </Button>
    </form>
  );
}

function FieldErrorText({ id, error }: { id: string; error: FieldError | undefined }) {
  if (!error) return null;
  return (
    <p id={id} role="alert" className="text-xs break-keep text-destructive-text">
      {error.message}
    </p>
  );
}
