import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link } from "@tanstack/react-router";

import {
  CHAT_MESSAGE_REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useChatMessageReportListQuery,
  type ReportStatusFilter,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { Pagination } from "@/shared/ui/Pagination";

type ChatMessageReportsTableProps = { page: number; status?: ReportStatusFilter; onPageChange: (page: number) => void };

/** 댓글 신고 표와 같은 모양이다. 링크에 `target`을 반드시 실어야 한다 — 빠지면 상세 라우트가 기본값인
 * 작품 신고로 열려 이 id로 작품 신고 상세를 부른다. 작품명 같은 맥락은 목록 응답에 없다(방이 지워지면
 * 찾을 수 없어 BE가 싣지 않는다). */
export function ChatMessageReportsTable({ page, status, onPageChange }: ChatMessageReportsTableProps) {
  const query = useChatMessageReportListQuery({ page, status });
  if (query.isPending) return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  if (query.isError) return <p role="alert" className="text-sm text-destructive-text">채팅 응답 신고를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  if (query.data.items.length === 0) return <p className="text-sm text-muted-foreground">접수된 채팅 응답 신고가 없어요.</p>;
  return <>
    <div className="overflow-hidden rounded-xl border border-border">
      <Table>
        <TableHeader><TableRow>
          <TableHead>신고 사유</TableHead><TableHead>신고일시</TableHead><TableHead>응답 사본</TableHead><TableHead>처리상태</TableHead>
        </TableRow></TableHeader>
        <TableBody>{query.data.items.map((item) => <TableRow key={item.id}>
          <TableCell><Link to="/reports/$reportId" params={{ reportId: item.id }} search={{ target: "chat-message" }}
            className="font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring">
            {CHAT_MESSAGE_REPORT_REASON_LABELS[item.reason]} 신고 보기
          </Link>{item.chatMessageId === null && <p className="mt-1 text-xs text-muted-foreground">원래 응답은 대화에서 지워졌어요</p>}</TableCell>
          <TableCell>{formatDateTime(item.createdAt)}</TableCell>
          <TableCell className="text-muted-foreground">{item.evidenceAvailable ? "보관 중" : "만료·파기"}</TableCell>
          <TableCell>{REPORT_STATUS_LABELS[item.status]}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>
    <Pagination page={query.data.page} totalPages={query.data.totalPages} totalCount={query.data.totalCount} onPageChange={onPageChange} />
  </>;
}
