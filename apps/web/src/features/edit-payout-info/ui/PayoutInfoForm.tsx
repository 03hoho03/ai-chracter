import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { BANK_CODES, BANK_LABELS } from "@/entities/creator-payout";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import { usePutPayoutInfoMutation } from "../api/usePutPayoutInfoMutation";
import { PAYOUT_INFO_CONSENT_LABEL, PAYOUT_INFO_CONSENT_NOTICE } from "../model/consentNotice";
import { formToServer } from "../model/formToServer";
import { PAYOUT_INFO_MESSAGES, toPayoutInfoFailure, toPayoutInfoFailureField } from "../model/payoutInfoResult";
import {
  payoutInfoDefaultValues,
  payoutInfoSchema,
  type PayoutInfoFormValues,
  type PayoutInfoSubmitValues,
} from "../model/schema";

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";
const DETAIL_SUMMARY_CLASS =
  "flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none [&::-webkit-details-marker]:hidden";
const FIELD_ERROR_CLASS = "text-xs break-keep text-destructive-text";

type PayoutInfoFormProps = {
  onSaved: () => void;
  /** 등록한 정보가 있을 때만 준다 — 처음 등록하는 자리에는 돌아갈 표시가 없다. */
  onCancel?: () => void;
  /** 버튼을 눌러 연 폼이면 참 — 누른 버튼이 폼으로 바뀌며 사라지므로 첫 칸(실명)으로 포커스를 옮긴다. 화면을 열자마자
   * 보이는 첫 등록 폼에는 주지 않는다(들어오자마자 포커스를 빼앗지 않는다). */
  focusOnOpen?: boolean;
};

/** 지급 정보 입력 폼. 실명·주민등록번호·은행·계좌번호와 수집·이용(국외 이전 포함) 동의 하나를 받는다. 동의는 이
 * 입력에만 걸리는 개별 동의라 미리 켜 두지 않고, 법정 고지는 정산 신청 동의와 같은 모양으로 "자세히"에 접어 둔다.
 *
 * 주민등록번호가 거절된 이유(외국인등록번호·본인인증 생년월일과 다름)는 그 칸 아래에, 나머지 실패는 폼 머리에 둔다.
 * 저장 중에는 `disabled` 대신 `aria-disabled` 로 막는다 — `disabled` 는 누른 버튼의 포커스를 날린다. */
