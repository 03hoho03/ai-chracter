import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  toCreatorPayoutFailure,
  useHoldCreatorPayoutMutation,
  useReturnCreatorPayoutMutation,
} from "@/entities/creator-payout";

import { reasonSchema, type ReasonFormValues } from "../model/schema";

type PayoutReasonKind = "return" | "hold";

/** 두 처리의 문구. 사유가 누구에게 보이는지가 갈리는 핵심이라 안내 줄에 늘 적는다. */
const COPY: Record<PayoutReasonKind, { effect: string; hint: string; placeholder: string; confirm: string; done: string }> =
  {
    return: {
      effect: "반려하면 금액이 신청자의 적립 잔액으로 돌아가고, 신청자가 정보를 고쳐 다시 신청할 수 있어요.",
      hint: "신청자 정산 화면에 이 사유가 그대로 보여요. 무엇을 고치면 되는지 적어주세요.",
      placeholder: "신청자에게 보일 반려 사유",
      confirm: "반려 확정",
      done: "지급을 반려했어요.",
    },
    hold: {
      effect: "보류해도 금액은 이 지급 건에 남아요. 수취 정보를 바꾼 뒤 이체를 기록하면 끝나요.",
      hint: "운영자만 보는 사유예요. 무엇을 기다리는지 적어주세요.",
      placeholder: "예: 문의로 새 계좌를 요청함",
      confirm: "보류",
      done: "지급을 보류했어요.",
    },
  };

type PayoutReasonFormProps = {
  kind: PayoutReasonKind;
  payoutId: string;
  onSuccess: () => void;
};

/** 반려·보류. 둘 다 사유가 필수인 한 번짜리 처리라 한 폼이 문구만 바꿔 맡는다. */
export function PayoutReasonForm({ kind, payoutId, onSuccess }: PayoutReasonFormProps) {
  const id = useId();
  const returnMutation = useReturnCreatorPayoutMutation(payoutId);
  const holdMutation = useHoldCreatorPayoutMutation(payoutId);
  const [failureMessage, setFailureMessage] = useState<string | null>(null);
  const copy = COPY[kind];
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ReasonFormValues>({ resolver: zodResolver(reasonSchema), defaultValues: { reasonText: "" } });

  const onSubmit = async (values: ReasonFormValues) => {
    setFailureMessage(null);
    const mutation = kind === "return" ? returnMutation : holdMutation;
    try {
      await mutation.mutateAsync({ reasonText: values.reasonText.trim() });
      toast.success(copy.done);
      onSuccess();
    } catch (error) {
      const failure = toCreatorPayoutFailure(error);
      if (failure.kind === "stale") {
        toast.error(failure.message);
        return;
      }
      setFailureMessage(failure.message);
    }
  };

  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-sm break-keep text-foreground">{copy.effect}</p>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-reason`}>사유 (필수)</Label>
        <p id={hintId} className="text-xs break-keep text-muted-foreground">
          {copy.hint}
        </p>
        <Textarea
          id={`${id}-reason`}
          rows={4}
          placeholder={copy.placeholder}
          aria-invalid={!!errors.reasonText}
          aria-describedby={[hintId, errors.reasonText && errorId].filter(Boolean).join(" ")}
          {...register("reasonText")}
        />
        {errors.reasonText && (
          <p id={errorId} role="alert" className="text-xs text-destructive-text">
            {errors.reasonText.message}
          </p>
        )}
      </div>

      {failureMessage && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {failureMessage}
        </p>
      )}

      <Button type="submit" className="self-end" disabled={isSubmitting}>
        {isSubmitting ? "처리 중..." : copy.confirm}
      </Button>
    </form>
  );
}
