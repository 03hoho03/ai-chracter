import { Link } from "@tanstack/react-router";

import {
  REPORT_REASON_LABELS,
  REPORT_STATUS_LABELS,
  useNovelReportListQuery,
  type NovelReportListItem,
  type ReportStatusFilter,
} from "@/entities/report";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { reportListEmpty } from "./reportListEmpty";

type NovelReportsTableProps = {
  page: number;
  status?: ReportStatusFilter;
  onPageChange: (page: number) => void;
  onReset: () => void;
};

/** 소설이 지워지면 노벨 id 가 비고 무엇이 신고됐는지는 증거 사본의 제목으로만 읽는다 — 그 사본도 파기되면 제목이 빈다. */
function reportedTitle(item: NovelReportListItem) {
  const title = item.evidenceTitle ?? "(제목 사본 파기됨)";
  return item.novelId === null ? `${title} (지워진 노벨)` : title;
}

function reportedScope(item: NovelReportListItem) {
  return item.chapterOrdinal === null ? "소설 전체" : `${item.chapterOrdinal}화`;
}

const COLUMNS: readonly DataListColumn<NovelReportListItem>[] = [
  { id: "reason", header: "신고 사유", isPrimary: true, cell: (item) => `${REPORT_REASON_LABELS[item.reasonCategory]} 신고` },
  {
    id: "novel",
    header: "노벨",
    cell: (item) => (
      <span className="text-muted-foreground">
        {reportedTitle(item)} · {reportedScope(item)}
      </span>
    ),
  },
  { id: "created", header: "신고일시", cell: (item) => formatDateTime(item.createdAt) },
  { id: "evidence", header: "증거 사본", cell: (item) => <EvidenceState isAvailable={item.evidenceAvailable} /> },
  { id: "status", header: "처리상태", cell: (item) => REPORT_STATUS_LABELS[item.status] },
];

/** 링크에 `target`을 반드시 실어야 한다 — 빠지면 상세 라우트가 기본값인 작품 신고로 열려 이 id로 작품 신고 상세를 부른다. */
export function NovelReportsTable({ page, status, onPageChange, onReset }: NovelReportsTableProps) {
  const query = useNovelReportListQuery({ page, status });

  return (
    <QueryState
      query={query}
      errorMessage="노벨 신고를 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={reportListEmpty({ noun: "노벨 신고", status, onReset })}
    >
      {(data) => (
        <>
          <DataList
            caption="노벨 신고 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => (
              <Link to="/reports/$reportId" params={{ reportId: item.id }} search={{ target: "novel" }} {...props} />
            )}
            card={{
              title: (item) => `${REPORT_REASON_LABELS[item.reasonCategory]} 신고`,
              meta: (item) => (
                <>
                  <span className="wrap-anywhere">
                    {reportedTitle(item)} · {reportedScope(item)}
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
  return <span className="text-muted-foreground">{isAvailable ? "사본 보관 중" : "사본 만료·파기"}</span>;
}
