import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Link } from "@tanstack/react-router";
import { FileQuestion, Heart, Loader2 } from "lucide-react";
import { useCallback, useId } from "react";

import { useCloverPricingQuery } from "@/entities/clover";
import { ContentListEmptyState } from "@/entities/content";
import {
  toUniqueWebnovels,
  toWebnovelLoadFailure,
  useWebnovelListQuery,
  WebnovelCover,
  WebnovelSourceCredit,
  type WebnovelListItem,
  type WebnovelListSort,
} from "@/entities/webnovel";
import { useInfiniteScrollSentinel } from "@/shared/lib/infinite-scroll/useInfiniteScrollSentinel";
import { formatCompactCount } from "@/shared/lib/number/formatCompactCount";

const PAGE_CLASS = "mx-auto flex max-w-5xl flex-col gap-6 px-4 sm:px-6 py-10";

const SORT_LABELS: Record<WebnovelListSort, string> = { latest: "최신순", popular: "인기순" };

function isListSort(value: string): value is WebnovelListSort {
  return value === "latest" || value === "popular";
}

/** `/webnovels` — 노벨 목록. 회원이 AI 캐릭터와 나눈 대화를 소설로 옮겨 공개한 작품들이다. 목록의 모든 작품이 그렇게
 * 만든 소설이라 행마다 배지를 달지 않고 머리의 한 문장이 그 표시를 맡는다.
 *
 * 항목은 카드 그리드가 아니라 행(표지 왼쪽 · 글 오른쪽)이다 — 소설은 소개 문장이 고르는 기준인데, 좁은 화면의 세로
 * 그리드 카드에는 제목·원작·지표를 넣으면 소개가 들어갈 자리가 없다. `md` 이상은 두 열.
 *
 * 노벨이 꺼져 있으면(공개 가격 응답의 켜짐 표시, 또는 목록 API 의 404) 찾을 수 없는 화면을 그린다 — 헤더에서도 탭이
 * 사라지고, 주소로 들어온 사람에게도 노벨이 없는 것과 같다. */
