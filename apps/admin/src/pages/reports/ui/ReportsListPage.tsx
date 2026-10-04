import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useNavigate } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import {
  isReportTarget,
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  REPORT_TARGET_LABELS,
  REPORT_TARGETS,
  useReportListQuery,
  type ReportStatusFilter,
  type ReportTarget,
} from "@/entities/report";
import { Pagination } from "@/shared/ui/Pagination";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { PageContainer } from "@/shared/ui/PageContainer";

import { ChatMessageReportsTable } from "./ChatMessageReportsTable";
import { CommentReportsTable } from "./CommentReportsTable";

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
  target: ReportTarget;
  onTargetChange: (target: ReportTarget) => void;
}

export function ReportsListPage({ page, status, target, onPageChange, onStatusChange, onTargetChange }: ReportsListPageProps) {
  return (
    <PageContainer>
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

      {/* 탭·가드를 대상 목록 하나에서 도출한다 — 손으로 적은 가드에서 값을 빠뜨리면 그 탭은 눌러도
       * 아무 일이 없다(타입 에러도 나지 않는다). */}
      <ToggleGroup type="single" variant="outline" value={target} aria-label="신고 대상" className="max-w-full flex-wrap"
        onValueChange={(value) => { if (isReportTarget(value)) onTargetChange(value); }}>
        {REPORT_TARGETS.map((value) => (
          <ToggleGroupItem key={value} value={value} className="h-auto min-h-9 min-w-0 max-w-full whitespace-normal wrap-anywhere">
            {REPORT_TARGET_LABELS[value]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <TargetReportsTable target={target} page={page} status={status} onPageChange={onPageChange} />
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

/** `SelectItem`의 value가 `string`이라 좁힘이 필요하다. `as` 대신 술어를 쓴다.
 * 목록에 섞여 있는 `"all"`은 "필터 없음"이라 여기서 자연히 걸러진다. AppealsListPage 동형. */
function isReportStatus(value: string): value is ReportStatusFilter {
  return STATUS_FILTER_OPTIONS.some((option) => option.value !== "all" && option.value === value);
}

function assertNever(value: never): never {
  throw new Error(`Unexpected: ${String(value)}`);
}
