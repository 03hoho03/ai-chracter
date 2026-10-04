import { Link } from "@tanstack/react-router";

import {
  CHAT_MESSAGE_REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useChatMessageReportListQuery,
  type ChatMessageReportList,
  type ReportStatusFilter,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { reportListEmpty } from "./reportListEmpty";

type ChatMessageReportsTableProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

type ChatMessageReportListItem = ChatMessageReportList["items"][number];

/** 원래 응답이 대화에서 지워졌어도 신고에 붙은 사본은 증거로 남는다 — 사본 상태 곁에 함께 알린다. */
function DeletedNote({ item }: { item: ChatMessageReportListItem }) {
  if (item.chatMessageId !== null) return null;
  return <span className="text-muted-foreground">원래 응답은 대화에서 지워졌어요</span>;
}

const COLUMNS: readonly DataListColumn<ChatMessageReportListItem>[] = [
  { id: "reason", header: "신고 사유", isPrimary: true, cell: (item) => `${CHAT_MESSAGE_REPORT_REASON_LABELS[item.reason]} 신고` },
  { id: "created", header: "신고일시", cell: (item) => formatDateTime(item.createdAt) },
  {
    id: "evidence",
    header: "응답 사본",
    cell: (item) => (
      <div className="flex flex-col">
        <span className="text-muted-foreground">{item.evidenceAvailable ? "보관 중" : "만료·파기"}</span>
        <span className="text-xs">
          <DeletedNote item={item} />
        </span>
      </div>
    ),
  },
  { id: "status", header: "처리상태", cell: (item) => REPORT_STATUS_LABELS[item.status] },
];

/** 댓글 신고 표와 같은 모양이다. 링크에 `target`을 반드시 실어야 한다 — 빠지면 상세 라우트가 기본값인
 * 작품 신고로 열려 이 id로 작품 신고 상세를 부른다. 작품명 같은 맥락은 목록 응답에 없다(방이 지워지면
 * 찾을 수 없어 BE가 싣지 않는다). */
export function ChatMessageReportsTable({ page, status, onPageChange, onReset }: ChatMessageReportsTableProps) {
  const query = useChatMessageReportListQuery({ page, status });

  return (
    <QueryState
      query={query}
      errorMessage="채팅 응답 신고를 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={reportListEmpty({ noun: "채팅 응답 신고", status, onReset })}
    >
      {(data) => (
        <>
          <DataList
            caption="채팅 응답 신고 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link to="/reports/$reportId" params={{ reportId: item.id }} search={{ target: "chat-message" }} {...props} />
            )}
            card={{
              title: (item) => `${CHAT_MESSAGE_REPORT_REASON_LABELS[item.reason]} 신고`,
              meta: (item) => (
                <>
                  <span>{item.evidenceAvailable ? "응답 사본 보관 중" : "응답 사본 만료·파기"}</span>
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{REPORT_STATUS_LABELS[item.status]}</span>
                  {item.chatMessageId === null && (
                    <>
                      <span aria-hidden>·</span>
                      <DeletedNote item={item} />
                    </>
                  )}
                </>
              ),
              trailing: (item) => formatDateTime(item.createdAt),
            }}
          />
          <Pagination page={data.page} totalPages={data.totalPages} totalCount={data.totalCount} onPageChange={onPageChange} />
        </>
      )}
    </QueryState>
  );
}
