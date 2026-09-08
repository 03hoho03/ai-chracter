import { Button } from "@ai-character-chat/ui/components/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link, useNavigate } from "@tanstack/react-router";

import { useNoticeListQuery } from "@/entities/notice";
import { Pagination } from "@/shared/ui/Pagination";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

type NoticesListPageProps = {
  page: number;
  onPageChange: (page: number) => void;
};

export function NoticesListPage({ page, onPageChange }: NoticesListPageProps) {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">공지 관리</h1>

        <Button asChild size="sm">
          <Link to="/notices/$noticeId" params={{ noticeId: "new" }}>
            새 공지
          </Link>
        </Button>
      </div>

      <NoticesTable page={page} onPageChange={onPageChange} />
    </main>
  );
}

type NoticesTableProps = {
  page: number;
  onPageChange: (page: number) => void;
};

/** 헤더(제목·새 공지 버튼)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다(`ReportsListPage` 관용구). */
function NoticesTable({ page, onPageChange }: NoticesTableProps) {
  const noticeListQuery = useNoticeListQuery(page);
  const navigate = useNavigate();

  if (noticeListQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (noticeListQuery.isError) {
    return <p className="text-sm text-destructive-text">공지 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (noticeListQuery.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">등록된 공지가 없어요.</p>;
  }

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>제목</TableHead>
              <TableHead>상태</TableHead>
              <TableHead>게시일</TableHead>
              {/* BE 응답(`AdminNoticeListItem`, `apps/api/src/api/admin/notices.py`)에는
                  `updatedAt`이 없다 — `Notice.updated_at`이 onupdate=func.now() 컬럼이라
                  커밋 직후 재조회 없이 읽으면 그린렛 밖 재조회가 필요해 응답 스펙에서
                  뺐다(`_to_detail` 주석). "수정일" 대신 실제로 있는 작성일을 쓴다. */}
              <TableHead>작성일</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {noticeListQuery.data.items.map((item) => (
              <TableRow
                key={item.id}
                tabIndex={0}
                role="button"
                className="cursor-pointer"
                onClick={() => void navigate({ to: "/notices/$noticeId", params: { noticeId: item.id } })}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void navigate({ to: "/notices/$noticeId", params: { noticeId: item.id } });
                  }
                }}
              >
                <TableCell>{item.title}</TableCell>
                <TableCell>
                  <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
                    {item.published ? "게시" : "숨김"}
                  </span>
                </TableCell>
                <TableCell>{formatDateTime(item.publishedAt)}</TableCell>
                <TableCell>{formatDateTime(item.createdAt)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Pagination
        page={noticeListQuery.data.page}
        totalPages={noticeListQuery.data.totalPages}
        totalCount={noticeListQuery.data.totalCount}
        onPageChange={onPageChange}
      />
    </>
  );
}
