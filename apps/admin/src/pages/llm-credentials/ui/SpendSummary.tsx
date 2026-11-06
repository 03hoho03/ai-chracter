import { Button } from "@ai-character-chat/ui/components/button";

import { formatCount } from "@/shared/lib/format/formatCount";
import { formatMonthDayTime } from "@/shared/lib/format/formatDateTime";

import type { AdminLlmCredential, AdminLlmCredentialSpend } from "../model/credential";
import { formatUsd, remainingRatio } from "../model/money";
import { NEUTRAL_BADGE_CLASS, PROBLEM_BADGE_CLASS } from "./badgeClasses";

type SpendSummaryProps = {
  credential: AdminLlmCredential;
  /** 행 버튼 접근 이름의 앞머리("2번째 운영 계정") — 같은 이름의 항목이 둘이어도 위치로 갈린다. */
  itemName: string;
  onCreditBasis: () => void;
};

/** 충전액 기준 이후의 추정 사용액. 금액은 서버의 달러 문자열을 표시만 하고, 임계 아래인지는 서버의 `belowAlert` 를 쓴다. */
export function SpendSummary({ credential, itemName, onCreditBasis }: SpendSummaryProps) {
  const { creditUsd, spend } = credential;
  const actionName = creditUsd === null ? "충전액 넣기" : "충전액 맞추기";

  return (
    <div className="flex min-w-0 flex-col items-start gap-2">
      <h4 className="text-sm font-semibold text-foreground">사용액</h4>
      <SpendBody creditUsd={creditUsd} creditSince={credential.creditSince} alertPct={credential.alertPct} spend={spend} />
      <Button type="button" variant="outline" size="sm" aria-label={`${itemName} ${actionName}`} onClick={onCreditBasis}>
        {actionName}…
      </Button>
    </div>
  );
}

type SpendBodyProps = {
  creditUsd: string | null;
  creditSince: string | null;
  alertPct: number;
  spend: AdminLlmCredentialSpend | null;
};

function SpendBody({ creditUsd, creditSince, alertPct, spend }: SpendBodyProps) {
  if (creditUsd === null) {
    return <p className="break-keep text-sm text-muted-foreground">충전액 없음 — 사용액을 세지 않아요.</p>;
  }
  if (spend === null) {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-sm tabular-nums text-foreground">충전 {formatUsd(creditUsd)}</p>
        <p className="break-keep text-sm text-destructive-text">추정 사용액을 읽지 못했어요.</p>
      </div>
    );
  }

  const ratio = remainingRatio(spend.remainingUsd, creditUsd);
  const isOverspent = Number(spend.remainingUsd) < 0;

  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm tabular-nums text-foreground">
        추정 잔액 {formatUsd(spend.remainingUsd)} / 충전 {formatUsd(creditUsd)}
        {ratio !== undefined && (
          <span className="text-muted-foreground">
            {" "}
            (남은 {Math.round(ratio * 100)}% · 임계 {alertPct}%)
          </span>
        )}
      </p>
      <p className="text-xs tabular-nums text-muted-foreground">
        추정 사용 {formatUsd(spend.spentUsd)} · 호출 {formatCount(spend.calls)}회
        {creditSince !== null && ` · ${formatMonthDayTime(creditSince)}부터`}
      </p>
      {(spend.belowAlert || isOverspent || spend.unpricedCalls > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {spend.belowAlert && <span className={PROBLEM_BADGE_CLASS}>임계 아래</span>}
          {isOverspent && <span className={PROBLEM_BADGE_CLASS}>추정 초과</span>}
          {spend.unpricedCalls > 0 && (
            <span className={NEUTRAL_BADGE_CLASS}>단가 없음 {formatCount(spend.unpricedCalls)}회</span>
          )}
        </div>
      )}
    </div>
  );
}
