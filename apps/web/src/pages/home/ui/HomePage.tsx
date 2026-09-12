import { useCallback } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useAtomValue } from "jotai";
import { Loader2, X } from "lucide-react";

import {
  CONTENT_LIST_SORTS,
  ContentCard,
  ContentCardGrid,
  ContentCardSkeleton,
  ContentListEmptyState,
  contentTypeToggleAtom,
  isContentListSort,
  toPriorityCount,
  toThumbnailAspect,
  useContentDetailModal,
  useContentListQuery,
  useGenreListQuery,
  type ContentListItem,
  type ContentListSort,
  type ContentType,
  type ThumbnailAspect,
} from "@/entities/content";
import { useInfiniteScrollSentinel } from "@/shared/lib/infinite-scroll/useInfiniteScrollSentinel";

export type HomeSearch = {
  q?: string;
  sort?: ContentListSort;
  genre?: string;
  creator?: string;
  hashtag?: string;
};

const SORT_LABEL: Record<ContentListSort, string> = {
  latest: "최신순",
  popular: "인기순",
  genre: "장르별",
};

const SORT_OPTIONS: { value: ContentListSort; label: string }[] = CONTENT_LIST_SORTS.map((value) => ({
  value,
  label: SORT_LABEL[value],
}));

const ALL_GENRES_VALUE = "all";

/** techspec-home-discovery.md — 헤더 전역 [캐릭터]/[스토리] 토글(§0)에 따른 유형별 무한스크롤 리스트(§1),
 * URL search param으로 관리되는 정렬/장르/검색어/크리에이터/해시태그 필터(§2), 공용 `ContentCard`(§3)를
 * 조합한 홈 화면. 인증 가드가 없어 비로그인 사용자도 그대로 열람할 수 있다(§5). */
export function HomePage({
  search,
  onSearchChange,
}: {
  search: HomeSearch;
  onSearchChange: (patch: Partial<HomeSearch>) => void;
}) {
  const contentType = useAtomValue(contentTypeToggleAtom);
  const { open } = useContentDetailModal();
  const genreListQuery = useGenreListQuery();

  const sort = search.sort ?? "latest";
  const contentListQuery = useContentListQuery({
    type: contentType,
    sort,
    genre: search.genre,
    creator: search.creator,
    hashtag: search.hashtag,
    q: search.q,
  });

  const items = contentListQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const activeCreatorNickname = search.creator ? items[0]?.creatorNickname : undefined;
  const hasActiveExtraFilter = Boolean(search.creator || search.hashtag);
  const thumbnailAspect = toThumbnailAspect(contentType);

  const fetchNextPage = useCallback(() => {
    if (contentListQuery.hasNextPage && !contentListQuery.isFetchingNextPage) {
      void contentListQuery.fetchNextPage();
    }
  }, [contentListQuery]);
  const sentinelRef = useInfiniteScrollSentinel(fetchNextPage, Boolean(contentListQuery.hasNextPage));

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 sm:px-6 py-10">
      <h1 className="sr-only">{contentType === "character" ? "캐릭터 홈" : "스토리 홈"}</h1>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {genreListQuery.data && (
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={search.genre ?? ALL_GENRES_VALUE}
            onValueChange={(value) => {
              if (!value) return;
              onSearchChange({ genre: value === ALL_GENRES_VALUE ? undefined : value });
            }}
            aria-label="장르 필터"
            className="flex-wrap"
          >
            <ToggleGroupItem value={ALL_GENRES_VALUE}>전체</ToggleGroupItem>
            {genreListQuery.data.map((genre) => (
              <ToggleGroupItem key={genre.id} value={genre.id}>
                {genre.name}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}

        <Select
          value={sort}
          onValueChange={(value) => {
            if (isContentListSort(value)) onSearchChange({ sort: value });
          }}
        >
          <SelectTrigger size="sm" aria-label="정렬" className="ml-auto">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {hasActiveExtraFilter && (
        <div className="flex flex-wrap gap-2">
          {search.creator && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground">
              {activeCreatorNickname ? `${activeCreatorNickname}님 작품` : "특정 작가 작품"}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-4"
                aria-label="작가 필터 해제"
                onClick={() => onSearchChange({ creator: undefined })}
              >
                <X aria-hidden className="size-3" />
              </Button>
            </span>
          )}
          {search.hashtag && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground">
              #{search.hashtag}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-4"
                aria-label="해시태그 필터 해제"
                onClick={() => onSearchChange({ hashtag: undefined })}
              >
                <X aria-hidden className="size-3" />
              </Button>
            </span>
          )}
        </div>
      )}

      <HomeContentBody
        query={contentListQuery}
        items={items}
        thumbnailAspect={thumbnailAspect}
        sentinelRef={sentinelRef}
        onOpenContent={open}
        onAuthorClick={(creatorUserId) => onSearchChange({ creator: creatorUserId })}
      />
    </main>
  );
}

type HomeContentBodyProps = {
  query: ReturnType<typeof useContentListQuery>;
  items: ContentListItem[];
  thumbnailAspect: ThumbnailAspect;
  sentinelRef: ReturnType<typeof useInfiniteScrollSentinel>;
  onOpenContent: (type: ContentType, id: string) => void;
  onAuthorClick: (creatorUserId: string) => void;
};

/** 로딩·전면실패·빈·성공 네 갈래를 **early return 순서**로 강제한다(COMP-04). 참고 모델:
 * `pages/favorites/ui/FavoritesPage.tsx`의 `FavoritesBody`. */
function HomeContentBody({ query, items, thumbnailAspect, sentinelRef, onOpenContent, onAuthorClick }: HomeContentBodyProps) {
  if (query.isPending) {
    return (
      <ContentCardGrid thumbnailAspect={thumbnailAspect}>
        {Array.from({ length: 8 }, (_, index) => (
          <ContentCardSkeleton key={index} thumbnailAspect={thumbnailAspect} metrics={{ viewCount: 0 }} />
        ))}
      </ContentCardGrid>
    );
  }

  if (query.isError && items.length === 0) {
    return <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (items.length === 0) {
    return <ContentListEmptyState />;
  }

  return (
    <>
      {query.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-destructive-text">
            새로고침에 실패했어요. 보이는 목록이 최신이 아닐 수 있어요.
          </p>
          <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
            다시 시도
          </Button>
        </div>
      )}

      <ContentCardGrid thumbnailAspect={thumbnailAspect}>
        {items.map((item, index) => (
          <ContentCard
            key={item.id}
            thumbnailUrl={item.thumbnailUrl ?? undefined}
            thumbnailAspect={thumbnailAspect}
            title={item.name}
            metrics={{ viewCount: item.viewCount }}
            author={{ name: item.creatorNickname, profileUrl: `/profile/${item.creatorUserId}` }}
            isPriority={index < toPriorityCount(thumbnailAspect)}
            isLcpCandidate={index === 0}
            onClick={() => onOpenContent(item.type, item.id)}
            onAuthorClick={() => onAuthorClick(item.creatorUserId)}
          />
        ))}
      </ContentCardGrid>

      <div ref={sentinelRef} className="flex justify-center py-4">
        {query.isFetchingNextPage && <Loader2 aria-hidden className="size-5 animate-spin text-muted-foreground" />}
      </div>
    </>
  );
}
