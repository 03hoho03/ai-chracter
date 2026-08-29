import { Button } from "@ai-character-chat/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";

import {
  CONTENT_TYPE_LABELS,
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useReportListQuery,
  type ReportStatusFilter,
} from "@/entities/report";

const STATUS_FILTER_OPTIONS: { value: "all" | ReportStatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "pending", label: REPORT_STATUS_LABELS.pending },
  { value: "resolved", label: REPORT_STATUS_LABELS.resolved },
  { value: "rejected", label: REPORT_STATUS_LABELS.rejected },
];

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다(TS-03).
 * 목록에 섞여 있는 `"all"`은 "필터 없음"이라 여기서 자연히 걸러진다. AppealsListPage 동형. */
function isReportStatus(value: string): value is ReportStatusFilter {
  return STATUS_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}

const CREATED_AT_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

type ReportsListPageProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onStatusChange: (status?: ReportStatusFilter) => void;
}

export function ReportsListPage({ page, status, onPageChange, onStatusChange }: ReportsListPageProps) {
  const reportListQuery = useReportListQuery({ page, status });
  const navigate = useNavigate();

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

      {reportListQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {reportListQuery.isError && (
        <p className="text-sm text-destructive-text">신고 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {reportListQuery.data && reportListQuery.data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">접수된 신고가 없어요.</p>
      )}

      {reportListQuery.data && reportListQuery.data.items.length > 0 && (
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
                    <TableCell>{CREATED_AT_FORMATTER.format(new Date(item.createdAt))}</TableCell>
                    <TableCell>{REPORT_STATUS_LABELS[item.status]}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              이전
            </Button>
            <span className="text-sm text-muted-foreground">
              {reportListQuery.data.page} / {reportListQuery.data.totalPages} 페이지 (총 {reportListQuery.data.totalCount}건)
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={page >= reportListQuery.data.totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              다음
            </Button>
          </div>
        </>
      )}
    </main>
  );
}
