import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  useRefundPaymentMutation,
  useRefundQuoteQuery,
  useUserPaymentsQuery,
  type AdminRefundQuoteResponse,
  type AdminRefundRequest,
  type AdminUserPaymentItem,
} from "@/entities/admin-user";
import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { toKstDateString } from "@/shared/lib/format/kstDate";

type RefundPaymentModalProps = {
  /** 모드를 연 순간의 행이 아니라 살아 있는 구매 내역 쿼리로 정하려고 받는다(같은 키라 캐시를 그대로 쓴다). */
  userId: string;
  payment: AdminUserPaymentItem;
};

/** 확정 뒤 다이얼로그에 남기는 한 줄. `unknown`·`waiting`은 문장이 지금 모드에 따라 갈려 렌더 때 고른다. */
type SubmitFeedback = { kind: "error"; message: string } | { kind: "unknown" } | { kind: "waiting" };

const refundSchema = z.object({
  receivedOn: z.string(),
  companyFault: z.boolean(),
  // 서버도 공백 사유를 422로 거부하고 1,000자에서 자른다 — 같은 규칙을 먼저 건다.
  reason: z.string().trim().min(1, "사유를 입력해주세요.").max(1000, "사유는 1,000자까지 쓸 수 있어요."),
});

type RefundFormValues = z.infer<typeof refundSchema>;

/** 구매 한 건의 환불 다이얼로그. 두 모드다.
 *
 * - **견적 모드**: 신청 접수일(KST, 기본 오늘)과 회사 귀책을 고르면 그때마다 견적을 다시 읽고, 그 견적 금액을 실어
 *   확정한다. 실행 시점 견적이 다르면 서버가 409로 막는다(그사이 회원이 클로버를 썼다).
 * - **확인·재시도 모드**: 그 결제에 결과를 모르는 시도가 있을 때(살아 있는 구매 내역의 `refundPending`, 또는 방금 받은
 *   202). 같은 실행 경로를 다시 부르면 서버가 포트원을 재조회해 마무리하고, 포트원에 닿지 않았던 요청이면 같은 금액으로
 *   다시 보낸다. 이때 요청의 견적 금액·접수일·귀책은 서버가 쓰지 않는다.
 *
 * 모드를 연 순간의 행으로 정하지 않는 이유: 그 뒤 다른 어드민이 시도를 만들었거나 이 창의 요청이 응답 없이 시도를 남겼으면,
 * 견적은 회수된 클로버 때문에 0원으로 오고 확정이 막혀 마무리할 길이 없다. 실행은 끝날 때마다 구매 내역을 다시 읽으므로
 * (뮤테이션의 `onSettled`) 응답을 못 받은 경우도 그 목록이 모드를 정한다 — 요청이 서버에 닿지도 않았는데 확인·재시도로
 * 넘기면 0원 재시도가 409로 막혀 "이미 마무리됐다"고 잘못 말하게 된다.
 *
 * 확정 버튼만 `primary`다 — 이 다이얼로그에서 지금 누를 것은 그 하나다. */
