import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Controller, useForm } from "react-hook-form";

import {
  BANK_LABELS,
  isPayeeInfoViewReasonCategory,
  PAYEE_INFO_VIEW_REASON_CATEGORY_OPTIONS,
  toCreatorPayoutFailure,
  type BankCode,
} from "@/entities/creator-payout";

import { useViewPayeeInfoMutation, type AdminPayeeInfoViewResponse } from "../api/useViewPayeeInfoMutation";
import { viewPayeeReasonSchema, type ViewPayeeReasonFormValues } from "../model/schema";

type PayeeInfoRevealProps = {
  payoutId: string;
  maskedName: string;
  bankCode: BankCode;
  accountLast4: string;
};

type RevealStage = { kind: "masked" } | { kind: "asking" } | { kind: "revealed"; info: AdminPayeeInfoViewResponse };

/**
 * 수취인 지급 정보. 평소에는 마스킹 값(실명 첫·끝 글자, 은행, 계좌 끝 4자리)만 보이고, 사유를 적어야 원문(실명·주민등록번호·
 * 계좌번호)을 연다 — 여는 것마다 서버에 감사 1행이 남는다.
 *
 * 원문은 이 컴포넌트의 지역 상태에만 있다. "가리기"를 누르거나 화면을 떠나면(언마운트) 사라지고, 다시 보려면 사유를 다시
 * 적는다. 수취 정보가 바뀌면 호출부가 `key` 를 바꿔 낡은 원문을 버린다. 탭 제목에는 이름을 싣지 않는다(화면이 그렇게 둔다).
 *
 * 단계가 바뀌면 누른 버튼(원문 보기·원문 열기·취소·가리기)이 사라진다. 그대로 두면 포커스가 `<body>` 로 떨어지므로,
 * 사유 폼이 열리면 첫 칸으로, 원문이 열리거나 다시 가려지면 수취인 블록으로 옮긴다.
 */
export function PayeeInfoReveal({ payoutId, maskedName, bankCode, accountLast4 }: PayeeInfoRevealProps) {
  const [stage, setStage] = useState<RevealStage>({ kind: "masked" });
  const shouldFocusPayeeRef = useRef(false);
  const focusPayeeIfJustChanged = (element: HTMLElement | null) => {
    if (!element || !shouldFocusPayeeRef.current) return;
    shouldFocusPayeeRef.current = false;
    element.focus();
  };
  const showPayee = (next: Exclude<RevealStage, { kind: "asking" }>) => {
    shouldFocusPayeeRef.current = true;
    setStage(next);
  };

  return (
    <div className="flex flex-col gap-4">
      <div
        ref={focusPayeeIfJustChanged}
        tabIndex={-1}
        role="group"
        aria-label={stage.kind === "revealed" ? "수취인 지급 정보 원문" : "수취인 지급 정보"}
        className="outline-none"
      >
        {stage.kind === "revealed" ? (
          <dl className="grid gap-x-6 gap-y-3 text-sm @xl:grid-cols-2">
            <PayeeField label="실명" value={stage.info.legalName} />
            <PayeeField label="주민등록번호" value={formatRrn(stage.info.rrn)} />
            <PayeeField label="은행" value={BANK_LABELS[stage.info.bankCode]} />
            <PayeeField label="계좌번호" value={stage.info.accountNumber} />
          </dl>
        ) : (
          <dl className="grid gap-x-6 gap-y-3 text-sm @xl:grid-cols-2">
            <PayeeField label="실명" value={maskedName} />
            <PayeeField label="주민등록번호" value="등록됨" />
            <PayeeField label="은행" value={BANK_LABELS[bankCode]} />
            <PayeeField label="계좌번호" value={`****${accountLast4}`} />
          </dl>
        )}
      </div>

      {stage.kind === "masked" && (
        <Button type="button" variant="outline" size="sm" className="self-start hover:bg-secondary" onClick={() => setStage({ kind: "asking" })}>
          <Eye aria-hidden />
          원문 보기
        </Button>
      )}

      {stage.kind === "asking" && (
        <ViewReasonForm
          payoutId={payoutId}
          onCancel={() => showPayee({ kind: "masked" })}
          onRevealed={(info) => showPayee({ kind: "revealed", info })}
        />
      )}

      {stage.kind === "revealed" && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Button type="button" variant="outline" size="sm" className="hover:bg-secondary" onClick={() => showPayee({ kind: "masked" })}>
            <EyeOff aria-hidden />
            가리기
          </Button>
          <p className="text-xs break-keep text-muted-foreground">
            이 화면을 떠나면 다시 가려져요. 원문을 다른 곳에 옮겨 적지 마세요.
          </p>
        </div>
      )}
    </div>
  );
}

