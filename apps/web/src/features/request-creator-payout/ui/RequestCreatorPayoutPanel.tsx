import { Button } from "@ai-character-chat/ui/components/button";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
  REQUEST_PAYOUT_MESSAGES,
  toRequestPayoutFailure,
  useRequestCreatorPayoutMutation,
  type RequestPayoutFailure,
} from "@/entities/creator-payout";
import { formatKrw } from "@/shared/lib/number/formatKrw";
import { formatDate } from "@/shared/lib/time/formatDate";

import { getRequestView, type RequestViewInput } from "../model/requestView";

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";

type RequestCreatorPayoutPanelProps = {
  payout: RequestViewInput;
  /** 같은 화면의 지급 정보 영역 id. 등록이 먼저 필요하면 그 자리로 가는 링크를 단다. */
  payoutInfoSectionId: string;
};

/** 지급 신청 자리. 무엇을 둘지는 `getRequestView`가 정하고, 여기서는 그 모양대로 그린다.
 *
 * 신청은 확정 잔액 전액이라 금액 칸이 없고, 버튼 글자에 금액을 적어 무엇을 신청하는지 누르기 전에 보인다. 원천징수
 * 금액은 서버가 신청 때 계산해 돌려주므로 신청 뒤 알림과 지급 내역에서 보인다.
 *
 * 신청이 성공하면 누른 버튼째 "처리 중" 블록으로 바뀌어 사라지므로, 이 자리에서 신청한 직후에만 그 블록으로 포커스를
 * 옮긴다(정산 신청 패널과 같다).
 *
 * 실패 문장은 이 패널이 쥐고 갈래 아래에 그린다. 거절은 정산 요약을 다시 읽은 뒤에 오는데, 그 사이 갈래가 바뀌면
 * (잔액이 최소액 아래로 내려가는 등) 신청 버튼째 사라진다 — 문장을 버튼 곁에 두면 함께 사라지고 포커스가 `<body>` 로
 * 떨어진다. 그래서 문장을 갈래와 무관하게 두고, 실패하면 포커스를 문장으로 옮긴다. */
export function RequestCreatorPayoutPanel({ payout, payoutInfoSectionId }: RequestCreatorPayoutPanelProps) {
  const [failure, setFailure] = useState<ShownRequestFailure | null>(null);
  const shouldFocusStatusRef = useRef(false);
  const shouldFocusFailureRef = useRef(false);
  const focusStatusIfJustRequested = (element: HTMLElement | null) => {
    if (!element || !shouldFocusStatusRef.current) return;
    shouldFocusStatusRef.current = false;
    element.focus();
  };
  const focusFailureIfJustFailed = (element: HTMLElement | null) => {
    if (!element || !shouldFocusFailureRef.current) return;
    shouldFocusFailureRef.current = false;
    element.focus();
  };

  return (
    <>
      <RequestViewBlock
        payout={payout}
        payoutInfoSectionId={payoutInfoSectionId}
        statusRef={focusStatusIfJustRequested}
        onRequestStart={() => {
          shouldFocusStatusRef.current = true;
          setFailure(null);
        }}
        onRequestFail={(next) => {
          shouldFocusStatusRef.current = false;
          // 재동의 거절은 재동의 모달이 대신 말한다(전역 뮤테이션 처리가 세션을 다시 읽어 띄운다).
          if (next === "reconsentRequired") return;
          shouldFocusFailureRef.current = true;
          setFailure(next);
        }}
      />
      {failure && (
        <p
          ref={focusFailureIfJustFailed}
          tabIndex={-1}
          role="alert"
          className="text-sm break-keep text-destructive-text outline-none"
        >
          {REQUEST_PAYOUT_MESSAGES[failure]}
          {failure === "infoUnreadable" && (
            <>
              {" "}
              <a href={`#${payoutInfoSectionId}`} className={INLINE_LINK_CLASS}>
                지급 정보 다시 입력하기
              </a>
            </>
          )}
        </p>
      )}
    </>
  );
}

type ShownRequestFailure = Exclude<RequestPayoutFailure, "reconsentRequired">;

type RequestViewBlockProps = RequestCreatorPayoutPanelProps & {
  statusRef: (element: HTMLElement | null) => void;
  onRequestStart: () => void;
  onRequestFail: (failure: RequestPayoutFailure) => void;
};