export function PayoutInfoForm({ onSaved, onCancel, focusOnOpen = false }: PayoutInfoFormProps) {
  const id = useId();
  const fieldId = (name: keyof PayoutInfoFormValues) => `${id}-${name}`;
  const errorId = (name: keyof PayoutInfoFormValues) => `${id}-${name}-error`;
  const [isForeignerRejected, setIsForeignerRejected] = useState(false);
  const mutation = usePutPayoutInfoMutation();
  const {
    register,
    handleSubmit,
    control,
    setError,
    setFocus,
    clearErrors,
    formState: { errors },
  } = useForm<PayoutInfoFormValues, unknown, PayoutInfoSubmitValues>({
    resolver: zodResolver(payoutInfoSchema),
    defaultValues: payoutInfoDefaultValues,
  });

  // 칸의 DOM 은 RHF `register` 가 쥐고 있어, 마운트 뒤 RHF 의 `setFocus` 로 옮긴다.
  useEffect(() => {
    if (focusOnOpen) setFocus("legalName");
  }, [focusOnOpen, setFocus]);

  async function handleValidSubmit(values: PayoutInfoSubmitValues) {
    // 버튼은 `aria-disabled` 라 Enter 제출을 막지 못한다 — 진행 중 재제출은 여기서 끊는다.
    if (mutation.isPending) return;
    clearErrors("root");
    setIsForeignerRejected(false);
    try {
      await mutation.mutateAsync(formToServer(values));
      toast.success("지급 정보를 저장했어요.");
      onSaved();
    } catch (error) {
      const failure = toPayoutInfoFailure(error);
      // 재동의 모달이 대신 말한다(전역 뮤테이션 처리가 세션을 다시 읽어 띄운다).
      if (failure === "reconsentRequired") return;
      setIsForeignerRejected(failure === "foreigner");
      const message = PAYOUT_INFO_MESSAGES[failure];
      if (toPayoutInfoFailureField(failure) === "rrn") {
        setError("rrn", { type: "server", message }, { shouldFocus: true });
      } else {
        setError("root", { type: "server", message });
      }
    }
  }

  const describedBy = (name: keyof PayoutInfoFormValues, hintId?: string) =>
    [hintId, errors[name] ? errorId(name) : undefined].filter(Boolean).join(" ") || undefined;

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(handleValidSubmit)(event);
      }}
    >
      {errors.root && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
          {errors.root.message}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("legalName")}>실명</Label>
        <Input
          id={fieldId("legalName")}
          autoComplete="name"
          aria-invalid={!!errors.legalName}
          aria-describedby={describedBy("legalName")}
          {...register("legalName")}
        />
        {errors.legalName && (
          <p id={errorId("legalName")} role="alert" className={FIELD_ERROR_CLASS}>
            {errors.legalName.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("rrn")}>주민등록번호</Label>
        <Input
          id={fieldId("rrn")}
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          maxLength={14}
          placeholder="000000-0000000"
          aria-invalid={!!errors.rrn}
          aria-describedby={describedBy("rrn", `${id}-rrn-hint`)}
          {...register("rrn")}
        />
        <p id={`${id}-rrn-hint`} className="text-xs break-keep text-muted-foreground">
          본인인증한 생년월일과 같아야 해요. 화면에는 다시 보이지 않아요.
        </p>
        {errors.rrn && (
          <p id={errorId("rrn")} role="alert" className={FIELD_ERROR_CLASS}>
            {errors.rrn.message}
            {isForeignerRejected && (
              <>
                {" "}
                <Link to={SUPPORT_DESTINATIONS["inquiry-new"].to} className={INLINE_LINK_CLASS}>
                  {SUPPORT_DESTINATIONS["inquiry-new"].label}
                </Link>
              </>
            )}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("bankCode")}>은행</Label>
        <Controller
          control={control}
          name="bankCode"
          render={({ field }) => (
            <Select value={field.value ?? ""} onValueChange={field.onChange}>
              <SelectTrigger
                id={fieldId("bankCode")}
                ref={field.ref}
                className="w-full"
                aria-invalid={!!errors.bankCode}
                aria-describedby={describedBy("bankCode")}
              >
                <SelectValue placeholder="은행 선택" />
              </SelectTrigger>
              <SelectContent>
                {BANK_CODES.map((code) => (
                  <SelectItem key={code} value={code}>
                    {BANK_LABELS[code]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        {errors.bankCode && (
          <p id={errorId("bankCode")} role="alert" className={FIELD_ERROR_CLASS}>
            {errors.bankCode.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId("accountNumber")}>계좌번호</Label>
        <Input
          id={fieldId("accountNumber")}
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={!!errors.accountNumber}
          aria-describedby={describedBy("accountNumber", `${id}-account-hint`)}
          {...register("accountNumber")}
        />
        <p id={`${id}-account-hint`} className="text-xs break-keep text-muted-foreground">
          본인 명의 계좌만 받을 수 있어요. 하이픈은 넣어도 괜찮아요.
        </p>
        {errors.accountNumber && (
          <p id={errorId("accountNumber")} role="alert" className={FIELD_ERROR_CLASS}>
            {errors.accountNumber.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Controller
          control={control}
          name="agreed"
          render={({ field }) => (
            <label className="flex items-start gap-2 text-sm break-keep text-foreground">
              <Checkbox
                ref={field.ref}
                className="mt-0.5"
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                aria-invalid={!!errors.agreed}
                aria-describedby={describedBy("agreed")}
              />
              <span>
                <span className="text-muted-foreground">(필수)</span> {PAYOUT_INFO_CONSENT_LABEL}
              </span>
            </label>
          )}
        />
        {errors.agreed && (
          <p id={errorId("agreed")} role="alert" className={`pl-6 ${FIELD_ERROR_CLASS}`}>
            {errors.agreed.message}
          </p>
        )}
        <details className="group pl-6">
          <summary className={DETAIL_SUMMARY_CLASS}>
            <span className="group-open:hidden">자세히</span>
            <span className="hidden group-open:inline">접기</span>
            <ChevronDown
              aria-hidden
              className="size-3.5 motion-safe:transition-transform motion-safe:duration-200 group-open:rotate-180"
            />
          </summary>
          <dl className="mt-2 flex flex-col gap-3 rounded-lg border border-border p-3 text-xs text-muted-foreground motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
            {PAYOUT_INFO_CONSENT_NOTICE.map((item) => (
              <div key={item.term}>
                <dt className="font-semibold text-foreground">{item.term}</dt>
                <dd className="mt-0.5 break-keep">{item.detail}</dd>
              </div>
            ))}
          </dl>
        </details>
        <p className="pl-6 text-xs break-keep text-muted-foreground">
          자세한 내용은{" "}
          <Link to={SUPPORT_DESTINATIONS.privacy.to} target="_blank" rel="noopener" className={INLINE_LINK_CLASS}>
            {SUPPORT_DESTINATIONS.privacy.label}
          </Link>
          과{" "}
          <Link
            to={SUPPORT_DESTINATIONS["creator-payout-policy"].to}
            target="_blank"
            rel="noopener"
            className={INLINE_LINK_CLASS}
          >
            {SUPPORT_DESTINATIONS["creator-payout-policy"].label}
          </Link>
          에서 볼 수 있어요.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" aria-disabled={mutation.isPending} className="aria-disabled:opacity-65">
          {mutation.isPending ? "저장하는 중…" : "지급 정보 저장"}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            취소
          </Button>
        )}
      </div>
    </form>
  );
}
