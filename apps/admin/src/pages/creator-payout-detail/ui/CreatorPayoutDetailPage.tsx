import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import {
  CREATOR_PAYOUT_STATUS_LABELS,
  formatKrw,
  formatRateBps,
  isWithholdingChanged,
  useCreatorPayoutDetailQuery,
  WithdrawnBadge,
  type AdminCreatorPayoutDetail,
  type AdminCreatorPayoutWithholding,
} from "@/entities/creator-payout";
import { hasPayoutActions, PayoutActionPanel } from "@/features/complete-creator-payout";
import { PayeeInfoReveal } from "@/features/view-payee-info";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useRememberedListSearch } from "@/shared/lib/list-search-memory/listSearchMemory";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DetailLayout } from "@/shared/ui/DetailLayout";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";

const PAGE_TITLE = "지급 상세";

const SECTION_CLASS = "flex flex-col gap-4 rounded-xl border border-border bg-card p-4 @xl:p-6";

type CreatorPayoutDetailPageProps = {
  payoutId: string;
};

export function CreatorPayoutDetailPage({ payoutId }: CreatorPayoutDetailPageProps) {
  const rememberedListSearch = useRememberedListSearch("/creator-payouts/");

  return (
    <PageContainer>
      <PageHeader
        title={PAGE_TITLE}
        back={
          <Button asChild variant="ghost" size="sm" className="self-start">
            <Link to="/creator-payouts" search={rememberedListSearch ?? {}}>
              <ChevronLeft aria-hidden />
              목록으로
            </Link>
          </Button>
        }
      />

      {/* 지급 건이 바뀌면 본문을 새로 그린다 — 앞 건에서 연 수취인 원문·적던 입력이 다음 건으로 넘어가지 않게. */}
      <PayoutDetailBody key={payoutId} payoutId={payoutId} />
    </PageContainer>
  );
}

/** 목록 링크·제목은 로딩·오류에도 남아야 해서 쿼리에 기대는 본문만 갈라낸다. */
function PayoutDetailBody({ payoutId }: { payoutId: string }) {
  const detailQuery = useCreatorPayoutDetailQuery(payoutId);
  // 탭 제목에 신청자 이름을 싣지 않는다 — 지급 정보 원문을 여는 화면이라 이름이 브라우저 기록에 남지 않게 화면명만 둔다.
  useDocumentTitle(PAGE_TITLE);

  return (
    <QueryState query={detailQuery} skeleton="detail" errorMessage="지급 정보를 불러오지 못했어요.">
      {(payout) => (
        <DetailLayout
          actions={
            hasPayoutActions(payout)
              ? {
                  title: "지급 처리",
                  triggerLabel: "처리하기",
                  summary: `${CREATOR_PAYOUT_STATUS_LABELS[payout.status]}${payout.withdrawn ? " · 탈퇴한 회원" : ""}`,
                  render: (host) => <PayoutActionPanel payout={payout} onSuccess={host.onDone} />,
                }
              : null
          }
        >
          <SummarySection payout={payout} />
          <WithholdingSection payout={payout} />
          <section className={SECTION_CLASS} aria-labelledby="payee-heading">
            <div className="flex flex-col gap-1">
              <h2 id="payee-heading" className="text-lg font-semibold text-foreground">
                수취인
              </h2>
              {payout.payeeEnteredByAdmin && (
                <p className="text-sm break-keep text-muted-foreground">
                  운영자가 문의로 받아 바꾼 수취 정보예요.
                </p>
              )}
            </div>
            {payout.payeeInfoReadable && payout.maskedName !== null ? (
              // 수취 정보 판이 바뀌면(운영자 교체) 앞 판에서 연 원문을 버린다.
              <PayeeInfoReveal
                key={payout.payeeProfileId}
                payoutId={payout.id}
                maskedName={payout.maskedName}
                bankCode={payout.bankCode}
                accountLast4={payout.accountLast4}
              />
            ) : (
              // 복호화하지 못한 수취인은 마스킹 이름도 원문도 없다 — 은행·끝 4자리는 평문이지만 실명 없이 보이면 확인된
              // 수취인처럼 읽혀 함께 숨긴다.
              <div role="note" className="flex items-start gap-2 rounded-lg border border-border p-3 text-sm text-foreground">
                <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
                <p className="break-keep">
                  <span className="font-semibold">수취 정보를 읽을 수 없어요.</span> 암호화 키 문제라 원문 열람과 이체 기록을
                  막아 뒀어요. 개발 담당자에게 알려주세요.
                </p>
              </div>
            )}
          </section>
          <HistorySection payout={payout} />
        </DetailLayout>
      )}
    </QueryState>
  );
}

