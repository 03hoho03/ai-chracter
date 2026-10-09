import { useCallback, useLayoutEffect, useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Loader2, X } from "lucide-react";

import {
  CONTENT_LIST_SORTS,
  CONTENT_TYPE_LABEL,
  ContentCard,
  ContentCardGrid,
  ContentCardSkeleton,
  ContentListEmptyState,
  isContentListSort,
  isContentType,
  resolveHomeContentType,
  toPriorityCount,
  toThumbnailAspect,
  useContentDetailModal,
  useContentListQuery,
  useGenreListQuery,
  useHomeCurationQuery,
  type ContentListItem,
  type ContentListSort,
  type ContentType,
  type ThumbnailAspect,
} from "@/entities/content";
import { useCloverPricingQuery } from "@/entities/clover";
import { useViewerPersonaName } from "@/entities/persona";
import { isWebnovelOpen, useSessionQuery } from "@/entities/session";
import { useHomeWebnovelsQuery } from "@/entities/webnovel";
import { SITE_INTRO } from "@/shared/config/site";
import { useInfiniteScrollSentinel } from "@/shared/lib/infinite-scroll/useInfiniteScrollSentinel";
import { useHorizontalScrollClip } from "@/shared/lib/scroll/useHorizontalScrollClip";

import { useCurationWaitCap } from "../model/curationWaitCap";
import {
  isHomeWebnovelPending,
  shouldRestoreResultsFocus,
  toHomeCurationLayoutKey,
  toHomeCurationView,
} from "../model/homeCuration";
import { HOME_EMPTY_MESSAGE, toHomeListEndMessage, toHomeListStatus } from "../model/homeListStatus";
import { HOME_FILTER_RESET, hasHomeFilter, type HomeSearch } from "../model/homeSearch";
import { HomeCurationSection } from "./HomeCurationSection";
import { HomeWebnovelSection } from "./HomeWebnovelSection";

const SORT_LABEL: Record<ContentListSort, string> = {
  latest: "최신순",
  popular: "인기순",
};

const SORT_OPTIONS: { value: ContentListSort; label: string }[] = CONTENT_LIST_SORTS.map((value) => ({
  value,
  label: SORT_LABEL[value],
}));

const ALL_GENRES_VALUE = "all";

/** URL `?type=`에 따른 유형별 무한스크롤 리스트, URL search param으로 관리되는
 * 정렬/장르/검색어/크리에이터/해시태그 필터, 공용 `ContentCard`를 조합한 홈 화면. 인증 가드가 없어
 * 비로그인 사용자도 그대로 열람할 수 있다.
 *
 * `onTypeChange` — 유형 전환은 `onSearchChange`(병합)로 못 한다. 정렬만 남기고 나머지 축을 버려야 해서
 * 라우트가 search를 통째로 교체한다. */
