import { useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";

import {
  APPEAL_STATUS_LABELS,
  APPEAL_TARGET_KIND_LABELS,
  useAppealListQuery,
  type AdminAppealListResponse,
  type AppealStatusFilter,
} from "@/entities/appeal";
import { AppealResolvePanel } from "@/features/resolve-appeal";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

const STATUS_OPTIONS: { value: AppealStatusFilter; label: string }[] = [
  { value: "pending", label: APPEAL_STATUS_LABELS.pending },
  { value: "resolved", label: APPEAL_STATUS_LABELS.resolved },
];

type AppealsListPageProps = {
  page: number;
  status?: AppealStatusFilter;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: AppealStatusFilter) => void;
}

export function AppealsListPage({ page, status, onPageChange, onStatusChange }: AppealsListPageProps) {
  useDocumentTitle("이의제기 검토");
  return (
    <PageContainer>
      <PageHeader title="이의제기 검토" />

      <FilterBar
        fields={[
          selectFilter({
            id: "status",
            label: "처리상태",
            options: STATUS_OPTIONS,
            value: status,
            defaultLabel: "전체",
            onChange: onStatusChange,
          }),
        ]}
        onReset={() => onStatusChange(undefined)}
      />

      <AppealsTable page={page} status={status} onPageChange={onPageChange} onReset={() => onStatusChange(undefined)} />
    </PageContainer>
  );
}

type AppealListItem = AdminAppealListResponse["items"][number];

/** 대상 종류만으로는 행끼리 구별되지 않아 접수일시를 접근 이름에 더한다(화면에는 옆 칸·끝에 이미 보인다). */
function AppealTitle({ item }: { item: AppealListItem }) {
  return (
    <>
      {APPEAL_TARGET_KIND_LABELS[item.targetKind]}
      <span className="sr-only">, {formatDateTime(item.createdAt)} 접수</span>
    </>
  );
}

const COLUMNS: readonly DataListColumn<AppealListItem>[] = [
  { id: "kind", header: "대상 종류", isPrimary: true, cell: (item) => <AppealTitle item={item} /> },
  { id: "created", header: "접수일시", cell: (item) => formatDateTime(item.createdAt) },
  { id: "status", header: "처리상태", cell: (item) => APPEAL_STATUS_LABELS[item.status] },
];

type AppealsTableProps = {
  page: number;
  status?: AppealStatusFilter;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. 선택된 항목의
 * 상세도 목록 응답에서 바로 찾으므로(별도 detail API가 없다) 여기 함께 둔다. */
function AppealsTable({ page, status, onPageChange, onReset }: AppealsTableProps) {
  const appealListQuery = useAppealListQuery({ page, status });
  const [selectedAppealId, setSelectedAppealId] = useState<string>();
  // 고른 이의제기 상세가 목록 아래에 열린다 — 좁은 화면에서는 화면 밖이라 고른 순간 그 자리로 포커스를 옮긴다. 상세는
  // 페이지·필터를 바꿔 다시 불러올 때도 다시 마운트되므로, 마운트가 아니라 고르는 클릭이 남긴 표시로 옮길지 정한다
  // (안 그러면 "다음"을 누를 때마다 포커스·스크롤을 상세가 가져간다).
  const shouldFocusDetailRef = useRef(false);
  const focusDetailIfJustSelected = (element: HTMLElement | null) => {
    if (!element || !shouldFocusDetailRef.current) return;
    shouldFocusDetailRef.current = false;
    element.focus();
  };

  return (
    <QueryState
      query={appealListQuery}
      errorMessage="이의제기 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={
        status === undefined
          ? { title: "검토할 이의제기가 없어요. 이용제한·숨김을 받은 작가가 신청하면 여기에 쌓여요." }
          : {
              title: "이 상태의 이의제기가 없어요.",
              action: (
                <Button type="button" variant="outline" size="sm" onClick={onReset}>
                  필터 초기화
                </Button>
              ),
            }
      }
    >
      {(data) => {
        const selectedAppeal = data.items.find((item) => item.id === selectedAppealId);

        return (
          <>
            {/* 상세 라우트가 없어 행 대상은 링크가 아니라 고르는 버튼이다. 고른 행은 `aria-current` 와 체크 글리프로 알린다. */}
            <DataList
              caption="이의제기 목록"
              rows={data.items}
              getRowKey={(item) => item.id}
              columns={COLUMNS}
              isRowSelected={(item) => item.id === selectedAppealId}
              renderRowTarget={(item, props) => (
                <button
                  type="button"
                  aria-current={item.id === selectedAppealId || undefined}
                  onClick={() => {
                    // 이미 고른 행을 다시 누르면 상세가 다시 그려지지 않아 표시가 남는다 — 새로 고를 때만 단다.
                    shouldFocusDetailRef.current = item.id !== selectedAppealId;
                    setSelectedAppealId(item.id);
                  }}
                  {...props}
                />
              )}
              card={{
                title: (item) => <AppealTitle item={item} />,
                meta: (item) => <span className="font-medium text-foreground">{APPEAL_STATUS_LABELS[item.status]}</span>,
                trailing: (item) => formatDateTime(item.createdAt),
              }}
            />

            <Pagination
              page={data.page}
              totalPages={data.totalPages}
              totalCount={data.totalCount}
              onPageChange={onPageChange}
            />

            {selectedAppeal && (
              <section
                key={selectedAppeal.id}
                ref={focusDetailIfJustSelected}
                tabIndex={-1}
                aria-label="고른 이의제기"
                className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 outline-none sm:p-6"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
                    {APPEAL_STATUS_LABELS[selectedAppeal.status]}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {formatDateTime(selectedAppeal.createdAt)} 접수
                  </span>
                </div>

                <div className="flex flex-col gap-1">
                  <h2 className="text-sm font-medium text-foreground">신청 사유</h2>
                  <p className="whitespace-pre-wrap text-sm text-muted-foreground wrap-anywhere">{selectedAppeal.reasonText}</p>
                </div>

                <AppealResolvePanel appeal={selectedAppeal} />
              </section>
            )}
          </>
        );
      }}
    </QueryState>
  );
}
