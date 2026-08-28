import { useCallback } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useAtomValue } from "jotai";
import { Loader2, X } from "lucide-react";

import {
  ContentCard,
  ContentListEmptyState,
  useContentListQuery,
  useGenreListQuery,
  type ContentListSort,
} from "@/entities/content";
import { useContentDetailModal } from "@/shared/lib/content-detail-modal/useContentDetailModal";
import { useInfiniteScrollSentinel } from "@/shared/lib/infinite-scroll/useInfiniteScrollSentinel";
import { contentTypeToggleAtom } from "@/shared/model/content-type-toggle";

export type HomeSearch = {
  q?: string;
  sort?: ContentListSort;
  genre?: string;
  creator?: string;
  hashtag?: string;
};

const SORT_OPTIONS: { value: ContentListSort; label: string }[] = [
  { value: "latest", label: "최신순" },
  { value: "popular", label: "인기순" },
  { value: "genre", label: "장르별" },
];

function isContentListSort(value: string): value is ContentListSort {
  return value === "latest" || value === "popular" || value === "genre";
}

const ALL_GENRES_VALUE = "all";

function ContentGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((key) => (
        <div key={key} className="aspect-[3/4] animate-pulse rounded-xl bg-muted" />
      ))}
    </div>
  );
}

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

  const fetchNextPage = useCallback(() => {
    if (contentListQuery.hasNextPage && !contentListQuery.isFetchingNextPage) {
      void contentListQuery.fetchNextPage();
    }
  }, [contentListQuery]);
  const sentinelRef = useInfiniteScrollSentinel(fetchNextPage, Boolean(contentListQuery.hasNextPage));

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
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

      {contentListQuery.isPending && <ContentGridSkeleton />}

      {contentListQuery.isError && (
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {contentListQuery.data && items.length === 0 && <ContentListEmptyState />}

      {contentListQuery.data && items.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {items.map((item, index) => (
              <ContentCard
                key={item.id}
                thumbnailUrl={item.thumbnailUrl}
                title={item.name}
                metrics={{ viewCount: item.viewCount }}
                author={{ name: item.creatorNickname, profileUrl: `/profile/${item.creatorUserId}` }}
                priority={index < 4}
                isLcpCandidate={index === 0}
                onClick={() => open(item.type, item.id)}
                onAuthorClick={() => onSearchChange({ creator: item.creatorUserId })}
              />
            ))}
          </div>

          <div ref={sentinelRef} className="flex justify-center py-4">
            {contentListQuery.isFetchingNextPage && (
              <Loader2 aria-hidden className="size-5 animate-spin text-muted-foreground" />
            )}
          </div>
        </>
      )}
    </main>
  );
}
