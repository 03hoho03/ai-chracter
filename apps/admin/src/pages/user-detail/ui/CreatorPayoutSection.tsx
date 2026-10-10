import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";

import { CREATOR_PAYOUT_APPLICATION_STATUS_LABELS } from "@/entities/creator-payout-application";
import {
  CREATOR_PAYOUT_CONFIRMATION_KIND_LABELS,
  CREATOR_PAYOUT_STATUS_LABELS,
  formatKrw,
  formatRateBps,
  useUserCreatorPayoutQuery,
  type AdminUserCreatorPayoutResponse,
} from "@/entities/creator-payout";
import { formatCount } from "@/shared/lib/format/formatCount";
import { formatDateTime, formatDateTimeParts } from "@/shared/lib/format/formatDateTime";
import { DenseTable } from "@/shared/ui/DenseTable";

const INLINE_LINK_CLASS =
  "admin-hit-area font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none";

type CreatorPayoutSectionProps = {
  userId: string;
};

/**
 * 크리에이터 정산 — 신청 이력·적립 잔액·최근 확정·최근 지급. 원장·구매 내역처럼 별도 라우트라 로딩·오류를 이 섹션이 따로
 * 진다. 처리(승인·지급)는 각 큐에서 하고 여기는 보기만 한다 — 지급 행은 그 지급 상세로 간다.
 */
export function CreatorPayoutSection({ userId }: CreatorPayoutSectionProps) {
  const payoutQuery = useUserCreatorPayoutQuery(userId);

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 @xl:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold text-foreground">크리에이터 정산</h2>
        {payoutQuery.isSuccess && (
          <p className="text-sm text-muted-foreground">
            적립 잔액{" "}
            <span className="font-semibold text-foreground tabular-nums">{formatKrw(payoutQuery.data.balanceKrw)}</span>
          </p>
        )}
      </div>

      <CreatorPayoutBody payoutQuery={payoutQuery} />
    </section>
  );
}

type CreatorPayoutBodyProps = {
  payoutQuery: ReturnType<typeof useUserCreatorPayoutQuery>;
};

