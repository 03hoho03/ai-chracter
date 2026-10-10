import { useState } from "react";

import type { AdminCreatorPayoutDetail } from "@/entities/creator-payout";
import { ActionChoice, type ActionChoiceOption } from "@/shared/ui/ActionChoice";

import { availablePayoutActions, type PayoutAction } from "../model/payoutActions";
import { PayoutReasonForm } from "./PayoutReasonForm";
import { ReplacePayeeForm } from "./ReplacePayeeForm";
import { TransferForm } from "./TransferForm";

const ACTION_LABELS: Record<PayoutAction, string> = {
  transfer: "이체 완료 기록",
  return: "반려",
  hold: "보류",
  "replace-payee": "수취 정보 교체",
};

type PayoutActionPanelProps = {
  payout: AdminCreatorPayoutDetail;
  /** 처리가 성공하면 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess: () => void;
};

/** 걸 수 있는 처리가 있는가. 상세 레이아웃이 조치 열·하단 바를 그릴지 패널을 그리기 전에 알아야 해서 패널 밖 판정으로 둔다. */
export function hasPayoutActions(payout: Pick<AdminCreatorPayoutDetail, "status" | "withdrawn" | "payeeInfoReadable">) {
  return availablePayoutActions(payout).length > 0;
}

/**
 * 지급 건 처리. 실제 이체는 운영자가 은행에서 하고, 여기서는 그 결과를 기록한다. 처리 방법을 고르면 그 처리의 입력칸이
 * 아래에 펼쳐진다. 탈퇴한 회원의 건은 반려 대신 보류·수취 정보 교체가 나온다.
 */
export function PayoutActionPanel({ payout, onSuccess }: PayoutActionPanelProps) {
  const actions = availablePayoutActions(payout);
  const [chosen, setChosen] = useState<PayoutAction>();
  // 처리 뒤 다시 읽어 상태가 바뀌면 고른 처리가 목록에서 빠질 수 있다 — 그때는 고르지 않은 것으로 본다.
  const action = chosen !== undefined && actions.includes(chosen) ? chosen : undefined;
  const options: ActionChoiceOption<PayoutAction>[] = actions.map((value) => ({ value, label: ACTION_LABELS[value] }));

  return (
    <div className="flex flex-col gap-4">
      {payout.withdrawn && (
        <p className="text-sm break-keep text-muted-foreground">
          {/* 이미 보류된 건에는 보류하라는 안내가 맞지 않는다. */}
          {payout.status === "held"
            ? "탈퇴한 회원의 보류된 지급이에요. 문의로 받은 새 정보로 수취 정보를 바꾼 뒤 이체해주세요."
            : "탈퇴한 회원의 지급이라 반려할 수 없어요. 등록된 계좌로 이체할 수 없으면 보류하고, 문의로 받은 새 정보로 수취 정보를 바꾼 뒤 이체해주세요."}
        </p>
      )}

      {!payout.payeeInfoReadable && (
        <p className="text-sm break-keep text-foreground">
          수취 정보를 읽을 수 없어 이체 완료를 기록할 수 없어요.{" "}
          {payout.withdrawn
            ? "문의로 받은 새 정보로 수취 정보를 바꾸면 다시 이체할 수 있어요."
            : "반려하면 신청자가 지급 정보를 다시 입력해 신청할 수 있어요."}
        </p>
      )}

      <ActionChoice legend="처리 방법" options={options} value={action} onValueChange={setChosen} />

      {action === "transfer" && <TransferForm payout={payout} onSuccess={onSuccess} />}
      {(action === "return" || action === "hold") && (
        <PayoutReasonForm key={action} kind={action} payoutId={payout.id} onSuccess={onSuccess} />
      )}
      {action === "replace-payee" && <ReplacePayeeForm payoutId={payout.id} onSuccess={onSuccess} />}
    </div>
  );
}