export function WebnovelsPage({ sort, onSortChange }: { sort: WebnovelListSort; onSortChange: (sort: WebnovelListSort) => void }) {
  const pricing = useCloverPricingQuery();
  const query = useWebnovelListQuery(sort);
  const isOff =
    pricing.data?.novelPublicEnabled === false || (query.isError && toWebnovelLoadFailure(query.error).kind === "missing");

  if (isOff) {
    return (
      <main className={PAGE_CLASS}>
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center break-keep">
          <FileQuestion aria-hidden className="size-8 text-muted-foreground" />
          <h1 className="text-lg font-semibold text-foreground">페이지를 찾을 수 없어요</h1>
          <p className="text-sm text-muted-foreground">주소가 잘못됐거나 사라진 페이지예요.</p>
          <Button asChild className="mt-3">
            <Link to="/">홈으로</Link>
          </Button>
        </div>
      </main>
    );
  }

  const freeChapterCount = pricing.data?.novelFreeChapterCount;

  return (
    <main className={PAGE_CLASS}>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">노벨</h1>
        <p className="text-sm text-pretty break-keep text-muted-foreground">
          회원들이 AI 캐릭터와 나눈 대화를 소설로 옮겨 공개한 작품이에요.
          {freeChapterCount !== undefined && freeChapterCount > 0 && ` 앞 ${freeChapterCount}화는 무료예요.`}
        </p>
      </div>

      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={sort}
        onValueChange={(value) => {
          // 이미 고른 칩을 다시 누르면 빈 값이 온다 — 정렬은 늘 하나가 골라져 있어야 해서 무시한다.
          if (isListSort(value)) onSortChange(value);
        }}
        aria-label="정렬"
        className="self-start"
      >
        {(["latest", "popular"] as const).map((value) => (
          <ToggleGroupItem key={value} value={value}>
            {SORT_LABELS[value]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      <WebnovelListBody query={query} />
    </main>
  );
}

function WebnovelListBody({ query }: { query: ReturnType<typeof useWebnovelListQuery> }) {
  const items = toUniqueWebnovels(query.data?.pages ?? []);
  const fetchNextPage = useCallback(() => {
    if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
  }, [query]);
  const sentinelRef = useInfiniteScrollSentinel(fetchNextPage, Boolean(query.hasNextPage));

  // 재시도 백오프 중에도 `isPending` 이라 `failureCount === 0` 으로 걸러야 실패가 스켈레톤에 갇히지 않는다.
  if (query.isPending && query.failureCount === 0) return <WebnovelListSkeleton />;

  if (query.isError && items.length === 0) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-destructive-text">노벨 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
        <RetryButton query={query} />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <ContentListEmptyState
        title="아직 공개된 노벨이 없어요"
        message="대화를 소설로 만든 뒤 내 소설에서 공개할 수 있어요."
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

      <ul className="grid gap-x-8 gap-y-6 md:grid-cols-2">
        {items.map((item, index) => (
          <li key={item.id}>
            {/* 첫 화면에 보일 만큼(두 열 × 세 줄)은 표지를 바로 받는다. */}
            <WebnovelRow item={item} isPriority={index < 6} />
          </li>
        ))}
      </ul>

      <div ref={sentinelRef} className="flex justify-center py-4">
        {query.isFetchingNextPage && <Loader2 aria-hidden className="size-5 animate-spin text-muted-foreground" />}
      </div>
    </div>
  );
}

/** 목록의 한 줄 — 표지 · 제목 두 줄 · 원작 한 줄 · 소개 두 줄 · 게시자와 지표. 껍데기(배경·보더·hover) 없이 그림과
 * 글만 놓는 것은 홈 큐레이션 블록과 같은 어휘다. 줄 전체가 작품 정보로 가는 링크 하나라 포커스 링과 눌림 표시를
 * 링크에 직접 단다(전역 1px 아웃라인은 3:1 미달). 링크 이름은 제목만 — 소개까지 읽히면 목록을 훑기 어렵다. */
function WebnovelRow({ item, isPriority }: { item: WebnovelListItem; isPriority: boolean }) {
  const titleId = useId();
  const meta = [item.publisherNickname, `${item.chapterCount}화`].filter((part) => part !== null);

  return (
    <Link
      to="/webnovels/$novelId"
      params={{ novelId: item.id }}
      aria-labelledby={titleId}
      className="flex items-start gap-4 rounded-xl focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"
    >
      <WebnovelCover url={item.source.coverUrl} isPriority={isPriority} className="w-20 sm:w-24" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p id={titleId} className="line-clamp-2 text-lg font-semibold break-keep text-foreground">
          {item.title}
        </p>
        <WebnovelSourceCredit source={item.source} isLinked={false} className="truncate text-xs" />
        {item.synopsis !== "" && (
          <p className="mt-1 line-clamp-2 text-sm break-keep text-muted-foreground">{item.synopsis}</p>
        )}
        <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground tabular-nums">
          <span className="min-w-0 truncate">{meta.join(" · ")}</span>
          <span aria-hidden>·</span>
          <span className="inline-flex items-center gap-1">
            <Heart aria-hidden className="size-3" />
            <span className="sr-only">좋아요</span>
            {formatCompactCount(item.likeCount)}
          </span>
        </p>
      </div>
    </Link>
  );
}

function RetryButton({ query }: { query: ReturnType<typeof useWebnovelListQuery> }) {
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

/** 로딩 — 행 네 줄. 스켈레톤은 진행 표시라 모션 가드를 걸지 않는다. */
function WebnovelListSkeleton() {
  return (
    <div aria-hidden className="grid gap-x-8 gap-y-6 md:grid-cols-2">
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="flex items-start gap-4">
          <div className="aspect-story w-20 shrink-0 animate-pulse rounded-xl bg-muted sm:w-24" />
          <div className="flex flex-1 flex-col gap-2">
            <div className="h-6 w-3/4 animate-pulse rounded-lg bg-muted" />
            <div className="h-4 w-1/2 animate-pulse rounded-lg bg-muted" />
            <div className="h-10 w-full animate-pulse rounded-lg bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}
