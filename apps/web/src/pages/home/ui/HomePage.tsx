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
import { useHorizontalScrollClip } from "@/shared/lib/scroll/useHorizontalScrollClip";

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

/** 헤더 전역 [캐릭터]/[스토리] 토글에 따른 유형별 무한스크롤 리스트,
 * URL search param으로 관리되는 정렬/장르/검색어/크리에이터/해시태그 필터, 공용 `ContentCard`를
 * 조합한 홈 화면. 인증 가드가 없어 비로그인 사용자도 그대로 열람할 수 있다. */
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
  const genreScroll = useHorizontalScrollClip();

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
    // 홈은 보이는 첫 행이 h1이 아니라 필터 툴바인 유일한 라우트라 상단 패딩을 pt-4로 줄인다
    // (홈의 h1은 sr-only, 즐겨찾기·내 작품은 보이는 h1으로 시작한다). 헤더↔칩 거리 40 → 16px.
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 sm:px-6 pt-4 pb-10">
      <h1 className="sr-only">{contentType === "character" ? "캐릭터 홈" : "스토리 홈"}</h1>

      {/* 장르 캐러셀. flex-wrap 대신 overflow-x-auto인 이유: 칩 11개가 1줄에 필요한 폭은
          780.71px, 본문 컨테이너는 1024px 뷰포트에서 976px다 — 1024px 이상에서만 전부 보이고
          390px에서는 3줄로 접힌다. 래퍼는 항상 렌더하고 min-h-8(칩 높이 32px)로 자리를
          예약한다: 조건부(genreListQuery.data &&)를 안쪽 ToggleGroup에만 두는 이유는, 행 전체를
          조건부로 걸면 로딩 중엔 행이 없다가 도착 시 행 + gap-6(24px)이 통째로 삽입되어 전
          뷰포트에서 새 점프가 생기기 때문이다. */}
      <div className="relative min-h-8">
        {/* -m-1 p-1: overflow-x-auto는 포커스 링을 네 방향 모두 클립한다(가로만 스크롤해도 세로가
            함께 클립된다) — 링 두께 이상을 안팎으로 상쇄한다. BuilderTabStrip과 같은 처방.
            스크롤바 숨김: 클래식 스크롤바 환경에서는 캐러셀 아래에 가로 스크롤바가 15px
            자리를 차지해 래퍼 높이가 32px가 아니라 47px이 된다(실측). 잘렸다는 신호는 아래 양쪽
            페이드가 지므로 어포던스를 잃지 않는다 — 그래서 페이드가 이 결정의 전제다. 이
            저장소의 첫 스크롤바 숨김이다. */}
        <div
          ref={genreScroll.ref}
          className="-m-1 overflow-x-auto p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
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
            >
              <ToggleGroupItem value={ALL_GENRES_VALUE}>전체</ToggleGroupItem>
              {genreListQuery.data.map((genre) => (
                <ToggleGroupItem key={genre.id} value={genre.id}>
                  {genre.name}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        </div>
        {/* 장르 축은 `전체` 칩이 항상 첫 자리에 있어 축의 존재와 현재 값은 잘리지 않는다 —
            MyWorksToolbar가 overflow-x-auto를 회귀로 걷어낸 것과 층위가 다르다. 거기서 밀려난 건
            필터 축 하나 전체였고, 여기서 밀려나는 건 한 축 안의 항목이다. */}
        {genreScroll.isClippedLeft && (
          <div aria-hidden className="pointer-events-none absolute inset-y-1 left-1 w-8 bg-linear-to-r from-background" />
        )}
        {genreScroll.isClippedRight && (
          <div aria-hidden className="pointer-events-none absolute inset-y-1 right-1 w-8 bg-linear-to-l from-background" />
        )}
      </div>

      {/* 정렬을 <main>의 다음 행으로: 툴바 래퍼(flex flex-col)를 새로 만들지 않는다. 만들면
          "툴바 안쪽 간격"과 "툴바→목록 간격"이 경쟁한다. 직접 자식으로 두면 둘 사이가 본문 리듬
          gap-6(24px)이고 그건 칩 간격 8px의 정확히 3배다(두 필터 축은 3배는 벌어져야 갈린다).
          ml-auto는 flex-col의 교차축에서도 남는 공간을 흡수해 우측 정렬을 만든다(실측 확인 —
          align-self 불필요). 정렬 SelectTrigger에는 bg-secondary 강조를 넣지 않는다 — 홈 정렬은
          목록을 줄이는 축이 아니라 순서만 바꾸는 축이다. */}
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

/** 로딩·전면실패·빈·성공 네 갈래를 **early return 순서**로 강제한다. 참고 모델:
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