function RequestViewBlock({ payout, payoutInfoSectionId, statusRef, onRequestStart, onRequestFail }: RequestViewBlockProps) {
  const view = getRequestView(payout);
  switch (view.kind) {
    case "inProgress":
      return (
        <div
          ref={statusRef}
          tabIndex={-1}
          role="status"
          className="flex flex-col gap-1 rounded-xl border border-border px-4 py-3 outline-none"
        >
          <p className="text-sm font-medium text-foreground">지급을 처리하고 있어요</p>
          <p className="text-xs break-keep text-muted-foreground">
            {formatDate(view.requestedAt)}에 {formatKrw(view.amountKrw)}을 신청했어요. 이체하면 아래 지급 내역에서 이체한
            날을 볼 수 있어요.
          </p>
        </div>
      );
    case "nothingToPay":
      return <p className="text-sm break-keep text-muted-foreground">지금은 지급을 신청할 적립금이 없어요.</p>;
    case "belowMinimum":
      return (
        <p className="text-sm break-keep text-muted-foreground">
          확정된 적립금이 {formatKrw(view.minimumKrw)} 이상이면 지급을 신청할 수 있어요.
        </p>
      );
    case "infoRequired":
      return (
        <p className="text-sm break-keep text-muted-foreground">
          지급을 신청하려면{" "}
          <a href={`#${payoutInfoSectionId}`} className={INLINE_LINK_CLASS}>
            지급 정보
          </a>
          를 먼저 등록해 주세요.
        </p>
      );
    case "infoUnreadable":
      return (
        <p className="text-sm break-keep text-muted-foreground">
          등록한 지급 정보를 읽을 수 없어요.{" "}
          <a href={`#${payoutInfoSectionId}`} className={INLINE_LINK_CLASS}>
            지급 정보
          </a>
          를 다시 입력하면 신청할 수 있어요.
        </p>
      );
    case "ready":
      return (
        <RequestForm amountKrw={view.amountKrw} onRequestStart={onRequestStart} onRequestFail={onRequestFail} />
      );
  }
}

type RequestFormProps = {
  amountKrw: number;
  /** 신청을 보내기 직전. 성공 뒤 포커스를 어디로 옮길지 패널이 정한다. */
  onRequestStart: () => void;
  /** 신청이 거절됐다. 문장은 패널이 그린다 — 이 폼은 그 사이 사라졌을 수 있다. */
  onRequestFail: (failure: RequestPayoutFailure) => void;
};

/** 신청 버튼과 결과. "지급 신청"이 이 화면의 솔리드 채움이다. 진행 중에는 `disabled` 대신 `aria-disabled` 로 막는다 —
 * `disabled` 는 누른 버튼의 포커스를 날린다. */
function RequestForm({ amountKrw, onRequestStart, onRequestFail }: RequestFormProps) {
  const mutation = useRequestCreatorPayoutMutation();

  const handleRequest = async () => {
    if (mutation.isPending) return;
    onRequestStart();
    try {
      const result = await mutation.mutateAsync({ forWithdrawal: false });
      // 성공하면 정산 요약을 다시 읽어 이 자리가 "처리 중"으로 바뀐다 — 떼는 세금은 이 응답에만 있어 알림으로 말한다.
      toast.success(
        `${formatKrw(result.amountKrw)} 지급을 신청했어요. 원천징수 ${formatKrw(result.incomeTaxKrw + result.localTaxKrw)}을 떼고 ${formatKrw(result.netAmountKrw)}을 이체해요.`,
      );
    } catch (error) {
      onRequestFail(toRequestPayoutFailure(error));
    }
  };

  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-sm break-keep text-muted-foreground">
        확정된 적립금 전액을 신청해요. 원천징수(소득세·지방소득세)를 뗀 금액이 등록한 계좌로 이체돼요.
      </p>
      <Button aria-disabled={mutation.isPending} className="aria-disabled:opacity-65" onClick={() => void handleRequest()}>
        {mutation.isPending ? "신청하는 중…" : `${formatKrw(amountKrw)} 지급 신청하기`}
      </Button>
    </div>
  );
}
