import { useCallback } from "react";
import { Loader2 } from "lucide-react";

import { ContentCard, ContentListEmptyState, useFavoriteListQuery } from "../../../entities/content";
import { useContentDetailModal } from "../../../shared/lib/content-detail-modal/useContentDetailModal";
import { useInfiniteScrollSentinel } from "../../../shared/lib/infinite-scroll/useInfiniteScrollSentinel";

function ContentGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((key) => (
        <div key={key} className="aspect-[3/4] animate-pulse rounded-xl bg-muted" />
      ))}
    </div>
  );
}

/** techspec-home-discovery.md §4 — 즐겨찾기 목록. §1 홈 무한스크롤과 동일한 구조(`ContentCard`/
 * `ContentListEmptyState`/sentinel)를 재사용하되, 정렬·장르·검색 필터 UI는 없다. */
export function FavoritesPage() {
  const { open } = useContentDetailModal();
  const favoriteListQuery = useFavoriteListQuery();

  const items = favoriteListQuery.data?.pages.flatMap((page) => page.items) ?? [];

  const fetchNextPage = useCallback(() => {
    if (favoriteListQuery.hasNextPage && !favoriteListQuery.isFetchingNextPage) {
      void favoriteListQuery.fetchNextPage();
    }
  }, [favoriteListQuery]);
  const sentinelRef = useInfiniteScrollSentinel(fetchNextPage, Boolean(favoriteListQuery.hasNextPage));

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <h1 className="text-xl font-bold tracking-tight text-foreground">즐겨찾기</h1>

      {favoriteListQuery.isPending && <ContentGridSkeleton />}

      {favoriteListQuery.isError && (
        <p className="text-sm text-destructive">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {favoriteListQuery.data && items.length === 0 && (
        <ContentListEmptyState message="아직 즐겨찾기한 작품이 없어요. 마음에 드는 캐릭터·스토리를 상세화면에서 즐겨찾기에 담아보세요." />
      )}

      {favoriteListQuery.data && items.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {items.map((item) => (
              <ContentCard
                key={item.id}
                thumbnailUrl={item.thumbnailUrl}
                title={item.name}
                viewCount={item.viewCount}
                author={{ name: item.creatorNickname, profileUrl: `/profile/${item.creatorUserId}` }}
                onClick={() => open(item.type, item.id)}
              />
            ))}
          </div>

          <div ref={sentinelRef} className="flex justify-center py-4">
            {favoriteListQuery.isFetchingNextPage && (
              <Loader2 aria-hidden className="size-5 animate-spin text-muted-foreground" />
            )}
          </div>
        </>
      )}
    </main>
  );
}
