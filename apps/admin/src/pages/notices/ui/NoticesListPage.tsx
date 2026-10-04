import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import { useNoticeListQuery, type AdminNoticeListItem } from "@/entities/notice";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

type NoticesListPageProps = {
  page: number;
  onPageChange: (page: number) => void;
};

function NewNoticeButton() {
  return (
    <Button asChild size="sm">
      <Link to="/notices/$noticeId" params={{ noticeId: "new" }}>
        새 공지
      </Link>
    </Button>
  );
}

export function NoticesListPage({ page, onPageChange }: NoticesListPageProps) {
  useDocumentTitle("공지 관리");
  return (
    <PageContainer>
      <PageHeader title="공지 관리" actions={<NewNoticeButton />} />

      <NoticesList page={page} onPageChange={onPageChange} />
    </PageContainer>
  );
}

function PublishedBadge({ item }: { item: AdminNoticeListItem }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
      {item.published ? "게시" : "숨김"}
    </span>
  );
}

const COLUMNS: readonly DataListColumn<AdminNoticeListItem>[] = [
  { id: "title", header: "제목", isPrimary: true, cell: (item) => item.title },
  { id: "published", header: "상태", cell: (item) => <PublishedBadge item={item} /> },
  { id: "published-at", header: "게시일", cell: (item) => formatDateTime(item.publishedAt) },
  // BE 응답(`AdminNoticeListItem`, `apps/api/src/api/admin/notices.py`)에는 `updatedAt`이 없다 — `Notice.updated_at`이
  // onupdate=func.now() 컬럼이라 커밋 직후 재조회 없이 읽으면 그린렛 밖 재조회가 필요해 응답 스펙에서 뺐다(`_to_detail`
  // 주석). "수정일" 대신 실제로 있는 작성일을 쓴다.
  { id: "created", header: "작성일", cell: (item) => formatDateTime(item.createdAt) },
];

type NoticesListProps = {
  page: number;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·새 공지 버튼)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function NoticesList({ page, onPageChange }: NoticesListProps) {
  const noticeListQuery = useNoticeListQuery(page);

  return (
    <QueryState
      query={noticeListQuery}
      errorMessage="공지 목록을 불러오지 못했어요."
      isEmpty={(data) => data.items.length === 0}
      getPage={(data) => data}
      empty={{ title: "아직 공지가 없어요. \"새 공지\"로 첫 공지를 쓸 수 있어요." }}
    >
      {(data) => (
        <>
          <DataList
            caption="공지 목록"
            rows={data.items}
            getRowKey={(item) => item.id}
            columns={COLUMNS}
            renderRowTarget={(item, props) => <Link to="/notices/$noticeId" params={{ noticeId: item.id }} {...props} />}
            card={{
              title: (item) => item.title,
              meta: (item) => <PublishedBadge item={item} />,
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
