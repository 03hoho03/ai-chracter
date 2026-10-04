import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import {
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useCommentReportListQuery,
  type CommentReportList,
  type ReportStatusFilter,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { reportListEmpty } from "./reportListEmpty";

type CommentReportsTableProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

type CommentReportListItem = CommentReportList["items"][number];

const COLUMNS: readonly DataListColumn<CommentReportListItem>[] = [
  { id: "reason", header: "신고 사유", isPrimary: true, cell: (item) => `${REPORT_REASON_LABELS[item.reasonCategory]} 신고` },
  {
    id: "content",
    header: "작품",
    cell: (item) => (
      <span className="text-muted-foreground">
        {CONTENT_TYPE_LABELS[item.contentType]} · {item.contentName || "(이름 없음)"}
      </span>
    ),
  },
  { id: "created", header: "신고일시", cell: (item) => formatDateTime(item.createdAt) },
  { id: "evidence", header: "원문 증거", cell: (item) => <EvidenceState isAvailable={item.evidenceAvailable} /> },
  { id: "status", header: "처리상태", cell: (item) => REPORT_STATUS_LABELS[item.status] },
];

/** 링크에 `target`을 반드시 실어야 한다 — 빠지면 상세 라우트가 기본값인 작품 신고로 열려 이 id로 작품 신고 상세를 부른다. */
export function CommentReportsTable({ page, status, onPageChange, onReset }: CommentReportsTableProps) {
  const query = useCommentReportListQuery({ page, status });

  return (
    <QueryState
      query={query}
      errorMessage="댓글 신고를 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={reportListEmpty({ noun: "댓글 신고", status, onReset })}
    >
      {(data) => (
        <>
          <DataList
            caption="댓글 신고 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link to="/reports/$reportId" params={{ reportId: item.id }} search={{ target: "comment" }} {...props} />
            )}
            card={{
              title: (item) => `${REPORT_REASON_LABELS[item.reasonCategory]} 신고`,
              meta: (item) => (
                <>
                  <span className="wrap-anywhere">
                    {CONTENT_TYPE_LABELS[item.contentType]} · {item.contentName || "(이름 없음)"}
                  </span>
                  <span aria-hidden>·</span>
                  <EvidenceState isAvailable={item.evidenceAvailable} />
                  <span aria-hidden>·</span>
                  <span className="font-medium text-foreground">{REPORT_STATUS_LABELS[item.status]}</span>
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

function EvidenceState({ isAvailable }: { isAvailable: boolean }) {
  return <span className="text-muted-foreground">{isAvailable ? "증거 보관 중" : "증거 만료·파기"}</span>;
}
