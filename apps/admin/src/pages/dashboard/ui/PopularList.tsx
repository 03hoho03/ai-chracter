import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";

import { CONTENT_TYPE_LABELS } from "@/entities/report";

import { usePopularQuery } from "../api/usePopularQuery";

function formatCount(value: number) {
  return value.toLocaleString("ko-KR");
}

/** `chat_count` 내림차순 Top 10. */
export function PopularList() {
  const popularQuery = usePopularQuery();

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-sm font-medium text-foreground">인기 작품 Top 10</h2>

      {popularQuery.isPending && <div className="h-64 animate-pulse rounded-xl bg-muted" />}

      {popularQuery.isError && (
        <p className="text-sm text-destructive-text">
          인기 작품을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {popularQuery.data && popularQuery.data.length === 0 && (
        <p className="text-sm text-muted-foreground">아직 채팅이 발생한 작품이 없어요.</p>
      )}

      {popularQuery.data && popularQuery.data.length > 0 && (
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
                // 작품 상세 화면은 2단계에서 생긴다 — 그때 이 행에 <Link to="/contents/$contentId">를 건다.
                <TableRow key={item.id}>
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
      )}
    </div>
  );
}