export const RefundPaymentModal = createCallable<RefundPaymentModalProps, void>(({ call, userId, payment }) => {
  // 다이얼로그를 연 순간의 날짜로 고정한다 — 자정을 넘겨도 입력 범위가 열린 화면 안에서 바뀌지 않는다(서버가 다시 검사한다).
  const [today] = useState(() => toKstDateString());
  const paidOn = payment.paidAt ? toKstDateString(payment.paidAt) : today;
  const paymentsQuery = useUserPaymentsQuery(userId);
  const livePayment = paymentsQuery.data?.items.find((item) => item.paymentId === payment.paymentId);
  // 방금 받은 202는 목록이 다시 읽히기 전에도 바로 확인·재시도로 넘긴다(목록도 곧 같은 답을 준다).
  const [hasAccepted, setHasAccepted] = useState(false);
  const isAttemptPending = hasAccepted || (livePayment ?? payment).refundPending;
  const [feedback, setFeedback] = useState<SubmitFeedback | null>(null);
  const refundMutation = useRefundPaymentMutation(payment.paymentId);

  const {
    control,
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RefundFormValues>({
    resolver: zodResolver(refundSchema),
    defaultValues: { receivedOn: today, companyFault: false, reason: "" },
  });
  const receivedOn = useWatch({ control, name: "receivedOn" });
  const companyFault = useWatch({ control, name: "companyFault" });
  // 같은 `YYYY-MM-DD` 형식이라 문자열 비교가 날짜 비교다. 빈 칸("")은 결제일보다 앞이라 범위 밖으로 떨어진다.
  const isReceivedOnInRange = receivedOn >= paidOn && receivedOn <= today;
  const isRefundable = isRefundableStatus((livePayment ?? payment).status);

  const quoteQuery = useRefundQuoteQuery({
    paymentId: payment.paymentId,
    receivedOn,
    companyFault,
    // 닫히는 중이거나 살아 있는 목록이 더는 환불할 수 없는 상태(전액 취소 등)라고 하면 묻지 않는다 — 서버가 422로 답할
    // 뿐이고 닫히는 화면에 그 오류가 비친다.
    enabled: !call.ended && !isAttemptPending && isReceivedOnInRange && isRefundable,
  });
  // 접수일·귀책을 바꾸는 동안 옛 견적으로 확정하지 않게, 지금 입력의 견적이 도착했을 때만 연다.
  const confirmableQuote =
    !isAttemptPending && isReceivedOnInRange && isRefundable && quoteQuery.isSuccess && !quoteQuery.isFetching
      ? quoteQuery.data
      : null;
  const confirmLabel = isAttemptPending ? "확인·재시도" : "환불 확정";

  const onSubmit = async (values: RefundFormValues) => {
    // 견적 모드에서 견적이 아직 없으면 확정 버튼이 막혀 있어 여기 닿지 않는다(막힌 기본 버튼은 Enter 제출도 막는다).
    if (!isAttemptPending && !confirmableQuote) return;
    setFeedback(null);
    try {
      const result = await refundMutation.mutateAsync(
        buildRefundRequest(values, isAttemptPending ? null : confirmableQuote, today),
      );
      if (result.status === "requested") {
        // 첫 202든 재시도의 202든 같은 줄을 남긴다 — 재시도의 202는 화면이 그대로라 이 줄이 없으면 눌린 흔적이 없다.
        setHasAccepted(true);
        setFeedback({ kind: "waiting" });
        return;
      }
      toast.success(
        `${formatCount(result.amountKrw)}원을 환불했어요. 클로버 유료 ${formatCount(result.clawbackPaid)}개·보너스 ${formatCount(result.clawbackBonus)}개를 회수했어요.`,
      );
      call.end();
    } catch (error) {
      if (!isApiError(error)) {
        setFeedback({ kind: "unknown" });
        return;
      }
      const code = detailCode(error.detail);
      if (code === "REFUND_REJECTED") {
        toast.error("포트원이 환불을 거절했어요. 회수했던 클로버는 회원에게 되돌렸어요.");
        call.end();
        return;
      }
      if (code === "PAYMENT_NOT_FOUND") {
        toast.error("결제를 찾지 못했어요.");
        call.end();
        return;
      }
      if (isAttemptPending && isAttemptAlreadySettled(code)) {
        // 재시도 요청은 견적 금액 0원을 싣는다 — 그사이 시도가 끝나 서버가 새 환불로 받으면 0원·상태·견적 불일치로
        // 반드시 거부되므로 새 환불이 시작되지 않는다. 그 거부가 곧 "이미 끝났다"는 뜻이다.
        toast.info("진행 중이던 환불이 이미 마무리됐어요. 구매 내역에서 결과를 확인해주세요.");
        call.end();
        return;
      }
      if (code === "PAYMENT_NOT_REFUNDABLE") {
        toast.error("환불할 수 없는 상태의 결제예요. 이미 취소됐을 수 있어요.");
        call.end();
        return;
      }
      if (code === "REFUND_QUOTE_CHANGED") {
        // 뮤테이션이 견적 쿼리까지 끊어 새 견적이 곧 다시 그려진다.
        setFeedback({
          kind: "error",
          message: "그사이 회원이 클로버를 써 견적이 바뀌었어요. 새 견적을 확인하고 다시 확정해주세요.",
        });
        return;
      }
      if (code === "REFUND_AMOUNT_ZERO") {
        setFeedback({ kind: "error", message: "환불할 금액이 0원이라 환불하지 않았어요." });
        return;
      }
      if (code === "REFUND_RECEIVED_ON_INVALID") {
        setError("receivedOn", { message: receivedOnRangeMessage(paidOn, today) });
        return;
      }
      // 5xx·네트워크 실패(status 0)는 서버가 시도를 만들었는지 모른다 — 모드를 넘기지 않고, 뮤테이션이 이미 다시 읽은
      // 구매 내역이 정하게 둔다. 그 밖은 화면이 미리 막는 검증 실패라 일반 문장으로 받는다.
      setFeedback(
        error.status >= 500 || error.status === 0
          ? { kind: "unknown" }
          : { kind: "error", message: "환불을 처리하지 못했어요. 잠시 후 다시 시도해주세요." },
      );
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-lg" onOpenAutoFocus={focusInitialElement}>
        <DialogHeader>
          <DialogTitle>{isAttemptPending ? "환불 확인·재시도" : "결제 환불"}</DialogTitle>
          <DialogDescription className="break-keep">
            {payment.orderName} · {formatCount(payment.amountKrw)}원 · 결제 {formatDateTime(payment.paidAt)}
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
            {isAttemptPending ? (
              <p className="rounded-lg border border-border p-3 text-sm break-keep text-foreground">
                포트원 결과를 기다리는 환불 시도가 있어요. 클로버는 이미 회수했고, 포트원이 처리하면 자동으로 맞춰져요.
                확인·재시도를 누르면 포트원을 다시 조회해 마무리하고, 요청이 포트원에 닿지 않았으면 같은 금액으로 다시
                보내요.
              </p>
            ) : (
              <>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="refund-received-on">신청 접수일</Label>
                  <Input
                    id="refund-received-on"
                    type="date"
                    min={paidOn}
                    max={today}
                    className="w-fit tabular-nums"
                    aria-invalid={!!errors.receivedOn || !isReceivedOnInRange}
                    aria-describedby="refund-received-on-hint"
                    {...register("receivedOn")}
                  />
                  <p
                    id="refund-received-on-hint"
                    className={
                      errors.receivedOn || !isReceivedOnInRange
                        ? "text-xs text-destructive-text"
                        : "text-xs text-muted-foreground"
                    }
                  >
                    {errors.receivedOn?.message ??
                      (isReceivedOnInRange
                        ? "회원이 환불을 신청한 날(KST)이에요. 결제 다음 날부터 7일째 안에 접수했으면 100%, 그 뒤면 90%예요."
                        : receivedOnRangeMessage(paidOn, today))}
                  </p>
                </div>

                <Controller
                  name="companyFault"
                  control={control}
                  render={({ field }) => (
                    <div className="flex items-start gap-2">
                      <Checkbox
                        id="refund-company-fault"
                        className="mt-0.5"
                        checked={field.value}
                        onCheckedChange={(checked) => field.onChange(checked === true)}
                        aria-describedby="refund-company-fault-hint"
                      />
                      <div className="flex flex-col gap-0.5">
                        <Label htmlFor="refund-company-fault">회사 귀책(100%)</Label>
                        <p id="refund-company-fault-hint" className="text-xs text-muted-foreground break-keep">
                          서비스 장애·오류처럼 회사 책임이면 접수일과 무관하게 100%를 환불해요.
                        </p>
                      </div>
                    </div>
                  )}
                />

                <RefundQuoteBody
                  quoteQuery={quoteQuery}
                  isReceivedOnInRange={isReceivedOnInRange}
                  isRefundable={isRefundable}
                  companyFault={companyFault}
                />
              </>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="refund-reason">사유 (필수)</Label>
              <Textarea
                id="refund-reason"
                rows={3}
                placeholder="내부 감사용 메모예요. 회원·포트원에는 보내지 않아요."
                aria-invalid={!!errors.reason}
                aria-describedby={errors.reason ? "refund-reason-error" : undefined}
                {...register("reason")}
              />
              {errors.reason && (
                <p id="refund-reason-error" role="alert" className="text-xs text-destructive-text">
                  {errors.reason.message}
                </p>
              )}
            </div>

            {feedback?.kind === "error" && (
              <p role="alert" className="text-sm break-keep text-destructive-text">
                {feedback.message}
              </p>
            )}
            {feedback?.kind === "unknown" && (
              <p role="alert" className="text-sm break-keep text-destructive-text">
                {unknownResultMessage(isAttemptPending, paymentsQuery.isError)}
              </p>
            )}
            {feedback?.kind === "waiting" && (
              <p role="status" className="text-sm break-keep text-foreground">
                포트원 결과를 아직 기다리는 중이에요. 잠시 뒤 다시 확인·재시도를 눌러주세요 — 마지막으로 보낸 지 30초가 안
                됐으면 다시 보내지 않고 결과만 확인해요.
              </p>
            )}
          </DialogBody>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
              취소
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || (!isAttemptPending && (!confirmableQuote || confirmableQuote.refundKrw === 0))}
            >
              {isSubmitting ? "처리 중..." : confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});

type RefundQuoteBodyProps = {
  quoteQuery: ReturnType<typeof useRefundQuoteQuery>;
  isReceivedOnInRange: boolean;
  /** 살아 있는 구매 내역의 상태가 환불할 수 있는가. 아니면 견적을 묻지 않으므로(쿼리가 꺼져 대기 상태로 남는다) 문장으로 받는다. */
  isRefundable: boolean;
  companyFault: boolean;
};

/** 견적 영역. 접수일·귀책이 바뀔 때마다 다시 읽으므로 스크린리더에도 바뀐 결과가 읽히게 `aria-live`다. */
function RefundQuoteBody(props: RefundQuoteBodyProps) {
  return (
    <section aria-label="환불 견적" aria-live="polite" className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold text-foreground">견적</h3>
      <RefundQuoteContent {...props} />
    </section>
  );
}

function RefundQuoteContent({ quoteQuery, isReceivedOnInRange, isRefundable, companyFault }: RefundQuoteBodyProps) {
  if (!isRefundable) {
    return (
      <p className="text-sm break-keep text-foreground">
        이 결제는 이제 환불할 수 없는 상태예요. 이미 취소됐을 수 있어요 — 구매 내역에서 상태를 확인해주세요.
      </p>
    );
  }

  if (!isReceivedOnInRange) {
    return <p className="text-sm text-muted-foreground">접수일을 고르면 견적을 보여 드려요.</p>;
  }

  if (quoteQuery.isError) {
    const message = quoteErrorMessage(quoteQuery.error.detail);
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-sm break-keep text-destructive-text">
          {message ?? "견적을 불러오지 못했어요. 잠시 후 다시 시도해주세요."}
        </p>
        {!message && (
          <Button type="button" variant="outline" size="sm" onClick={() => void quoteQuery.refetch()}>
            다시 시도
          </Button>
        )}
      </div>
    );
  }

  // 다이얼로그는 `popover` 표면이라 `muted` 스켈레톤이 사라진다 — 한 칸 위 `secondary`로 칠한다.
  if (!quoteQuery.isSuccess || quoteQuery.isFetching) {
    return <div className="h-48 animate-pulse rounded-lg bg-secondary" />;
  }

  const quote = quoteQuery.data;
  return (
    <>
      <dl className="divide-y divide-border rounded-lg border border-border text-sm">
        {refundQuoteRows(quote, companyFault).map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-4 px-3 py-2">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd className="text-right tabular-nums text-foreground">{row.value}</dd>
          </div>
        ))}
        <div className="flex items-baseline justify-between gap-4 px-3 py-2">
          <dt className="font-semibold text-foreground">환불 금액</dt>
          <dd className="text-lg font-semibold tabular-nums text-foreground">{formatCount(quote.refundKrw)}원</dd>
        </div>
      </dl>
      <p className="text-xs break-keep text-muted-foreground">
        환불 금액 = 환불 대상 × 구매 단가 × 비율(원 미만 버림), 취소 가능 잔액이 상한이에요. 확정하면 이 구매의 남은 유료·보너스
        클로버를 모두 회수해요.
      </p>
      {quote.refundKrw === 0 && (
        <p className="text-sm break-keep text-foreground">
          환불할 금액이 0원이에요 — 환불 대상 클로버(남은 유료 − 쓴 보너스)가 없어요.
        </p>
      )}
    </>
  );
}

/** 견적의 산식 줄 — 서버가 쓴 `max(0, 남은 유료 − 쓴 보너스)`를 그대로 보여 준다. 환불 금액 줄은 강조해 따로 그린다. */
function refundQuoteRows(quote: AdminRefundQuoteResponse, companyFault: boolean) {
  const refundableUnits = Math.max(0, quote.paidRemaining - quote.bonusUsed);
  return [
    { label: "남은 유료 클로버", value: `${formatCount(quote.paidRemaining)}개` },
    { label: "이 구매에서 쓴 보너스", value: `${formatCount(quote.bonusUsed)}개` },
    { label: "환불 대상", value: `${formatCount(refundableUnits)}개` },
    { label: "비율", value: `${quote.ratioPercent}% · ${ratioReason(quote.ratioPercent, companyFault)}` },
    { label: "취소 가능 잔액", value: `${formatCount(quote.cancellableKrw)}원` },
    {
      label: "회수할 클로버",
      value: `유료 ${formatCount(quote.clawbackPaid)}개 · 보너스 ${formatCount(quote.clawbackBonus)}개`,
    },
  ];
}

/** 비율은 서버가 정한다 — 화면은 귀책 입력과 받은 비율로 이유만 붙인다. */
function ratioReason(ratioPercent: number, companyFault: boolean) {
  if (companyFault) return "회사 귀책";
  return ratioPercent === 100 ? "7일 안 접수" : "7일 지나 접수";
}

/** 견적 422·404 는 입력에 대한 답이라 다시 시도할 것이 없다 — 문장만 보여 준다. 그 밖은 `null`(다시 시도를 연다). */
function quoteErrorMessage(detail: unknown) {
  const code = detailCode(detail);
  if (code === "REFUND_RECEIVED_ON_INVALID") return "접수일은 결제일부터 오늘(KST) 사이여야 해요.";
  if (code === "PAYMENT_NOT_REFUNDABLE") return "환불할 수 있는 상태가 아니에요. 이미 취소됐을 수 있어요.";
  if (code === "PAYMENT_NOT_FOUND") return "결제를 찾지 못했어요.";
  return null;
}

/** 재시도 요청이 "그사이 시도가 이미 끝났다"로 받는 거부들(새 환불로 받혀 0원·상태·견적에서 막힌 것). */
function isAttemptAlreadySettled(code: string | null) {
  return (
    code === "REFUND_QUOTE_CHANGED" ||
    code === "REFUND_AMOUNT_ZERO" ||
    code === "PAYMENT_NOT_REFUNDABLE" ||
    code === "REFUND_RECEIVED_ON_INVALID"
  );
}

/** 견적 모드는 받은 견적 금액을 싣고, 확인·재시도 모드(`quote` 없음)는 0원을 싣는다 — 서버는 진행 중 시도가 있으면
 * 이 값을 쓰지 않고, 없으면 0원 견적은 422·0원이 아닌 견적은 409로 거부해 새 환불을 시작하지 않는다. */
function buildRefundRequest(
  values: RefundFormValues,
  quote: AdminRefundQuoteResponse | null,
  today: string,
): AdminRefundRequest {
  return {
    reason: values.reason,
    expectedRefundKrw: quote?.refundKrw ?? 0,
    receivedOn: quote ? values.receivedOn : today,
    companyFault: quote ? values.companyFault : false,
  };
}

/** 응답을 못 받은 뒤의 문장. 실행이 끝날 때 구매 내역을 다시 읽으므로 지금 모드가 곧 서버의 답이다 — 다시 읽기마저
 * 실패했으면 아무것도 단정하지 않는다. 견적 모드의 재확정은 앞 요청이 늦게 닿아 시도가 생겼어도 서버가 그 시도를
 * 이어받아 두 번 환불되지 않는다. */
function unknownResultMessage(isAttemptPending: boolean, isPaymentsRefetchFailed: boolean) {
  if (isAttemptPending) {
    return "응답을 받지 못했어요. 결과를 기다리는 환불 시도가 남아 있어요 — 확인·재시도로 마무리해주세요.";
  }
  if (isPaymentsRefetchFailed) {
    return "응답을 받지 못했고 구매 내역도 다시 읽지 못했어요. 잠시 뒤 창을 닫고 구매 내역에서 상태를 확인해주세요.";
  }
  return "응답을 받지 못했지만 진행 중인 환불 시도는 없어요. 견적을 확인하고 다시 확정해주세요.";
}

/** 서버 견적이 받는 상태와 같다(그 밖은 422 `PAYMENT_NOT_REFUNDABLE`). */
function isRefundableStatus(status: AdminUserPaymentItem["status"]) {
  return status === "paid" || status === "partially_cancelled";
}

function receivedOnRangeMessage(paidOn: string, today: string) {
  return `접수일은 결제일(${paidOn})부터 오늘(${today}) 사이로 골라주세요.`;
}

/** 거부 code 는 OpenAPI 에 없어 `detail.code`를 직접 읽는다(`UserActionConfirmModal`의 `hasDetailCode`와 같은 모양). */
function detailCode(detail: unknown) {
  if (typeof detail !== "object" || detail === null || !("code" in detail)) return null;
  return typeof detail.code === "string" ? detail.code : null;
}
