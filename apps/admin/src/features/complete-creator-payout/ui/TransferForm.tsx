import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  BANK_LABELS,
  formatKrw,
  toCreatorPayoutFailure,
  useTransferCreatorPayoutMutation,
  type AdminCreatorPayoutDetail,
} from "@/entities/creator-payout";
import { toKstDateString } from "@/shared/lib/format/kstDate";

import { createTransferSchema, type TransferFormValues } from "../model/schema";

type TransferFormProps = {
  payout: AdminCreatorPayoutDetail;
  onSuccess: () => void;
};

/** 이체 완료 기록. 금액은 신청 때 원천징수를 뗀 실지급액이고 바꿀 수 없다 — 운영자는 이체일과 메모만 넣는다. */
export function TransferForm({ payout, onSuccess }: TransferFormProps) {
  const id = useId();
  const transferMutation = useTransferCreatorPayoutMutation(payout.id);
  const [failureMessage, setFailureMessage] = useState<string | null>(null);
  const [today] = useState(() => toKstDateString());
  const requestedOn = toKstDateString(payout.requestedAt);
  const schema = useMemo(() => createTransferSchema({ requestedOn, today }), [requestedOn, today]);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<TransferFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { transferredOn: today, adminMemo: "" },
  });

  const onSubmit = async (values: TransferFormValues) => {
    setFailureMessage(null);
    try {
      // 화면이 보여 주는 수취 정보 판을 함께 보낸다 — 그 사이 다른 운영자가 수취 정보를 바꿨으면 서버가 409 로 거부해, 보지
      // 않은 계좌로 이체했다고 기록되지 않는다.
      await transferMutation.mutateAsync({
        transferredOn: values.transferredOn,
        adminMemo: values.adminMemo.trim(),
        payeeProfileId: payout.payeeProfileId,
      });
      toast.success("이체 완료를 기록했어요.");
      onSuccess();
    } catch (error) {
      const failure = toCreatorPayoutFailure(error);
      if (failure.kind === "stale") {
        toast.error(failure.message);
        return;
      }
      if (failure.kind === "input") {
        setError("transferredOn", { message: failure.message });
        return;
      }
      setFailureMessage(failure.message);
    }
  };

  const dateErrorId = `${id}-date-error`;
  const memoErrorId = `${id}-memo-error`;

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-sm break-keep text-foreground">
        실지급액 <span className="font-semibold tabular-nums">{formatKrw(payout.withholding.netAmountKrw)}</span>을{" "}
        {BANK_LABELS[payout.bankCode]} ****{payout.accountLast4}로 이체했다고 기록해요.
      </p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-date`}>이체일 (한국 시각)</Label>
        <Input
          id={`${id}-date`}
          type="date"
          min={requestedOn}
          max={today}
          aria-invalid={!!errors.transferredOn}
          aria-describedby={errors.transferredOn ? dateErrorId : undefined}
          {...register("transferredOn")}
        />
        {errors.transferredOn && (
          <p id={dateErrorId} role="alert" className="text-xs break-keep text-destructive-text">
            {errors.transferredOn.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-memo`}>메모 (선택)</Label>
        <Textarea
          id={`${id}-memo`}
          rows={3}
          placeholder="이체 거래 번호 등 운영자만 볼 메모"
          aria-invalid={!!errors.adminMemo}
          aria-describedby={errors.adminMemo ? memoErrorId : undefined}
          {...register("adminMemo")}
        />
        {errors.adminMemo && (
          <p id={memoErrorId} role="alert" className="text-xs text-destructive-text">
            {errors.adminMemo.message}
          </p>
        )}
      </div>

      {failureMessage && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {failureMessage}
        </p>
      )}

      <Button type="submit" className="self-end" disabled={isSubmitting}>
        {isSubmitting ? "기록 중..." : "이체 완료 기록"}
      </Button>
    </form>
  );
}
