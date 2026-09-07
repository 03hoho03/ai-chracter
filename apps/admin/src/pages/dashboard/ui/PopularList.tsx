import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { useNavigate } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import { formatCount } from "@/shared/lib/format/formatCount";

import { usePopularQuery } from "../api/usePopularQuery";

/** `chat_count` 내림차순 Top 10. */
export function PopularList() {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-sm font-medium text-foreground">인기 작품 Top 10</h2>
      <PopularTable />
    </div>
  );
}

/** 카드 셸(제목)은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function PopularTable() {
  const popularQuery = usePopularQuery();
  const navigate = useNavigate();

  if (popularQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (popularQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        인기 작품을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (popularQuery.data.length === 0) {
    return <p className="text-sm text-muted-foreground">아직 채팅이 발생한 작품이 없어요.</p>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>이름</TableHead>
            <TableHead>타입</TableHead>
            <TableHead className="text-right">채팅수</TableHead>
            <TableHead className="text-right">조회수</TableHead>
            <TableHead className="text-right">좋아요수</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {popularQuery.data.map((item) => (
            <TableRow
              key={item.id}
              tabIndex={0}
              role="button"
              className="cursor-pointer"
              onClick={() => void navigate({ to: "/contents/$contentId", params: { contentId: item.id } })}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  void navigate({ to: "/contents/$contentId", params: { contentId: item.id } });
                }
              }}
            >
              <TableCell>{item.name || "(이름 없음)"}</TableCell>
              <TableCell className="text-muted-foreground">{CONTENT_TYPE_LABELS[item.type]}</TableCell>
              <TableCell className="text-right tabular-nums">{formatCount(item.chatCount)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatCount(item.viewCount)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatCount(item.likeCount)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
