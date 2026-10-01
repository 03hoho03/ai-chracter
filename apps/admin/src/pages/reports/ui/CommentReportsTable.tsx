import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import { REPORT_REASON_LABELS, REPORT_STATUS_LABELS, useCommentReportListQuery, type ReportStatusFilter } from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { Pagination } from "@/shared/ui/Pagination";

type CommentReportsTableProps = { page: number; status?: ReportStatusFilter; onPageChange: (page: number) => void };

export function CommentReportsTable({ page, status, onPageChange }: CommentReportsTableProps) {
  const query = useCommentReportListQuery({ page, status });
  if (query.isPending) return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  if (query.isError) return <p role="alert" className="text-sm text-destructive-text">댓글 신고를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  if (query.data.items.length === 0) return <p className="text-sm text-muted-foreground">접수된 댓글 신고가 없어요.</p>;
  return <>
    <div className="overflow-hidden rounded-xl border border-border">
      <Table>
        <TableHeader><TableRow>
          <TableHead>신고 사유·작품</TableHead><TableHead>신고일시</TableHead><TableHead>원문 증거</TableHead><TableHead>처리상태</TableHead>
        </TableRow></TableHeader>
        <TableBody>{query.data.items.map((item) => <TableRow key={item.id}>
          <TableCell><Link to="/reports/$reportId" params={{ reportId: item.id }} search={{ target: "comment" }}
            className="font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring">
            {REPORT_REASON_LABELS[item.reasonCategory]} 신고 보기
          </Link><p className="mt-1 text-xs text-muted-foreground">{CONTENT_TYPE_LABELS[item.contentType]} · {item.contentName || "(이름 없음)"}</p></TableCell>
          <TableCell>{formatDateTime(item.createdAt)}</TableCell>
          <TableCell className="text-muted-foreground">{item.evidenceAvailable ? "보관 중" : "만료·파기"}</TableCell>
          <TableCell>{REPORT_STATUS_LABELS[item.status]}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>
    <Pagination page={query.data.page} totalPages={query.data.totalPages} totalCount={query.data.totalCount} onPageChange={onPageChange} />
  </>;
}