export function HomePage({
  search,
  onSearchChange,
  onTypeChange,
}: {
  search: HomeSearch;
  onSearchChange: (patch: Partial<HomeSearch>) => void;
  onTypeChange: (type: ContentType) => void;
}) {
  const contentType = resolveHomeContentType(search.type);
  const { open } = useContentDetailModal();
  const sessionQuery = useSessionQuery();
  const genreListQuery = useGenreListQuery();
  const genreScroll = useHorizontalScrollClip();
  const resultsRef = useRef<HTMLElement>(null);

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
  // 칩 줄은 장르를 빼고 판단한다 — 장르는 자기 칩 줄에서 이미 선택 상태로 보인다.
  const hasActiveChip = Boolean(search.q || search.creator || search.hashtag);
  const isFiltered = hasHomeFilter(search);
  const thumbnailAspect = toThumbnailAspect(contentType);

  // 조건이 걸려도 조회는 그대로 둔다(숨기기만 한다) — 조건을 풀면 응답이 이미 있어 섹션이 기다림 없이 돌아온다.
  //
  // 목록과 큐레이션은 따로 도착한다. 필터 없는 홈에서는 큐레이션이 정해질 때까지(응답 또는 대기 상한 포기) 그리드를
  // 스켈레톤으로 붙잡아, 실제 카드가 그려진 뒤 섹션이 끼어드는 일을 막는다. 목록이 다 온 뒤에도 큐레이션만 기다리는
  // 시간은 상한을 넘기지 않는다 — 넘기면 이 마운트에서는 섹션을 포기하고 그리드를 먼저 그린다(`useCurationWaitCap`).
  // 스켈레톤이 밀리는 것은 아래 `curationLayoutKey` 가 막는다.
  const homeCurationQuery = useHomeCurationQuery(contentType);
  // 큐레이션 응답은 보는 사람과 무관하다 — 한줄소개 속 `{{user}}` 에 넣을 보는 사람의 이름은 여기서 붙인다.
  const viewerPersonaName = useViewerPersonaName(sessionQuery.data !== undefined);
  // 노벨 섹션은 로그인 회원에게, 노벨이 열려 있을 때만 있다(노벨 API 가 로그인 필수다). 큐레이션과 같은 대기 묶음에
  // 넣어, 결과 그리드가 그려진 뒤 섹션이 위에서 밀고 들어오지 않게 한다.
  const isLoggedIn = sessionQuery.data !== undefined;
  const pricingQuery = useCloverPricingQuery();
  const isWebnovelSectionOpen =
    isLoggedIn && isWebnovelOpen(pricingQuery.data?.novelPublicEnabled, sessionQuery.data?.novelPublicEnabled);
  const homeWebnovelsQuery = useHomeWebnovelsQuery({ enabled: isWebnovelSectionOpen });
  const isWebnovelPending = isHomeWebnovelPending({
    isSessionPending: sessionQuery.isPending,
    isLoggedIn,
    isPricingPending: pricingQuery.isPending,
    isOpen: isWebnovelSectionOpen,
    isPending: homeWebnovelsQuery.isPending,
  });
  const isCurationPending = homeCurationQuery.isPending || isWebnovelPending;
  const isHoldingGrid = !isFiltered && isCurationPending && !contentListQuery.isPending;
  const hasGivenUpCuration = useCurationWaitCap(isHoldingGrid);
  const curationView = toHomeCurationView({
    isFiltered,
    hasGivenUp: hasGivenUpCuration,
    isPending: isCurationPending,
    item: homeCurationQuery.data ?? null,
  });
  const homeWebnovels =
    isWebnovelSectionOpen && curationView.kind !== "waiting" && !isFiltered && !hasGivenUpCuration
      ? (homeWebnovelsQuery.data ?? [])
      : [];
  const isListPending = contentListQuery.isPending || curationView.kind === "waiting";
  const curationLayoutKey = toHomeCurationLayoutKey(curationView);

  // 덩어리를 갈아 끼우면 그 안에 있던 포커스(대개 필터를 바꾼 뒤의 착지점인 결과 영역)가 버려진 노드와 함께
  // 사라져 `<body>` 로 떨어진다 — 필터 걸린 주소로 들어와 큐레이션 응답 전에 칩 ×·`필터 지우기` 를 누르면 키가
  // 결정됨 → 결정 중으로 돌아가며 생긴다. 포커스가 덩어리 안에 있었는지를 포커스 이벤트로 기억해 두었다가(노드가
  // 지워질 때는 blur 가 오지 않아 값이 남는다), 갈아 끼운 직후 포커스를 잃었으면 새 결과 영역으로 옮긴다. 덩어리
  // 밖(칩 줄·헤더)에 있던 포커스는 건드리지 않는다. 페인트 전에 옮기려고 layout effect 다.
  const isFocusInChunkRef = useRef(false);
  const lastLayoutKeyRef = useRef(curationLayoutKey);
  useLayoutEffect(() => {
    const isRemounted = lastLayoutKeyRef.current !== curationLayoutKey;
    lastLayoutKeyRef.current = curationLayoutKey;
    const active = document.activeElement;
    const isFocusLost = active === null || active === document.body;
    if (shouldRestoreResultsFocus({ isRemounted, wasFocusInside: isFocusInChunkRef.current, isFocusLost })) {
      resultsRef.current?.focus({ preventScroll: true });
    }
  }, [curationLayoutKey]);

  const fetchNextPage = useCallback(() => {
    if (contentListQuery.hasNextPage && !contentListQuery.isFetchingNextPage) {
      void contentListQuery.fetchNextPage();
    }
  }, [contentListQuery]);
  const sentinelRef = useInfiniteScrollSentinel(fetchNextPage, Boolean(contentListQuery.hasNextPage));

  // 필터를 바꾸면 누른 컨트롤이 사라진다 — 작가 버튼(목록이 스켈레톤으로 바뀐다), 칩 ×(그 칩이 없어진다),
  // `필터 지우기`(자기 패널이 없어진다). 그대로 두면 포커스가 `<body>`로 떨어져 키보드 사용자가
  // 헤더부터 Tab을 다시 시작한다. 그래서 search를 바꾸기 **전에** 동기로, 분기와 무관하게 늘 마운트된 결과
  // 영역으로 포커스를 옮긴다(`apps/web/CLAUDE.md` 포커스 절 — rAF·effect는 라우터 커밋에 기대므로 쓰지 않는다).
  // `preventScroll` — 포커스 이동이 스크롤 위치를 바꾸지 않게 해 마우스로 누른 경우의 화면을 그대로 둔다.
  const changeFilter = (patch: Partial<HomeSearch>) => {
    resultsRef.current?.focus({ preventScroll: true });
    onSearchChange(patch);
  };

  // 상세 모달은 닫히면 연 카드로 포커스를 돌려준다. 그 카드가 그사이 사라졌으면(목록이 다시 그려진 경우) 필터 뒤
  // 착지점과 같은 결과 영역으로 받는다 — 다음 Tab 이 첫 카드로 간다.
  const openDetail = (type: ContentType, id: string) => {
    open(type, id, { getFallbackFocus: () => resultsRef.current });
  };

  return (
    // 홈은 보이는 첫 행이 h1이 아니라 유형·정렬 행인 유일한 라우트라(비로그인은 그 위에 소개 한 줄) 상단
    // 패딩을 pt-4로 줄인다(홈의 h1은 sr-only, 즐겨찾기·내 작품은 보이는 h1으로 시작한다).
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 sm:px-6 pt-4 pb-10">
      <h1 className="sr-only">{contentType === "character" ? "캐릭터 홈" : "스토리 홈"}</h1>

      {/* 처음 온 사람에게 이곳이 무엇인지 말하는 한 줄. 비로그인에게만, 닫기 없이 상시. 세션 확인 중에는
          그리지 않는다 — `!me`만 보면 로그인 사용자에게도 한 번 떴다 사라진다. */}
      {!sessionQuery.isPending && !sessionQuery.data && (
        <p className="break-keep text-sm text-muted-foreground">{SITE_INTRO} 둘러보는 데는 로그인이 필요 없어요.</p>
      )}

      {/* 유형 행. 640px 미만에서는 헤더에 유형 탭이 없어(버거 드로어 안에만 있다) 여기서 바로 바꾸게 하고,
          그 이상은 바로 위 헤더 탭이 전환을 맡으므로 같은 컨트롤을 두 번 세우지 않고 지금 유형 이름만 보인다.
          이름은 h1이 아니다 — h1은 위 sr-only가 맡고, 보이는 h1은 Display(`text-2xl`) 전용이라 이 행에 둘 수
          없다. 같은 말을 h1이 이미 읽으므로 이름은 `aria-hidden`이다.

          정렬은 이 행 오른쪽 끝에 둔다. 정렬만 홀로 선 행을 없애 첫 화면에서 한 행(32px + 행 간격 24px)을
          돌려받고, 정렬이 바꾸는 대상(이 유형의 목록)과 한 줄에 놓인다. 같은 행의 두 컨트롤은 형태가
          달라(텍스트 탭·이름 대 Select 셸) 한 축으로 읽히지 않는다. 아래 장르 칩 줄과는 본문 리듬 gap-6
          (24px, 칩 간격 8px의 3배)으로 떨어진다. 정렬 SelectTrigger에는 강조를 넣지 않는다 — 홈 정렬은
          목록을 줄이는 축이 아니라 순서만 바꾸는 축이다. */}
      <div className="flex min-h-9 items-center justify-between gap-3">
        {/* -ml-2: tab 변형의 좌우 패딩(px-2)만큼 당겨 글자를 본문 왼쪽 선에 맞춘다. 재클릭은 빈 문자열이
            와서 `isContentType`에서 걸러진다. */}
        <ToggleGroup
          type="single"
          variant="tab"
          value={contentType}
          onValueChange={(value) => {
            if (isContentType(value)) onTypeChange(value);
          }}
          aria-label="콘텐츠 유형 전환"
          className="-ml-2 sm:hidden"
        >
          <ToggleGroupItem value="character">캐릭터</ToggleGroupItem>
          <ToggleGroupItem value="story">스토리</ToggleGroupItem>
        </ToggleGroup>
        <p aria-hidden className="hidden text-lg font-semibold text-foreground sm:block">
          {CONTENT_TYPE_LABEL[contentType]}
        </p>

        <Select
          value={sort}
          onValueChange={(value) => {
            if (isContentListSort(value)) onSearchChange({ sort: value });
          }}
        >
          <SelectTrigger size="sm" aria-label="정렬">
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
              {/* `data-filter-default` — 아무것도 거르지 않는 기본값 칩이라는 표식. 선택돼도 `primary`로
                  채우지 않는다(규칙은 `toggleVariants`의 `outline`, 근거는 DESIGN.md Toggles 절). */}
              <ToggleGroupItem value={ALL_GENRES_VALUE} data-filter-default>
                전체
              </ToggleGroupItem>
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

      {/* 장르 밖에서 걸린 조건은 전부 여기 칩으로 보인다 — 화면에 안 보이는 필터가 남지 않게. 검색어도
          헤더 검색을 닫으면 입력칸에서 사라지므로 칩이 맡는다. */}
      {hasActiveChip && (
        <div className="flex flex-wrap gap-2">
          {search.q && (
            <HomeFilterChip
              label={`“${search.q}”`}
              removeLabel="검색어 필터 해제"
              onRemove={() => changeFilter({ q: undefined })}
            />
          )}
          {search.creator && (
            <HomeFilterChip
              label={activeCreatorNickname ? `${activeCreatorNickname}님 작품` : "특정 작가 작품"}
              removeLabel="작가 필터 해제"
              onRemove={() => changeFilter({ creator: undefined })}
            />
          )}
          {search.hashtag && (
            <HomeFilterChip
              label={`#${search.hashtag}`}
              removeLabel="해시태그 필터 해제"
              onRemove={() => changeFilter({ hashtag: undefined })}
            />
          )}
        </div>
      )}

      {/* 큐레이션 섹션과 결과 영역은 한 덩어리로 다시 만든다(덩어리 div 의 `gap-6` 은 `<main>` 의 간격과 같은 값이라 배치가
          바뀌지 않는다). 기다리는 동안 결과 영역의 스켈레톤이 큐레이션 자리에
          그려져 있다가, 섹션이 정해지는 순간 그 위에 섹션이 끼어들면 스켈레톤이 섹션 높이만큼 밀려 내려간다 — 브라우저는
          이것을 레이아웃 이동으로 센다(390px 실측 0.19). 정해지는 순간 `key` 를 바꿔 스켈레톤을 옮기지 않고 새 노드로
          갈아 끼우면, 사라진 노드와 새로 생긴 노드는 이동으로 세지 않는다. 덩어리 아래(푸터)는 스켈레톤 그리드가 첫
          화면보다 길어 화면 밖에 있다. 정해진 뒤 스켈레톤 → 실제 카드는 같은 덩어리 안에서 같은 높이로 바뀐다. */}
      <div
        key={curationLayoutKey}
        className="flex flex-col gap-6"
        onFocus={() => {
          isFocusInChunkRef.current = true;
        }}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) isFocusInChunkRef.current = false;
        }}
      >
        {curationView.kind === "shown" && <HomeCurationSection item={curationView.item} viewerPersonaName={viewerPersonaName} onOpen={openDetail} />}
        {homeWebnovels.length > 0 && <HomeWebnovelSection items={homeWebnovels} />}

        {/* 필터를 바꾼 뒤의 포커스 착지점(`changeFilter`). 로딩·빈·실패·목록 어느 분기에서도 마운트돼 있다.
            스크립트로만 포커스를 받는 영역이라 링을 그리지 않는다 — 다음 Tab이 첫 카드로 간다. */}
        <section ref={resultsRef} tabIndex={-1} aria-label="작품 목록" className="flex flex-col gap-6 outline-none">
          <HomeContentBody
            query={contentListQuery}
            isPending={isListPending}
            items={items}
            thumbnailAspect={thumbnailAspect}
            sentinelRef={sentinelRef}
            endMessage={toHomeListEndMessage(contentType, isFiltered)}
            onOpenContent={openDetail}
            onAuthorClick={(creatorUserId) => changeFilter({ creator: creatorUserId })}
            onFiltersClear={isFiltered ? () => changeFilter(HOME_FILTER_RESET) : undefined}
            // `다시 시도`도 자기 패널을 언마운트시킨다 — 데이터가 하나도 없는 쿼리는 재요청을 시작하는 순간
            // `isPending`으로 돌아가 스켈레톤 분기가 되므로 패널·버튼이 즉시 사라진다. 그래서 `changeFilter`와
            // 같이 재요청 **전에** 동기로 결과 영역에 포커스를 옮긴다.
            onRetry={() => {
              resultsRef.current?.focus({ preventScroll: true });
              void contentListQuery.refetch();
            }}
          />
        </section>
      </div>

      {/* 결과 상태 라이브 영역. 분기마다 갈아끼우는 자리에 두면 영역 자체가 새로 생겨 읽히지 않으므로
          `HomeContentBody` 밖에 항상 마운트해 두고 글자만 바꾼다. */}
      <p role="status" className="sr-only">
        {toHomeListStatus({
          type: contentType,
          isFiltered,
          isPending: isListPending,
          isError: contentListQuery.isError,
          itemCount: items.length,
          hasNextPage: Boolean(contentListQuery.hasNextPage),
        })}
      </p>
    </main>
  );
}