function PayeeField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-all text-foreground tabular-nums">{value}</dd>
    </div>
  );
}

/** 주민등록번호 13자리를 읽기 쉬운 `000000-0000000` 으로. 다른 길이면 받은 그대로 둔다. */
function formatRrn(rrn: string) {
  return /^\d{13}$/.test(rrn) ? `${rrn.slice(0, 6)}-${rrn.slice(6)}` : rrn;
}

type ViewReasonFormProps = {
  payoutId: string;
  onCancel: () => void;
  onRevealed: (info: AdminPayeeInfoViewResponse) => void;
};

/** 열람 사유. 모달이 아니라 그 자리에 펼친다 — 원문이 나타날 자리 바로 위에서 사유를 적고, 열면 같은 자리에 원문이 온다. */
function ViewReasonForm({ payoutId, onCancel, onRevealed }: ViewReasonFormProps) {
  const id = useId();
  const viewMutation = useViewPayeeInfoMutation(payoutId);
  const [failureMessage, setFailureMessage] = useState<string | null>(null);
  const {
    control,
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ViewPayeeReasonFormValues>({
    resolver: zodResolver(viewPayeeReasonSchema),
    defaultValues: { reasonCategory: undefined, reasonText: "" },
  });
  // "원문 보기"를 눌러 열린 폼이라 누른 버튼이 사라졌다 — 첫 칸(사유 분류)으로 포커스를 옮긴다. 이 폼은 그 버튼으로만 열린다.
  const focusOnMount = useRef(true);
  const focusCategoryOnOpen = (element: HTMLElement | null) => {
    if (!element || !focusOnMount.current) return;
    focusOnMount.current = false;
    element.focus();
  };

  const onSubmit = async (values: ViewPayeeReasonFormValues) => {
    if (!values.reasonCategory) return;
    setFailureMessage(null);
    try {
      const info = await viewMutation.mutateAsync({
        reasonCategory: values.reasonCategory,
        reasonText: values.reasonText.trim(),
      });
      // 원문을 뮤테이션 결과로 들고 있지 않게 바로 비운다 — 이제 원문은 부모의 지역 상태에만 있다.
      viewMutation.reset();
      onRevealed(info);
    } catch (error) {
      setFailureMessage(toCreatorPayoutFailure(error).message);
    }
  };

  const categoryErrorId = `${id}-category-error`;
  const textErrorId = `${id}-text-error`;

  return (
    <form
      noValidate
      aria-label="지급 정보 열람 사유"
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
      className="flex flex-col gap-3 rounded-lg border border-border p-3"
    >
      <p className="text-sm break-keep text-muted-foreground">
        원문을 보려면 사유가 필요해요. 열람할 때마다 기록이 남아요.
      </p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-category`}>사유 분류</Label>
        <Controller
          name="reasonCategory"
          control={control}
          render={({ field }) => (
            <Select
              value={field.value ?? ""}
              onValueChange={(value) => field.onChange(isPayeeInfoViewReasonCategory(value) ? value : undefined)}
            >
              <SelectTrigger
                ref={focusCategoryOnOpen}
                id={`${id}-category`}
                className="w-full"
                aria-invalid={!!errors.reasonCategory}
                aria-describedby={errors.reasonCategory ? categoryErrorId : undefined}
              >
                <SelectValue placeholder="사유를 고르세요" />
              </SelectTrigger>
              <SelectContent>
                {PAYEE_INFO_VIEW_REASON_CATEGORY_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        {errors.reasonCategory && (
          <p id={categoryErrorId} role="alert" className="text-xs text-destructive-text">
            {errors.reasonCategory.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-text`}>사유 상세 (필수)</Label>
        <Textarea
          id={`${id}-text`}
          rows={3}
          placeholder="이체 전 계좌 확인, 지급명세서 작성 등"
          aria-invalid={!!errors.reasonText}
          aria-describedby={errors.reasonText ? textErrorId : undefined}
          {...register("reasonText")}
        />
        {errors.reasonText && (
          <p id={textErrorId} role="alert" className="text-xs text-destructive-text">
            {errors.reasonText.message}
          </p>
        )}
      </div>

      {failureMessage && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {failureMessage}
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="outline" className="hover:bg-secondary" disabled={isSubmitting} onClick={onCancel}>
          취소
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "여는 중..." : "원문 열기"}
        </Button>
      </div>
    </form>
  );
}