function CreatorPayoutBody({ payoutQuery }: CreatorPayoutBodyProps) {
  if (payoutQuery.isPending) {
    return <div className="h-24 animate-pulse rounded-lg bg-secondary" />;
  }

  if (payoutQuery.isError) {
    return <p className="text-sm text-destructive-text">정산 기록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  const data = payoutQuery.data;
  if (data.applications.length === 0) {
    return <p className="text-sm text-muted-foreground">크리에이터 정산을 신청한 적이 없어요.</p>;
  }

  return (
    <>
      {data.balanceKrw < 0 && (
        <p className="text-sm break-keep text-muted-foreground">
          잔액이 음수예요 — 지급한 뒤 결제가 취소돼 생긴 조정이고, 다음 확정 적립에서 차감돼요.
        </p>
      )}
      <ApplicationsTable applications={data.applications} />
      <ConfirmationsTable confirmations={data.confirmations} />
      <PayoutsTable payouts={data.payouts} />
    </>
  );
}

function SubHeading({ children }: { children: string }) {
  return <h3 className="text-sm font-medium text-foreground">{children}</h3>;
}

function ApplicationsTable({ applications }: { applications: AdminUserCreatorPayoutResponse["applications"] }) {
  return (
    <div className="flex flex-col gap-2">
      <SubHeading>신청 이력</SubHeading>
      <div className="overflow-hidden rounded-lg border border-border">
        <DenseTable surface="card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>상태</TableHead>
                <TableHead>신청일시</TableHead>
                <TableHead>처리일시</TableHead>
                <TableHead>적립 시작</TableHead>
                <TableHead>사유 (신청자에게 보임)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {applications.map((application) => (
                <TableRow key={application.id}>
                  <TableCell>{CREATOR_PAYOUT_APPLICATION_STATUS_LABELS[application.status]}</TableCell>
                  <DateTimeCell value={application.appliedAt} />
                  <DateTimeCell value={application.revokedAt ?? application.decidedAt} />
                  <DateTimeCell value={application.accrualStartAt} />
                  <TableCell className="min-w-48 whitespace-normal break-keep text-muted-foreground wrap-anywhere">
                    {application.decisionReason || "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DenseTable>
      </div>
    </div>
  );
}

function ConfirmationsTable({ confirmations }: { confirmations: AdminUserCreatorPayoutResponse["confirmations"] }) {
  return (
    <div className="flex flex-col gap-2">
      <SubHeading>최근 확정 (12건까지)</SubHeading>
      {confirmations.length === 0 ? (
        <p className="text-sm text-muted-foreground">확정된 적립이 아직 없어요.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <DenseTable surface="card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>기간</TableHead>
                  <TableHead>종류</TableHead>
                  <TableHead className="text-right">유료 사용</TableHead>
                  <TableHead className="text-right">환급</TableHead>
                  <TableHead className="text-right">비율</TableHead>
                  <TableHead className="text-right">적립액</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {confirmations.map((confirmation) => (
                  <TableRow key={confirmation.id}>
                    <TableCell>{confirmationPeriodLabel(confirmation)}</TableCell>
                    <TableCell>{CREATOR_PAYOUT_CONFIRMATION_KIND_LABELS[confirmation.kind]}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatCount(confirmation.grossUnits)}</TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {formatCount(confirmation.refundedUnits)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatRateBps(confirmation.rateBps)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatKrw(confirmation.amountKrw)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DenseTable>
        </div>
      )}
    </div>
  );
}

/** 월 확정은 그 달(`YYYY-MM`), 소급은 센 구간의 시작~끝 시각이다(소급은 한 번뿐이고 달에 맞춰 끊기지 않는다). */
function confirmationPeriodLabel(confirmation: AdminUserCreatorPayoutResponse["confirmations"][number]) {
  if (confirmation.periodMonth) return confirmation.periodMonth.slice(0, 7);
  return `${formatDateTime(confirmation.windowStart)} ~ ${formatDateTime(confirmation.windowEnd)}`;
}

function PayoutsTable({ payouts }: { payouts: AdminUserCreatorPayoutResponse["payouts"] }) {
  return (
    <div className="flex flex-col gap-2">
      <SubHeading>최근 지급 (20건까지)</SubHeading>
      {payouts.length === 0 ? (
        <p className="text-sm text-muted-foreground">지급을 신청한 적이 없어요.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <DenseTable surface="card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>신청일시</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead className="text-right">신청액</TableHead>
                  <TableHead className="text-right">실지급액</TableHead>
                  <TableHead>이체일</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {payouts.map((payout) => (
                  <TableRow key={payout.id}>
                    <TableCell>
                      <Link
                        to="/creator-payouts/$payoutId"
                        params={{ payoutId: payout.id }}
                        className={INLINE_LINK_CLASS}
                      >
                        {formatDateTime(payout.requestedAt)}
                      </Link>
                    </TableCell>
                    <TableCell>{CREATOR_PAYOUT_STATUS_LABELS[payout.status]}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatKrw(payout.amountKrw)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatKrw(payout.netAmountKrw)}</TableCell>
                    <TableCell className="tabular-nums">{payout.transferredOn ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DenseTable>
        </div>
      )}
    </div>
  );
}

/** 표의 일시 칸 — 모자라면 날짜와 시각 사이에서만 두 줄로 꺾인다(회원 상세의 다른 표와 같다). */
function DateTimeCell({ value }: { value: string | null }) {
  if (!value) return <TableCell>-</TableCell>;
  const { date, time } = formatDateTimeParts(value);
  return (
    <TableCell className="whitespace-normal">
      <span className="whitespace-nowrap">{date}</span> <span className="whitespace-nowrap">{time}</span>
    </TableCell>
  );
}