/** 걸린 조건 하나를 보이고 해제하는 칩. 세 축(검색어·작가·해시태그)이 같은 모양이라 하나로 묶는다 —
 * 사본 셋이면 히트 영역 숫자 하나가 갈린다.
 *
 * × 히트 영역 — 보이는 버튼은 16px 그대로 두고 `after:`로 누르는 영역만 넓힌다(`KeywordChipField`의 칩 ×와
 * 같은 관용구). 버튼 보더 1px 안쪽에서 펼쳐지므로 `-inset-2`는 30px, 터치(`pointer-coarse`)에서 `-inset-3.5`는
 * 42px로 손가락 타깃 40px를 넘긴다. 넓힌 영역이 라벨 끝 몇 px를 덮어 그 자리를 눌러도 해제된다(같은 감수). */
function HomeFilterChip({ label, removeLabel, onRemove }: { label: string; removeLabel: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground">
      {label}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="relative size-4 after:absolute after:-inset-2 pointer-coarse:after:-inset-3.5"
        aria-label={removeLabel}
        onClick={onRemove}
      >
        <X aria-hidden className="size-3" />
      </Button>
    </span>
  );
}

type HomeContentBodyProps = {
  query: ReturnType<typeof useContentListQuery>;
  /** 목록 쿼리의 `isPending` 에 큐레이션 기다림을 더한 값 — 스켈레톤 분기는 이것만 본다. */
  isPending: boolean;
  items: ContentListItem[];
  thumbnailAspect: ThumbnailAspect;
  sentinelRef: ReturnType<typeof useInfiniteScrollSentinel>;
  endMessage: string;
  onOpenContent: (type: ContentType, id: string) => void;
  onAuthorClick: (creatorUserId: string) => void;
  /** 거르는 조건이 걸려 있을 때만 넘긴다 — 없으면 빈 상태에 `필터 지우기`가 없다(눌러도 아무 일도 안 일어난다). */
  onFiltersClear?: () => void;
  onRetry: () => void;
};

