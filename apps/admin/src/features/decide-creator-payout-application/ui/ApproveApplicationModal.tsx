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
  useApproveCreatorPayoutApplicationMutation,
  type AdminCreatorPayoutApplicationItem,
} from "@/entities/creator-payout-application";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";
import { formatCount } from "@/shared/lib/format/formatCount";

import { toDecisionFailure } from "../model/decisionError";

type ApproveApplicationModalProps = {
  application: AdminCreatorPayoutApplicationItem;
  applicantName: string;
};

const approveSchema = z.object({
  // 서버가 1,000자에서 거부한다 — 같은 규칙을 먼저 건다. 메모는 비워 둘 수 있다.
  memo: z.string().max(1000, "메모는 1,000자까지 쓸 수 있어요."),
});

type ApproveFormValues = z.infer<typeof approveSchema>;

/** 승인 결과. 소급 금액이 `null` 이면 이 회원은 이전 승인 때 이미 소급했다(승인 취소 뒤 다시 승인). */
type ApproveResult = { retroAmountKrw: number | null };

/**
 * 정산 신청 승인 확인. 처음 승인이면 서버가 같은 요청에서 지난 소급 기간의 사용분을 확정해 되돌릴 수 없으므로 버튼
 * 한 번으로 실행하지 않는다. 성공하면 닫지 않고 같은 모달에서 소급 확정 금액을 보여 준다 — 승인한 행은 대기 목록에서
 * 곧 빠져 그 금액을 다시 볼 자리가 없다.
 */
export const ApproveApplicationModal = createCallable<ApproveApplicationModalProps, void>(
  ({ call, application, applicantName }) => {
    const approveMutation = useApproveCreatorPayoutApplicationMutation(application.id);
    const [result, setResult] = useState<ApproveResult | null>(null);
    const [failureMessage, setFailureMessage] = useState<string | null>(null);
    const {
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<ApproveFormValues>({ resolver: zodResolver(approveSchema), defaultValues: { memo: "" } });

    const onSubmit = async (values: ApproveFormValues) => {
      setFailureMessage(null);
      try {
        const response = await approveMutation.mutateAsync({ reasonText: values.memo.trim() });
        setResult({ retroAmountKrw: response.retroAmountKrw });
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

    return (
      // 승인 요청 중에는 닫지 않는다 — 닫은 뒤 성공하면 소급 확정 금액을 다시 볼 자리가 없다.
      <Dialog open={!call.ended} onOpenChange={(open) => !open && !isSubmitting && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          {result ? (
            <>
              <DialogHeader>
                <DialogTitle>승인했어요</DialogTitle>
                <DialogDescription className="break-keep">
                  {applicantName}님은 지금부터 정산 적립을 받아요.
                </DialogDescription>
              </DialogHeader>
              <DialogBody>
                <ApproveResultBody result={result} />
              </DialogBody>
              <DialogFooter>
                <Button type="button" autoFocus data-initial-focus onClick={() => call.end()}>
                  닫기
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>정산 신청 승인</DialogTitle>
                <DialogDescription className="break-keep">
                  <span className="font-medium text-foreground">{applicantName}</span>님의 정산 신청을 승인합니다.
                  처음 승인이면 지난 소급 기간의 사용분을 바로 확정하고, 이 확정은 되돌릴 수 없어요. 승인
                  취소 뒤 다시 승인하면 소급 없이 지금부터 적립해요.
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
                    <Label htmlFor="approve-memo">메모 (선택)</Label>
                    <Textarea
                      id="approve-memo"
                      rows={3}
                      placeholder="감사 기록에만 남고 신청자에게는 보이지 않아요."
                      aria-invalid={!!errors.memo}
                      aria-describedby={errors.memo ? "approve-memo-error" : undefined}
                      {...register("memo")}
                    />
                    {errors.memo && (
                      <p id="approve-memo-error" role="alert" className="text-xs text-destructive-text">
                        {errors.memo.message}
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
                  <Button
                    type="button"
                    variant="outline"
                    autoFocus
                    data-initial-focus
                    disabled={isSubmitting}
                    onClick={() => call.end()}
                  >
                    취소
                  </Button>
                  <Button type="submit" disabled={isSubmitting}>
                    {isSubmitting ? "승인 중..." : "승인 확정"}
                  </Button>
                </DialogFooter>
              </form>
            </>
          )}
        </DialogContent>
      </Dialog>
    );
  },
);

function ApproveResultBody({ result }: { result: ApproveResult }) {
  if (result.retroAmountKrw === null) {
    return (
      <p role="status" className="text-sm break-keep text-foreground">
        이 회원은 앞선 승인 때 이미 소급 확정을 받아, 이번 승인은 소급 없이 지금부터 적립해요.
      </p>
    );
  }
  return (
    <div role="status" className="flex flex-col gap-1 rounded-lg border border-border p-4">
      <span className="text-sm text-muted-foreground">소급 확정 금액</span>
      <span className="text-2xl font-bold tabular-nums text-foreground">{formatCount(result.retroAmountKrw)}원</span>
      {result.retroAmountKrw === 0 && (
        <span className="text-xs break-keep text-muted-foreground">
          소급 기간에 정산 대상 사용이 없었어요. 소급은 끝난 것으로 기록돼요.
        </span>
      )}
    </div>
  );
}
