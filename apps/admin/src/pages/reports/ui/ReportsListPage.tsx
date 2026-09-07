import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import {
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useReportListQuery,
  type ReportStatusFilter,
} from "@/entities/report";
import { Pagination } from "@/shared/ui/Pagination";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

const STATUS_FILTER_OPTIONS: { value: "all" | ReportStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: REPORT_STATUS_LABELS.pending },
  { value: "resolved", label: REPORT_STATUS_LABELS.resolved },
  { value: "rejected", label: REPORT_STATUS_LABELS.rejected },
];

type ReportsListPageProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: ReportStatusFilter) => void;
}

export function ReportsListPage({ page, status, onPageChange, onStatusChange }: ReportsListPageProps) {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">신고 관리</h1>

        <Select
          value={status ?? "all"}
          onValueChange={(value) => onStatusChange(isReportStatus(value) ? value : undefined)}
        >
          <SelectTrigger size="sm" aria-label="처리상태 필터" className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_FILTER_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <ReportsTable page={page} status={status} onPageChange={onPageChange} />
    </main>
  );
}

type ReportsTableProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·필터)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function ReportsTable({ page, status, onPageChange }: ReportsTableProps) {
  const reportListQuery = useReportListQuery({ page, status });
  const navigate = useNavigate();

  if (reportListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (reportListQuery.isError) {
    return <p className="text-sm text-destructive-text">신고 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (reportListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">접수된 신고가 없어요.</p>;
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>신고 사유</TableHead>
              <TableHead>대상 콘텐츠</TableHead>
              <TableHead>신고일시</TableHead>
              <TableHead>처리상태</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reportListQuery.data.items.map((item) => (
              <TableRow
                key={item.id}
                tabIndex={0}
                role="button"
                className="cursor-pointer"
                onClick={() => void navigate({ to: "/reports/$reportId", params: { reportId: item.id } })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void navigate({ to: "/reports/$reportId", params: { reportId: item.id } });
                  }
                }}
              >
                <TableCell>{REPORT_REASON_LABELS[item.reasonCategory]}</TableCell>
                <TableCell>
                  <span className="text-muted-foreground">{CONTENT_TYPE_LABELS[item.contentType]}</span>{" "}
                  {item.contentName || "(이름 없음)"}
                </TableCell>
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
                <TableCell>{REPORT_STATUS_LABELS[item.status]}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={reportListQuery.data.page}
        totalPages={reportListQuery.data.totalPages}
        totalCount={reportListQuery.data.totalCount}
        onPageChange={onPageChange}
      />
    </>
  );
}

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03).
 * 목록에 섞여 있는 `"all"`은 "필터 없음"이라 여기서 자연히 걸러진다. AppealsListPage 동형. */
function isReportStatus(value: string): value is ReportStatusFilter {
  return STATUS_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}
