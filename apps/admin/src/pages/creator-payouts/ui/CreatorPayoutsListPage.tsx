import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import {
  CREATOR_PAYOUT_STATUS_LABELS,
  formatKrw,
  useCreatorPayoutListQuery,
  WithdrawnBadge,
  type AdminCreatorPayoutItem,
  type CreatorPayoutStatus,
} from "@/entities/creator-payout";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

/** 서버는 상태 하나만 받고 기본이 처리 중이다 — 필터의 기본 항목이 곧 처리 중이라, 나머지 셋만 고르는 값으로 둔다. */
export type NonDefaultPayoutStatus = Exclude<CreatorPayoutStatus, "requested">;

const STATUS_OPTIONS: { value: NonDefaultPayoutStatus; label: string }[] = [
  { value: "held", label: CREATOR_PAYOUT_STATUS_LABELS.held },
  { value: "paid", label: CREATOR_PAYOUT_STATUS_LABELS.paid },
  { value: "returned", label: CREATOR_PAYOUT_STATUS_LABELS.returned },
];

const PAGE_TITLE = "지급 처리";

type CreatorPayoutsListPageProps = {
  page: number;
  status?: NonDefaultPayoutStatus;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: NonDefaultPayoutStatus) => void;
};

export function CreatorPayoutsListPage({ page, status, onPageChange, onStatusChange }: CreatorPayoutsListPageProps) {
  useDocumentTitle(PAGE_TITLE);
  return (
    <PageContainer>
      <PageHeader title={PAGE_TITLE} />

      <FilterBar
        fields={[
          selectFilter({
            id: "status",
            label: "처리상태",
            options: STATUS_OPTIONS,
            value: status,
            defaultLabel: CREATOR_PAYOUT_STATUS_LABELS.requested,
            onChange: onStatusChange,
          }),
        ]}
        onReset={() => onStatusChange(undefined)}
      />

      <PayoutsList
        page={page}
        status={status ?? "requested"}
        onPageChange={onPageChange}
        onReset={() => onStatusChange(undefined)}
      />
    </PageContainer>
  );
}

/** 탈퇴 회원은 서버가 닉네임을 파기해 `null` 로 보낸다. */
function PayeeTitle({ item }: { item: AdminCreatorPayoutItem }) {
  return (
    <>
      {item.nickname ?? "탈퇴한 회원"}
      {/* 닉네임만으로는 같은 사람의 여러 지급이 구별되지 않아 신청일시를 접근 이름에 더한다. */}
      <span className="sr-only">, {formatDateTime(item.requestedAt)} 신청</span>
    </>
  );
}

/** 상태 옆에 탈퇴 표식을 둔다 — 탈퇴한 회원의 건은 처리 방법이 달라진다(반려 대신 보류·수취 정보 교체). */
function PayoutStatus({ item }: { item: AdminCreatorPayoutItem }) {
  return (
    <span className="inline-flex items-center gap-2">
      {CREATOR_PAYOUT_STATUS_LABELS[item.status]}
      {item.withdrawn && <WithdrawnBadge />}
    </span>
  );
}

const COLUMNS: readonly DataListColumn<AdminCreatorPayoutItem>[] = [
  { id: "payee", header: "신청자", isPrimary: true, cell: (item) => <PayeeTitle item={item} /> },
  {
    id: "amount",
    header: "신청액",
    cell: (item) => <span className="tabular-nums">{formatKrw(item.amountKrw)}</span>,
  },
  {
    id: "net",
    header: "실지급액",
    cell: (item) => <span className="tabular-nums">{formatKrw(item.netAmountKrw)}</span>,
  },
  { id: "status", header: "상태", cell: (item) => <PayoutStatus item={item} /> },
  { id: "requested", header: "신청일시", cell: (item) => formatDateTime(item.requestedAt) },
];

const EMPTY_TITLES: Record<CreatorPayoutStatus, string> = {
  requested: "처리할 지급 신청이 없어요. 크리에이터가 지급을 신청하면 여기에 오래된 순으로 쌓여요.",
  held: "보류된 지급이 없어요.",
  paid: "지급을 마친 건이 없어요.",
  returned: "반려된 지급이 없어요.",
};

type PayoutsListProps = {
  page: number;
  status: CreatorPayoutStatus;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

/** 헤더(제목·필터)는 로딩·오류에도 남아야 해서 쿼리에 기대는 본문만 갈라낸다. */
function PayoutsList({ page, status, onPageChange, onReset }: PayoutsListProps) {
  const listQuery = useCreatorPayoutListQuery({ page, status });

  return (
    <QueryState
      query={listQuery}
      errorMessage="지급 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={
        status === "requested"
          ? { title: EMPTY_TITLES.requested }
          : {
              title: EMPTY_TITLES[status],
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  처리 중 보기
                </Button>
              ),
            }
      }
    >
      {(data) => (
        <>
          <DataList
            caption="지급 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link to="/creator-payouts/$payoutId" params={{ payoutId: item.id }} {...props} />
            )}
            card={{
              title: (item) => <PayeeTitle item={item} />,
              meta: (item) => (
                <>
                  <span className="tabular-nums">실지급 {formatKrw(item.netAmountKrw)}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">
                    <PayoutStatus item={item} />
                  </span>
                </>
              ),
              trailing: (item) => formatDateTime(item.requestedAt),
            }}
          />

          <Pagination
            page={data.page}
            totalPages={data.totalPages}
            totalCount={data.totalCount}
            onPageChange={onPageChange}
          />
        </>
      )}
    </QueryState>
  );
}
