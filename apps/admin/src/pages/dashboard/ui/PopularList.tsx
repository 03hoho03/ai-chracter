import { Link } from "@tanstack/react-router";

import { CONTENT_TYPE_LABELS } from "@/entities/admin-content";
import { formatCount } from "@/shared/lib/format/formatCount";
import { DataList, type DataListColumn } from "@/shared/ui/DataList";

import { usePopularQuery, type AdminDashboardPopularItem } from "../api/usePopularQuery";

/** `chat_count` 내림차순 Top 10. 카드 껍데기 없이 제목 + 목록이다 — 목록이 이미 테두리를 가져 카드 안에 넣으면
 * 상자 속 상자가 된다. */
export function PopularList() {
  return (
    <section>
      <h2 className="mb-4 text-sm font-medium text-foreground">인기 작품 Top 10</h2>
      <PopularTable />
    </section>
  );
}

const COLUMNS: readonly DataListColumn<AdminDashboardPopularItem>[] = [
  { id: "name", header: "이름", cell: (item) => item.name || "(이름 없음)", isPrimary: true },
  { id: "type", header: "타입", cell: (item) => CONTENT_TYPE_LABELS[item.type] },
  { id: "chats", header: "채팅수", align: "end", cell: (item) => formatCount(item.chatCount) },
  { id: "views", header: "조회수", align: "end", cell: (item) => formatCount(item.viewCount) },
  { id: "likes", header: "좋아요수", align: "end", cell: (item) => formatCount(item.likeCount) },
];

/** 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. 좁은 폭에서는 다섯 칸 표 대신 카드 행이다 —
 * 순위 비교에 필요한 채팅수만 오른쪽 끝에 두고 나머지는 한 줄 메타로 내린다. */
function PopularTable() {
  const popularQuery = usePopularQuery();

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
    <DataList
      caption="채팅수 기준 인기 작품 10개"
      rows={popularQuery.data}
      getRowKey={(item) => item.id}
      columns={COLUMNS}
      renderRowTarget={(item, props) => <Link to="/contents/$contentId" params={{ contentId: item.id }} {...props} />}
      card={{
        title: (item) => item.name || "(이름 없음)",
        meta: (item) => (
          <>
            <span>{CONTENT_TYPE_LABELS[item.type]}</span>
            <span aria-hidden>·</span>
            <span>조회 {formatCount(item.viewCount)}</span>
            <span aria-hidden>·</span>
            <span>좋아요 {formatCount(item.likeCount)}</span>
          </>
        ),
        trailing: (item) => `채팅 ${formatCount(item.chatCount)}`,
      }}
    />
  );
}
