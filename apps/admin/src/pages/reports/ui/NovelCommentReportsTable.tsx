import { Link } from "@tanstack/react-router";

import {
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useNovelCommentReportListQuery,
  type NovelCommentReportList,
  type ReportStatusFilter,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { reportListEmpty } from "./reportListEmpty";

type NovelCommentReportsTableProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

type NovelCommentReportListItem = NovelCommentReportList["items"][number];

/** 목록 응답에는 노벨 제목이 없다 — 댓글이 지금 남아 있는지만 보이고, 무엇에 단 댓글인지는 상세에서 본다. */
function commentState(item: NovelCommentReportListItem) {
  return item.commentId === null ? "댓글 사라짐" : "댓글 남아 있음";
}

const COLUMNS: readonly DataListColumn<NovelCommentReportListItem>[] = [
  { id: "reason", header: "신고 사유", isPrimary: true, cell: (item) => `${REPORT_REASON_LABELS[item.reasonCategory]} 신고` },
  { id: "comment", header: "대상 댓글", cell: (item) => <span className="text-muted-foreground">{commentState(item)}</span> },
  { id: "created", header: "신고일시", cell: (item) => formatDateTime(item.createdAt) },
  { id: "evidence", header: "원문 증거", cell: (item) => <EvidenceState isAvailable={item.evidenceAvailable} /> },
  { id: "status", header: "처리상태", cell: (item) => REPORT_STATUS_LABELS[item.status] },
];

/** 링크에 `target`을 반드시 실어야 한다 — 빠지면 상세 라우트가 기본값인 작품 신고로 열려 이 id로 작품 신고 상세를 부른다. */
export function NovelCommentReportsTable({ page, status, onPageChange, onReset }: NovelCommentReportsTableProps) {
  const query = useNovelCommentReportListQuery({ page, status });

  return (
    <QueryState
      query={query}
      errorMessage="노벨 댓글 신고를 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={reportListEmpty({ noun: "노벨 댓글 신고", status, onReset })}
    >
      {(data) => (
        <>
          <DataList
            caption="노벨 댓글 신고 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link to="/reports/$reportId" params={{ reportId: item.id }} search={{ target: "novel-comment" }} {...props} />
            )}
            card={{
              title: (item) => `${REPORT_REASON_LABELS[item.reasonCategory]} 신고`,
              meta: (item) => (
                <>
                  <span>{commentState(item)}</span>
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
