import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  useRejectCreatorPayoutApplicationMutation,
  useRevokeCreatorPayoutApplicationMutation,
  type AdminCreatorPayoutApplicationItem,
} from "@/entities/creator-payout-application";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

import { toDecisionFailure } from "../model/decisionError";

type DecisionReasonKind = "reject" | "revoke";

type DecisionReasonModalProps = {
  kind: DecisionReasonKind;
  application: AdminCreatorPayoutApplicationItem;
  applicantName: string;
};

const reasonSchema = z.object({
  // 서버도 공백 사유를 422 로 거부하고 1,000자에서 자른다 — 같은 규칙을 먼저 건다.
  reason: z.string().trim().min(1, "사유를 입력해주세요.").max(1000, "사유는 1,000자까지 쓸 수 있어요."),
});

type ReasonFormValues = z.infer<typeof reasonSchema>;

/** 두 처리의 문구. 사유가 누구에게 보이는지가 갈리는 핵심이라 안내 줄에 늘 적는다. */
const COPY: Record<
  DecisionReasonKind,
  { title: string; effect: string; reasonHint: string; placeholder: string; confirm: string; done: string }
> = {
  reject: {
    title: "정산 신청 거절",
    effect: "의 정산 신청을 거절합니다.",
    reasonHint: "신청자 화면에 이 사유가 그대로 보여요. 무엇을 고치면 되는지 적어주세요.",
    placeholder: "신청자에게 보일 거절 사유",
    confirm: "거절 확정",
    done: "신청을 거절했어요.",
  },
  revoke: {
    title: "정산 승인 취소",
    effect:
      "의 정산 승인을 취소합니다. 지금부터 적립이 멈추고, 이미 확정된 적립은 그대로 남아요.",
    reasonHint: "감사 기록에만 남고 신청자에게는 보이지 않아요.",
    placeholder: "취소 사유",
    confirm: "승인 취소 확정",
    done: "승인을 취소했어요.",
  },
};

/** 거절·승인 취소 확인. 둘 다 사유가 필수인 한 번짜리 처리라 한 모달이 문구만 바꿔 맡는다. */
export const DecisionReasonModal = createCallable<DecisionReasonModalProps, void>(
  ({ call, kind, application, applicantName }) => {
    const rejectMutation = useRejectCreatorPayoutApplicationMutation(application.id);
    const revokeMutation = useRevokeCreatorPayoutApplicationMutation(application.id);
    const [failureMessage, setFailureMessage] = useState<string | null>(null);
    const copy = COPY[kind];
    const {
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<ReasonFormValues>({ resolver: zodResolver(reasonSchema), defaultValues: { reason: "" } });

    const onSubmit = async (values: ReasonFormValues) => {
      setFailureMessage(null);
      const mutation = kind === "reject" ? rejectMutation : revokeMutation;
      try {
        await mutation.mutateAsync({ reasonText: values.reason });
        toast.success(copy.done);
        call.end();
      } catch (error) {
        const failure = toDecisionFailure(error);
        if (failure.kind === "stale") {
          toast.error(failure.message);
          call.end();
          return;
        }
        setFailureMessage(failure.message);
      }
    };

    const reasonDescribedBy = ["decision-reason-hint", errors.reason && "decision-reason-error"]
      .filter(Boolean)
      .join(" ");

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription className="break-keep">
              <span className="font-medium text-foreground">{applicantName}</span>님{copy.effect}
              {/* 탈퇴 회원은 다시 신청할 길이 없다. */}
              {kind === "reject" && !application.eligibility.withdrawn && " 신청자는 다시 신청할 수 있어요."}
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex min-h-0 flex-1 flex-col gap-4"
          >
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="decision-reason">사유 (필수)</Label>
                <p id="decision-reason-hint" className="text-xs break-keep text-muted-foreground">
                  {copy.reasonHint}
                </p>
                <Textarea
                  id="decision-reason"
                  rows={4}
                  placeholder={copy.placeholder}
                  aria-invalid={!!errors.reason}
                  aria-describedby={reasonDescribedBy}
                  {...register("reason")}
                />
                {errors.reason && (
                  <p id="decision-reason-error" role="alert" className="text-xs text-destructive-text">
                    {errors.reason.message}
                  </p>
                )}
              </div>

              {failureMessage && (
                <p role="alert" className="text-sm break-keep text-destructive-text">
                  {failureMessage}
                </p>
              )}
            </DialogBody>

            <DialogFooter>
              <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : copy.confirm}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
