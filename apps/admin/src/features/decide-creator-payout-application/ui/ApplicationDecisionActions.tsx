import { Button } from "@ai-character-chat/ui/components/button";

import {
  CREATOR_PAYOUT_BLOCK_REASON_LABELS,
  getCreatorPayoutBlockReason,
  type AdminCreatorPayoutApplicationItem,
} from "@/entities/creator-payout-application";

import { ApproveApplicationModal } from "./ApproveApplicationModal";
import { DecisionReasonModal } from "./DecisionReasonModal";

type ApplicationDecisionActionsProps = {
  application: AdminCreatorPayoutApplicationItem;
  /** 모달 문구에 쓰는 신청자 이름(탈퇴 회원은 닉네임이 파기돼 호출부가 대신할 말을 정한다). */
  applicantName: string;
};

/**
 * 신청 상태마다 할 수 있는 처리. 대기 → 승인·거절, 승인 → 승인 취소. 거절·승인 취소는 종단이라 버튼이 없다.
 * 지금 자격이 없으면 승인을 막고 이유를 옆에 둔다 — 서버도 같은 판정으로 거부하고, 막힌 신청은 거절로 정리한다.
 */
export function ApplicationDecisionActions({ application, applicantName }: ApplicationDecisionActionsProps) {
  if (application.status === "pending") {
    const blockReason = getCreatorPayoutBlockReason(application.eligibility);
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            disabled={blockReason !== null}
            aria-describedby={blockReason ? "approve-blocked-reason" : undefined}
            onClick={() => void ApproveApplicationModal.call({ application, applicantName })}
          >
            승인
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void DecisionReasonModal.call({ kind: "reject", application, applicantName })}
          >
            거절
          </Button>
        </div>
        {blockReason && (
          <p id="approve-blocked-reason" className="text-xs break-keep text-muted-foreground">
            {CREATOR_PAYOUT_BLOCK_REASON_LABELS[blockReason]} — 지금 자격이 없어 승인할 수 없어요.
          </p>
        )}
      </div>
    );
  }

  if (application.status === "approved") {
    return (
      <div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void DecisionReasonModal.call({ kind: "revoke", application, applicantName })}
        >
          승인 취소
        </Button>
      </div>
    );
  }

  return null;
}
