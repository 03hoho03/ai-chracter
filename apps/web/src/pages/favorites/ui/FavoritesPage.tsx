import { useCallback } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useAtomValue } from "jotai";
import { Loader2 } from "lucide-react";

import {
  ContentCard,
  ContentCardGrid,
  ContentCardSkeleton,
  ContentListEmptyState,
  toThumbnailAspect,
  useFavoriteListQuery,
  type ContentType,
} from "@/entities/content";
import { useContentDetailModal } from "@/shared/lib/content-detail-modal/useContentDetailModal";
import { useInfiniteScrollSentinel } from "@/shared/lib/infinite-scroll/useInfiniteScrollSentinel";
import { contentTypeToggleAtom } from "@/shared/model/content-type-toggle";

export type FavoritesSearch = {
  type?: ContentType;
};

const TYPE_OPTIONS: { value: ContentType; label: string }[] = [
  { value: "character", label: "캐릭터" },
  { value: "story", label: "스토리" },
];

/** techspec-home-discovery.md §4 — 즐겨찾기 목록. §1 홈 무한스크롤과 동일한 구조(`ContentCard`/
 * `ContentListEmptyState`/sentinel)를 재사용한다.
 *
 * card-grid-goal-prompt.md D-6 — 그리드가 항상 단일 타입이어야 D-5(타입별 열 수)가 예외 없이 성립하므로,
 * 캐릭터/스토리 2택 `Select`를 둔다('전체' 없음). 헤더의 전역 `ContentTypeToggle`과 같은 프리미티브
 * (`ToggleGroup`)를 쓰면 같은 모양의 컨트롤 둘이 다르게 동작하게 돼(하나는 홈으로 이동) `Select`를
 * 쓴다(card-grid-techspec.md T-1). 기본값은 `contentTypeToggleAtom`의 현재값 — atom은 읽기만 하고
 * 쓰지 않는다. 이후 진실은 `?type=` URL이다. */
export function FavoritesPage({
  search,
  onSearchChange,
}: {
  search: FavoritesSearch;
  onSearchChange: (patch: Partial<FavoritesSearch>) => void;
}) {
  const headerToggleType = useAtomValue(contentTypeToggleAtom);
  const { open } = useContentDetailModal();
  const type = search.type ?? headerToggleType;

  const favoriteListQuery = useFavoriteListQuery(type);

  const items = favoriteListQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const thumbnailAspect = toThumbnailAspect(type);

  const fetchNextPage = useCallback(() => {
    if (favoriteListQuery.hasNextPage && !favoriteListQuery.isFetchingNextPage) {
      void favoriteListQuery.fetchNextPage();
    }
  }, [favoriteListQuery]);
  const sentinelRef = useInfiniteScrollSentinel(fetchNextPage, Boolean(favoriteListQuery.hasNextPage));

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 sm:px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight text-foreground">즐겨찾기</h1>

        <Select
          value={type}
          onValueChange={(value) => {
            if (isContentType(value)) onSearchChange({ type: value });
          }}
        >
          <SelectTrigger size="sm" aria-label="즐겨찾기 유형 필터">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TYPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {favoriteListQuery.isPending && (
        <ContentCardGrid thumbnailAspect={thumbnailAspect}>
          {Array.from({ length: 8 }, (_, index) => (
            <ContentCardSkeleton key={index} thumbnailAspect={thumbnailAspect} metrics={{ viewCount: 0 }} />
          ))}
        </ContentCardGrid>
      )}

      {favoriteListQuery.isError && items.length === 0 && (
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {favoriteListQuery.isError && items.length > 0 && (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-destructive-text">
            새로고침에 실패했어요. 보이는 목록이 최신이 아닐 수 있어요.
          </p>
          <Button type="button" variant="outline" size="sm" onClick={() => void favoriteListQuery.refetch()}>
            다시 시도
          </Button>
        </div>
      )}

      {favoriteListQuery.data && items.length === 0 && (
        <ContentListEmptyState message="아직 즐겨찾기한 작품이 없어요. 마음에 드는 캐릭터·스토리를 상세화면에서 즐겨찾기에 담아보세요." />
      )}

      {favoriteListQuery.data && items.length > 0 && (
        <>
          <ContentCardGrid thumbnailAspect={thumbnailAspect}>
            {items.map((item, index) => (
              <ContentCard
                key={item.id}
                thumbnailUrl={item.thumbnailUrl}
                thumbnailAspect={thumbnailAspect}
                title={item.name}
                metrics={{ viewCount: item.viewCount }}
                author={{ name: item.creatorNickname, profileUrl: `/profile/${item.creatorUserId}` }}
                priority={index < 4}
                isLcpCandidate={index === 0}
                onClick={() => open(item.type, item.id)}
              />
            ))}
          </ContentCardGrid>

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

function isContentType(value: string): value is ContentType {
  return value === "character" || value === "story";
}
