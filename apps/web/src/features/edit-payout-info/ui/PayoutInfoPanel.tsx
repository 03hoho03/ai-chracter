import { Button } from "@ai-character-chat/ui/components/button";
import { useRef, useState } from "react";

import { BANK_LABELS, type CreatorPayoutResponse } from "@/entities/creator-payout";

import { PayoutInfoForm } from "./PayoutInfoForm";

const STATUS_BLOCK_CLASS = "flex flex-col gap-3 rounded-xl border border-border px-4 py-3";

type PayoutInfoPanelProps = {
  payout: Pick<CreatorPayoutResponse, "payoutInfo" | "inProgressPayout">;
};

/** 지급 정보 영역. 등록한 정보가 있으면 마스킹한 표시값(실명 첫·끝 글자, 은행, 계좌 끝 4자리)을 보이고 "바꾸기"로 같은
 * 자리에서 폼을 연다(리스트 항목의 인라인 편집과 같다 — 모달로 덮을 만큼 길지 않다). 없으면 처음부터 폼이다.
 * 주민등록번호는 서버가 돌려주지 않아 "등록됨"으로만 말한다.
 *
 * 처리 중인 지급이 있으면 서버가 변경을 받지 않으므로(처리 중 건의 수취인을 바꾸지 않는다) 바꾸기 버튼 대신 그 사실을
 * 말한다. 저장하거나 취소하면 폼이 닫히며 누른 버튼째 사라지므로, 그때만 표시 블록으로 포커스를 옮긴다(정산 신청
 * 패널과 같다). 거꾸로 "바꾸기"로 폼을 열 때도 누른 버튼이 사라지므로 폼의 첫 칸으로 옮긴다. */
export function PayoutInfoPanel({ payout }: PayoutInfoPanelProps) {
  const [isEditing, setIsEditing] = useState(false);
  const shouldFocusSummaryRef = useRef(false);
  const { payoutInfo } = payout;
  const isLocked = payout.inProgressPayout !== null;

  const focusSummaryIfJustSaved = (element: HTMLElement | null) => {
    if (!element || !shouldFocusSummaryRef.current) return;
    shouldFocusSummaryRef.current = false;
    element.focus();
  };
  const closeForm = () => {
    shouldFocusSummaryRef.current = true;
    setIsEditing(false);
  };

  if (payoutInfo === null || isEditing) {
    return (
      <div className="flex flex-col gap-4">
        {payoutInfo === null && (
          <p className="text-sm break-keep text-muted-foreground">
            지급을 받을 본인 명의 계좌를 등록해 주세요. 원천징수와 지급명세서 제출에 주민등록번호가 필요해요.
          </p>
        )}
        <PayoutInfoForm
          onSaved={closeForm}
          onCancel={payoutInfo === null ? undefined : closeForm}
          focusOnOpen={isEditing}
        />
      </div>
    );
  }

  return (
    <div ref={focusSummaryIfJustSaved} tabIndex={-1} className={`${STATUS_BLOCK_CLASS} outline-none`}>
      {/* 복호화하지 못하면(암호화 키를 잃었다) 실명이 없다. 은행·계좌 끝자리는 남아 있지만 운영자도 원문을 읽지 못해
          이체할 수 없으므로 다시 입력받는다. */}
      {payoutInfo.maskedName === null && (
        <p className="text-sm break-keep text-foreground">
          등록한 지급 정보를 읽을 수 없어요. 지급 정보를 다시 입력해 주세요.
        </p>
      )}
      <dl className="flex flex-col gap-1.5 text-sm">
        {payoutInfo.maskedName !== null && <InfoRow term="실명" detail={payoutInfo.maskedName} />}
        <InfoRow term="주민등록번호" detail="등록됨" />
        <InfoRow term="계좌" detail={`${BANK_LABELS[payoutInfo.bankCode]} ****${payoutInfo.accountLast4}`} />
      </dl>
      {isLocked ? (
        <p className="text-xs break-keep text-muted-foreground">처리 중인 지급이 끝나면 지급 정보를 바꿀 수 있어요.</p>
      ) : (
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => setIsEditing(true)}>
          {payoutInfo.maskedName === null ? "다시 입력하기" : "지급 정보 바꾸기"}
        </Button>
      )}
    </div>
  );
}

function InfoRow({ term, detail }: { term: string; detail: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-muted-foreground">{term}</dt>
      <dd className="min-w-0 text-right break-keep text-foreground tabular-nums">{detail}</dd>
    </div>
  );
}
