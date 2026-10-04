import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import {
  isReportTarget,
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  REPORT_TARGET_LABELS,
  REPORT_TARGETS,
  useReportListQuery,
  type AdminReportListResponse,
  type ReportStatusFilter,
  type ReportTarget,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { ChatMessageReportsTable } from "./ChatMessageReportsTable";
import { CommentReportsTable } from "./CommentReportsTable";
import { reportListEmpty } from "./reportListEmpty";

const STATUS_OPTIONS: { value: ReportStatusFilter; label: string }[] = [
  { value: "pending", label: REPORT_STATUS_LABELS.pending },
  { value: "resolved", label: REPORT_STATUS_LABELS.resolved },
  { value: "rejected", label: REPORT_STATUS_LABELS.rejected },
];

type ReportsListPageProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: ReportStatusFilter) => void;
  target: ReportTarget;
  onTargetChange: (target: ReportTarget) => void;
}

export function ReportsListPage({ page, status, target, onPageChange, onStatusChange, onTargetChange }: ReportsListPageProps) {
  return (
    <PageContainer>
      <PageHeader title="신고 관리" />

      {/* 대상 전환은 걸러 내는 필터가 아니라 표 자체를 바꾸는 축이라 필터 바 밖에 둔다 — 필터 수·해제 칩에 섞이지 않는다.
       * 탭·가드를 대상 목록 하나에서 도출한다 — 손으로 적은 가드에서 값을 빠뜨리면 그 탭은 눌러도
       * 아무 일이 없다(타입 에러도 나지 않는다). */}
      <ToggleGroup type="single" variant="outline" value={target} aria-label="신고 대상" className="max-w-full flex-wrap"
        onValueChange={(value) => { if (isReportTarget(value)) onTargetChange(value); }}>
        {REPORT_TARGETS.map((value) => (
          <ToggleGroupItem key={value} value={value} className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere">
            {REPORT_TARGET_LABELS[value]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

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

      <TargetReportsTable
        target={target}
        page={page}
        status={status}
        onPageChange={onPageChange}
        onReset={() => onStatusChange(undefined)}
      />
    </PageContainer>
  );
}

/** 대상마다 표가 다르다. 두 갈래 삼항이면 새 대상이 작품 표로 조용히 떨어지므로 대상을 하나씩
 * 명시하고, `assertNever`로 대상이 늘었을 때 여기서 컴파일이 깨지게 한다. */
function TargetReportsTable({ target, ...tableProps }: ReportsTableProps & { target: ReportTarget }) {
  switch (target) {
    case "content":
      return <ReportsTable {...tableProps} />;
    case "comment":
      return <CommentReportsTable {...tableProps} />;
    case "chat-message":
      return <ChatMessageReportsTable {...tableProps} />;
    default:
      return assertNever(target);
  }
}

type ReportsTableProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  /** 빈 결과에서 처리상태 필터를 푼다. */
  onReset: () => void;
};

type ReportListItem = AdminReportListResponse["items"][number];

const COLUMNS: readonly DataListColumn<ReportListItem>[] = [
  { id: "reason", header: "신고 사유", cell: (item) => REPORT_REASON_LABELS[item.reasonCategory] },
  {
    id: "content",
    header: "대상 콘텐츠",
    isPrimary: true,
    cell: (item) => (
      <>
        <span className="text-muted-foreground">{CONTENT_TYPE_LABELS[item.contentType]}</span> {item.contentName || "(이름 없음)"}
      </>
    ),
  },
  { id: "created", header: "신고일시", cell: (item) => formatDateTime(item.createdAt) },
  { id: "status", header: "처리상태", cell: (item) => REPORT_STATUS_LABELS[item.status] },
];

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ReportsTable({ page, status, onPageChange, onReset }: ReportsTableProps) {
  const reportListQuery = useReportListQuery({ page, status });

  return (
    <QueryState
      query={reportListQuery}
      errorMessage="신고 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={reportListEmpty({ noun: "신고", status, onReset })}
    >
      {(data) => (
        <>
          <DataList
            caption="작품 신고 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link to="/reports/$reportId" params={{ reportId: item.id }} {...props} />
            )}
            card={{
              title: (item) => item.contentName || "(이름 없음)",
              meta: (item) => (
                <>
                  <span>{CONTENT_TYPE_LABELS[item.contentType]}</span>
                  <span aria-hidden>·</span>
                  <span>{REPORT_REASON_LABELS[item.reasonCategory]}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{REPORT_STATUS_LABELS[item.status]}</span>
                </>
              ),
              trailing: (item) => formatDateTime(item.createdAt),
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

function assertNever(value: never): never {
  throw new Error(`Unexpected: ${String(value)}`);
}