/** 로딩·전면실패·빈·성공 네 갈래를 **early return 순서**로 강제한다. 참고 모델:
 * `pages/favorites/ui/FavoritesPage.tsx`의 `FavoritesBody`. 라이브 영역 문구(`toHomeListStatus`)도 같은 순서다. */
function HomeContentBody({
  query,
  isPending,
  items,
  thumbnailAspect,
  sentinelRef,
  endMessage,
  onOpenContent,
  onAuthorClick,
  onFiltersClear,
  onRetry,
}: HomeContentBodyProps) {
  if (isPending) {
    return (
      <ContentCardGrid thumbnailAspect={thumbnailAspect}>
        {Array.from({ length: 8 }, (_, index) => (
          <ContentCardSkeleton key={index} thumbnailAspect={thumbnailAspect} metrics={{ viewCount: 0 }} />
        ))}
      </ContentCardGrid>
    );
  }

  if (query.isError && items.length === 0) {
    // 보여 줄 것이 없는 실패라 `다시 시도`가 이 화면의 유일한 앞길이다 — 그래서 기본 크기다(빈 상태 액션
    // 규칙과 같은 이유). 보통은 누르는 순간 쿼리가 `isPending`으로 돌아가 이 패널 대신 스켈레톤이 진행을
    // 보여 준다. 패널이 남는 건 데이터는 있는데 0건인 채로 백그라운드 재요청이 실패한 드문 경우뿐이고, 그때의
    // 재요청 진행을 `aria-disabled` + 스피너로 알린다. `disabled`는 누르는 순간 포커스를 날려 쓰지 않는다.
    const isRetrying = query.isRefetching;
    return (
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
        <Button
          type="button"
          variant="outline"
          aria-disabled={isRetrying}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (isRetrying) return;
            onRetry();
          }}
        >
          {isRetrying && <Loader2 aria-hidden className="animate-spin" />}
          다시 시도
        </Button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <ContentListEmptyState
        message={HOME_EMPTY_MESSAGE}
        action={
          onFiltersClear && (
            <Button type="button" variant="outline" onClick={onFiltersClear}>
              필터 지우기
            </Button>
          )
        }
      />
    );
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

      {/* 끝 표시는 남은 페이지가 없을 때만 — 바로 아래가 사이트 푸터라 "더 없음"을 말하지 않으면 목록이 끊긴
          건지 끝난 건지 갈리지 않는다. 스피너는 진행 표시라 `motion-safe`로 가드하지 않는다. */}
      <div ref={sentinelRef} className="flex justify-center py-4">
        {query.isFetchingNextPage && <Loader2 aria-hidden className="size-5 animate-spin text-muted-foreground" />}
        {!query.hasNextPage && <p className="text-xs text-muted-foreground">{endMessage}</p>}
      </div>
    </>
  );
}