function SummarySection({ payout }: { payout: AdminCreatorPayoutDetail }) {
  return (
    <section className={SECTION_CLASS} aria-label="지급 요약">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
          {CREATOR_PAYOUT_STATUS_LABELS[payout.status]}
        </span>
        {payout.withdrawn && <WithdrawnBadge />}
        <span className="text-sm text-muted-foreground">{formatDateTime(payout.requestedAt)} 신청</span>
      </div>

      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold break-all text-foreground">{payout.nickname ?? "탈퇴한 회원"}</h2>
        {/* 탈퇴 회원은 회원 상세가 404 라 링크를 두지 않는다 — 이 화면이 처리에 필요한 값을 다 가진다. */}
        {payout.withdrawn ? (
          <p className="text-sm break-keep text-muted-foreground">탈퇴한 회원이라 회원 상세가 없어요.</p>
        ) : (
          <Link
            to="/users/$userId"
            params={{ userId: payout.userId }}
            className="admin-hit-area w-fit text-sm font-medium text-primary hover:underline focus-visible:underline"
          >
            회원 상세 보기
          </Link>
        )}
      </div>

      <dl className="grid gap-x-6 gap-y-3 text-sm @xl:grid-cols-2">
        <Field label="신청액">{formatKrw(payout.amountKrw)}</Field>
        <Field label="실지급액 (원천징수 뒤)">
          <span className="font-semibold">{formatKrw(payout.withholding.netAmountKrw)}</span>
        </Field>
        {payout.forWithdrawal && (
          <Field label="신청 경로" wide>
            탈퇴 직전 신청 — 최소 지급액 미만이어도 받은 건이에요.
          </Field>
        )}
      </dl>
    </section>
  );
}

/**
 * 원천징수. 이체는 신청 때 남긴 값으로 한다. 신청 뒤 세율 상수가 바뀌었으면 지금 세율로 다시 계산한 값이 달라 경고하고
 * 두 값을 나란히 보인다. 경고는 색이 아니라 아이콘과 굵은 글로 가른다(상태에 유채색을 쓰지 않는다).
 */
function WithholdingSection({ payout }: { payout: AdminCreatorPayoutDetail }) {
  const changed = isWithholdingChanged(payout.withholding, payout.currentWithholding);

  return (
    <section className={SECTION_CLASS} aria-labelledby="withholding-heading">
      <h2 id="withholding-heading" className="text-lg font-semibold text-foreground">
        원천징수
      </h2>

      {changed && (
        <div role="note" className="flex items-start gap-2 rounded-lg border border-border p-3 text-sm text-foreground">
          <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
          <p className="break-keep">
            <span className="font-semibold">신청한 뒤 원천징수 세율이 바뀌었어요.</span> 이 건의 실지급액은 신청 때 계산한
            값이에요. 지금 세율로 다시 계산한 값과 비교해 보고 이체 전에 처리 방법을 확인해주세요.
          </p>
        </div>
      )}

      <div className={changed ? "grid gap-x-6 gap-y-4 text-sm @xl:grid-cols-2" : "text-sm"}>
        <WithholdingList title={changed ? "신청 때 (이체 기준)" : undefined} withholding={payout.withholding} />
        {changed && <WithholdingList title="지금 세율로 다시 계산" withholding={payout.currentWithholding} />}
      </div>
    </section>
  );
}

function WithholdingList({ title, withholding }: { title?: string; withholding: AdminCreatorPayoutWithholding }) {
  const rows: { label: string; value: string }[] = [
    { label: `소득세 (${formatRateBps(withholding.incomeTaxRateBps)})`, value: formatKrw(withholding.incomeTaxKrw) },
    { label: "지방소득세 (소득세의 10%)", value: formatKrw(withholding.localTaxKrw) },
    { label: "실지급액", value: formatKrw(withholding.netAmountKrw) },
  ];
  return (
    <div className="flex flex-col gap-2">
      {title && <p className="font-medium text-foreground">{title}</p>}
      <dl className="flex flex-col gap-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-4">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd className="text-foreground tabular-nums">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** 처리 기록. 있는 값만 보인다 — 보류한 뒤 이체한 건은 보류 기록과 이체 기록이 함께 남는다. */
function HistorySection({ payout }: { payout: AdminCreatorPayoutDetail }) {
  const hasHistory = payout.heldAt || payout.paidAt || payout.returnedAt;
  if (!hasHistory) return null;

  return (
    <section className={SECTION_CLASS} aria-labelledby="history-heading">
      <h2 id="history-heading" className="text-lg font-semibold text-foreground">
        처리 기록
      </h2>
      <dl className="grid gap-x-6 gap-y-3 text-sm @xl:grid-cols-2">
        {payout.heldAt && (
          <>
            <Field label="보류일시">{formatDateTime(payout.heldAt)}</Field>
            <Field label="보류 사유 (운영자만 봄)" wide>
              <span className="whitespace-pre-wrap">{payout.holdReason || "-"}</span>
            </Field>
          </>
        )}
        {payout.paidAt && (
          <>
            <Field label="이체일">{payout.transferredOn ?? "-"}</Field>
            <Field label="기록일시">{formatDateTime(payout.paidAt)}</Field>
            <Field label="메모 (운영자만 봄)" wide>
              <span className="whitespace-pre-wrap">{payout.adminMemo || "-"}</span>
            </Field>
          </>
        )}
        {payout.returnedAt && (
          <>
            <Field label="반려일시">{formatDateTime(payout.returnedAt)}</Field>
            <Field label="반려 사유 (신청자에게 보임)" wide>
              <span className="whitespace-pre-wrap">{payout.returnReason || "-"}</span>
            </Field>
          </>
        )}
      </dl>
    </section>
  );
}

function Field({ label, wide = false, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={wide ? "flex flex-col gap-0.5 @xl:col-span-2" : "flex flex-col gap-0.5"}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-keep text-foreground tabular-nums wrap-anywhere">{children}</dd>
    </div>
  );
}
