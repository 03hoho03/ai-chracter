import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { Link, useNavigate } from "@tanstack/react-router";

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
    return <div className="h-64 animate-pulse rounded-xl bg-secondary" />;
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
            // 행 전체 클릭은 두되 키보드·보조기술 진입점은 첫 셀의 `Link`다 — `<tr role="button">`은
            // 표의 행·열 의미를 지우고 새 탭 열기도 막는다. 클릭이 링크 안에서 났으면 `tr`은 손을 뗀다:
            // 일반 클릭은 `Link`가 이미 이동했고, Cmd/Ctrl+클릭은 새 탭만 열어야 한다.
            // hover는 `bg-card` 위라 공용 `muted/50`이 안 보여 `secondary/50`으로 덮는다.
            <TableRow
              key={item.id}
              className="cursor-pointer hover:bg-secondary/50"
              onClick={(event) => {
                if (event.target instanceof Element && event.target.closest("a")) return;
                void navigate({ to: "/contents/$contentId", params: { contentId: item.id } });
              }}
            >
              <TableCell>
                <Link
                  to="/contents/$contentId"
                  params={{ contentId: item.id }}
                  className="block w-full rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  {item.name || "(이름 없음)"}
                </Link>
              </TableCell>
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
