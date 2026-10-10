import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";

import {
  PAYOUT_INFO_SECTION_ID,
  REQUEST_PAYOUT_MESSAGES,
  toRequestPayoutFailure,
  useRequestCreatorPayoutMutation,
  type RequestPayoutFailure,
} from "@/entities/creator-payout";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";
import { formatKrw } from "@/shared/lib/number/formatKrw";

import type { CreatorEarningsWarning } from "../model/creatorEarningsWarning";
import type { WithdrawalPayoutAction } from "../model/withdrawalPayoutAction";

// 틴트 위 링크. 유료 클로버 경고의 메일 링크와 같다 — 쉬는 상태에 이미 밑줄이 있어 포커스는 불투명 아웃라인으로 준다.
const TINT_LINK_CLASS =
  "font-medium whitespace-nowrap underline underline-offset-4 focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring";

type CreatorEarningsWarningMessageProps = {
  warning: CreatorEarningsWarning;
  action: WithdrawalPayoutAction;
};

/** 크리에이터 적립금 경고. 유료 클로버 경고와 같은 틴트 블록이다. 문장마다 아는 만큼만 말한다 — 금액은 확정 잔액이
 * 0 보다 클 때만, 모르면 "있다면"·"있었다면" 조건으로.
 *
 * 경고 다음에 탈퇴 전에 받을 길(`action`)을 말한다. 최소 지급액 미만 잔액은 탈퇴 확인에서만 신청을 받아 이 블록에 신청
 * 버튼을 두고, 그 밖의 신청은 정산 화면으로 보낸다. 지급 신청이 없는 동안의 문장("준비 중")은 서버가 지급을 받지
 * 않는다고 답했을 때만 남는다. 정산 정책 링크는 새 탭이다 — 이 다이얼로그를 닫지 않고 읽을 수 있다(재동의 모달
 * 안에서도 새 탭은 열린다). */
export function CreatorEarningsWarningMessage({ warning, action }: CreatorEarningsWarningMessageProps) {
  if (warning.kind === "none") return null;
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text sm:items-start">
      <p role="alert">
        {creatorEarningsLead(warning)}
        {payoutActionSentence(action) && ` ${payoutActionSentence(action)}`}
      </p>
      {action.kind === "request" && <WithdrawalPayoutRequestButton balanceKrw={action.balanceKrw} />}
      {action.kind === "registerInfo" && (
        <Link to="/creator-payout" hash={PAYOUT_INFO_SECTION_ID} className={TINT_LINK_CLASS}>
          지급 정보 등록하러 가기
        </Link>
      )}
      {action.kind === "goToPayout" && (
        <Link to="/creator-payout" className={TINT_LINK_CLASS}>
          크리에이터 정산에서 신청하기
        </Link>
      )}
      <p className="text-xs">
        자세한 기준은{" "}
        <Link
          to={SUPPORT_DESTINATIONS["creator-payout-policy"].to}
          target="_blank"
          rel="noopener"
          className={TINT_LINK_CLASS}
        >
          {SUPPORT_DESTINATIONS["creator-payout-policy"].label}
        </Link>
        에서 볼 수 있어요.
      </p>
    </div>
  );
}

function creatorEarningsLead(warning: Exclude<CreatorEarningsWarning, { kind: "none" }>): string {
  switch (warning.kind) {
    case "confirmed":
      return `크리에이터 정산의 확정된 적립금 ${formatKrw(warning.balanceKrw)}과 아직 확정되지 않은 적립이 모두 사라져요.`;
    case "unconfirmed":
      return "크리에이터 정산에서 아직 확정되지 않은 적립이 있다면 함께 사라져요.";
    case "unavailable":
      return "크리에이터 정산 적립금이 있었다면 탈퇴할 때 함께 사라져요.";
    case "unknown":
      return "크리에이터 정산 적립금이 있다면 확정된 적립금과 아직 확정되지 않은 적립이 모두 사라져요.";
  }
}

function payoutActionSentence(action: WithdrawalPayoutAction): string | null {
  switch (action.kind) {
    case "request":
      return `탈퇴하기 전에 남은 적립금 ${formatKrw(action.balanceKrw)}을 지급 신청할 수 있어요. 신청하지 않으면 사라져요.`;
    case "registerInfo":
      return `탈퇴하기 전에 남은 적립금 ${formatKrw(action.balanceKrw)}을 지급 신청할 수 있어요. 지급 정보를 먼저 등록해야 하고, 신청하지 않으면 사라져요.`;
    case "goToPayout":
      return `탈퇴하기 전에 크리에이터 정산 화면에서 남은 적립금 ${formatKrw(action.balanceKrw)}을 지급 신청할 수 있어요. 신청하지 않으면 사라져요.`;
    case "afterReconsent":
      return `약관에 동의하면 탈퇴하기 전에 크리에이터 정산 화면에서 남은 적립금 ${formatKrw(action.balanceKrw)}을 지급 신청할 수 있어요. 신청하지 않으면 사라져요.`;
    case "inProgress":
      return "이미 신청한 지급은 탈퇴해도 처리돼요.";
    case "notOffered":
      return "지급 신청 기능은 아직 준비 중이라, 지금 탈퇴하면 받을 수 없어요.";
    case "unknown":
    case "none":
      return null;
  }
}

/** 최소 지급액 미만 잔액의 탈퇴 전 신청. 성공하면 정산 요약을 다시 읽어 이 버튼이 "처리 중" 문장으로 바뀐다 — 떼는
 * 세금은 이 응답에만 있어 알림으로 말한다. 진행 중에는 `disabled` 대신 `aria-disabled` 로 막는다(누른 버튼의 포커스). */
function WithdrawalPayoutRequestButton({ balanceKrw }: { balanceKrw: number }) {
  const [failure, setFailure] = useState<Exclude<RequestPayoutFailure, "reconsentRequired"> | null>(null);
  const mutation = useRequestCreatorPayoutMutation();

  const handleRequest = async () => {
    if (mutation.isPending) return;
    setFailure(null);
    try {
      const result = await mutation.mutateAsync({ forWithdrawal: true });
      toast.success(
        `${formatKrw(result.amountKrw)} 지급을 신청했어요. 원천징수 ${formatKrw(result.incomeTaxKrw + result.localTaxKrw)}을 떼고 ${formatKrw(result.netAmountKrw)}을 이체해요.`,
      );
    } catch (error) {
      const next = toRequestPayoutFailure(error);
      // 재동의 모달이 대신 말한다(전역 뮤테이션 처리가 세션을 다시 읽어 띄운다).
      if (next !== "reconsentRequired") setFailure(next);
    }
  };

  return (
    <div className="flex flex-col items-center gap-1.5 sm:items-start">
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-disabled={mutation.isPending}
        className="aria-disabled:opacity-65"
        onClick={() => void handleRequest()}
      >
        {mutation.isPending ? "신청하는 중…" : `${formatKrw(balanceKrw)} 지급 신청하기`}
      </Button>
      {failure && (
        <p role="alert" className="text-sm">
          {REQUEST_PAYOUT_MESSAGES[failure]}
        </p>
      )}
      {failure === "infoUnreadable" && (
        <Link to="/creator-payout" hash={PAYOUT_INFO_SECTION_ID} className={TINT_LINK_CLASS}>
          지급 정보 다시 입력하러 가기
        </Link>
      )}
    </div>
  );
}
