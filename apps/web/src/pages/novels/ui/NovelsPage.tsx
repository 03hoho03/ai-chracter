import { Button } from "@ai-character-chat/ui/components/button";
import { DropdownMenuItem } from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { useRef } from "react";

import {
  CONTENT_TYPE_LABEL,
  ContentCardActionMenu,
  ContentListEmptyState,
  ContentListLoadMore,
} from "@/entities/content";
import { isNovelizeNotAllowedError, NovelizeLockedState, useNovelListQuery, type NovelListItem } from "@/entities/novel";
import { DeleteNovelModal } from "@/features/delete-novel";
import { formatDate } from "@/shared/lib/time/formatDate";

const PAGE_CLASS = "mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10";

/** `/novels` — 내 소설 목록. 원래 대화방을 지운 소설도 여기 남는다(읽고 고칠 수 있다). 장이 아직 없는 소설도
 * 보인다 — 채팅방에서 `소설로 보기`를 누르는 순간 빈 소설이 생기기 때문이다.
 *
 * 허용 없는 계정이 주소로 들어오면 서버가 403 을 주고, 그때는 제목까지 통째로 잠김 안내로 바꾼다. */
export function NovelsPage() {
  const query = useNovelListQuery();

  if (query.isError && isNovelizeNotAllowedError(query.error)) {
    return (
      <main className={PAGE_CLASS}>
        <NovelizeLockedState />
      </main>
    );
  }

  return (
    <main className={PAGE_CLASS}>
      <h1 className="text-2xl font-bold tracking-tight text-foreground">내 소설</h1>
      <NovelListBody query={query} />
    </main>
  );
}

function NovelListBody({ query }: { query: ReturnType<typeof useNovelListQuery> }) {
  const listRef = useRef<HTMLUListElement>(null);
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];

  // 재시도 백오프 중에도 `isPending` 이라 `failureCount === 0` 으로 걸러야 실패가 스켈레톤에 갇히지 않는다
  // (클로버 내역과 같은 순서).
  if (query.isPending && query.failureCount === 0) {
    return <NovelListSkeleton />;
  }

  if (query.isError && items.length === 0) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-destructive-text">소설 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
        <RetryButton query={query} />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <ContentListEmptyState
        title="아직 소설이 없어요"
        message="채팅방 더보기에서 「소설로 보기」를 누르면 그 대화의 소설이 여기에 생겨요."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {query.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-destructive-text">새로고침에 실패했어요. 보이는 목록이 최신이 아닐 수 있어요.</p>
          <RetryButton query={query} />
        </div>
      )}

      {/* 마지막 페이지에서 "더 보기"가 사라질 때 포커스를 받을 자리다(Tab 순서에는 넣지 않는다). */}
      <ul ref={listRef} tabIndex={-1} className="flex flex-col gap-3 outline-none">
        {items.map((novel) => (
          <li key={novel.id}>
            <NovelListRow novel={novel} onDeleted={() => listRef.current?.focus()} />
          </li>
        ))}
      </ul>

      <ContentListLoadMore
        hasMore={query.hasNextPage}
        isLoading={query.isFetchingNextPage}
        onLoadMore={() => {
          if (query.hasNextPage && !query.isFetchingNextPage) {
            void query.fetchNextPage();
          }
        }}
        onExhausted={() => listRef.current?.focus()}
      />
    </div>
  );
}

/** 행은 문의 내역과 같은 클릭 카드 레시피(배경과 같은 면 + hover 에서 한 칸 밝게)다. 같은 작품의 방이 둘이면
 * 제목이 같은 소설이 둘 생기므로, 마지막으로 바뀐 날짜를 함께 보여 가른다.
 *
 * 링크 안에 메뉴 버튼을 넣을 수 없어(대화형 요소 중첩) 상자는 바깥 `div` 가 그리고, 링크는 `after:` 로 상자 전체를
 * 덮어 어디를 눌러도 열린다. "⋯" 메뉴는 그 위 층에 형제로 놓인다. hover·포커스·눌림 표시는 상자가 링크의 상태를
 * 보고(`has-`) 그린다 — 메뉴 버튼 hover 는 카드 hover 와 겹치지 않는다(메뉴 셸이 한 칸 밝은 면을 쓴다). */
function NovelListRow({ novel, onDeleted }: { novel: NovelListItem; onDeleted: () => void }) {
  const meta = [
    CONTENT_TYPE_LABEL[novel.contentType],
    novel.chapterCount > 0 ? `${novel.chapterCount}화` : "아직 화가 없어요",
    formatDate(novel.updatedAt),
  ];

  return (
    <div className="relative flex items-start gap-2 rounded-xl border border-border bg-background p-4 motion-safe:transition-colors has-[a:hover]:bg-muted has-[a:focus-visible]:border-ring has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-ring/50 has-[a:active]:translate-y-px">
      <Link
        to="/novels/$novelId"
        params={{ novelId: novel.id }}
        className="flex min-w-0 flex-1 flex-col gap-1 outline-none after:absolute after:inset-0 after:rounded-xl"
      >
        <span className="break-keep text-lg font-semibold text-foreground">{novel.contentTitle}</span>
        <span className="text-sm break-keep text-muted-foreground">{meta.join(" · ")}</span>
        {novel.chatRoomId === null && (
          <span className="text-sm break-keep text-muted-foreground">원래 대화방은 지워졌어요</span>
        )}
      </Link>
      <div className="relative">
        <ContentCardActionMenu title={novel.contentTitle}>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() =>
              void DeleteNovelModal.call({ novelId: novel.id, title: novel.contentTitle, hasActiveJob: undefined }).then(
                (isDeleted) => {
                  // 지운 소설의 메뉴 버튼은 행과 함께 사라진다 — 목록으로 포커스를 받아 둔다.
                  if (isDeleted) onDeleted();
                },
              )
            }
          >
            <Trash2 aria-hidden />
            소설 지우기
          </DropdownMenuItem>
        </ContentCardActionMenu>
      </div>
    </div>
  );
}

/** 다시 가져오는 동안 `disabled` 를 걸면 누르는 순간 포커스가 `<body>` 로 떨어지므로 `aria-disabled` + 첫 줄
 * return 으로 막는다. */
function RetryButton({ query }: { query: ReturnType<typeof useNovelListQuery> }) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-disabled={query.isFetching}
      className="aria-disabled:opacity-65"
      onClick={() => {
        if (query.isFetching) return;
        void query.refetch();
      }}
    >
      다시 시도
    </Button>
  );
}

function NovelListSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="h-20 w-full animate-pulse rounded-xl bg-muted" />
      <div className="h-20 w-full animate-pulse rounded-xl bg-muted" />
      <div className="h-20 w-full animate-pulse rounded-xl bg-muted" />
    </div>
  );
}
