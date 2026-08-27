import { useRef, type RefObject } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate } from "@tanstack/react-router";

import {
  ContentCard,
  ContentListEmptyState,
  isVisibilityFilter,
  useProfileContentListQuery,
  VISIBILITY_FILTER_LABEL,
  VISIBILITY_FILTER_OPTIONS,
  type ContentCardTag,
  type VisibilityFilter,
} from "@/entities/content";
import { useDraftListQuery } from "@/entities/draft";
import { useContentDetailModal } from "@/shared/lib/content-detail-modal/useContentDetailModal";

import { filterMyWorks, formatMyWorkUpdatedAt, mergeMyWorks, type MyWorkItem } from "../model/myWorkItems";
import {
  isMyWorksSort,
  isMyWorkTypeFilter,
  MY_WORK_TYPE_FILTERS,
  MY_WORKS_SORTS,
  resolveMyWorksSearch,
  type MyWorksSearch,
  type MyWorksSort,
  type MyWorkTypeFilter,
} from "../model/myWorksSearch";
import { MyWorkCardMenu } from "./MyWorkCardMenu";

const TYPE_FILTER_LABEL: Record<MyWorkTypeFilter, string> = {
  all: "전체",
  character: "캐릭터",
  story: "스토리",
  unpublished: "미등록",
};

// 라벨은 `TYPE_FILTER_LABEL` 한 곳에만 적고, 항목 목록·순서는 model의 `MY_WORK_TYPE_FILTERS` 하나를
// 쓴다 — 칩과 건수 문장(`describeFilter`)이 같은 말을 쓰게 하려면 목록을 따로 적을 수 없다
// (`entities/content/model/visibilityFilter.ts`가 같은 형태).
const TYPE_FILTER_OPTIONS: { value: MyWorkTypeFilter; label: string }[] = MY_WORK_TYPE_FILTERS.map(
  (value) => ({ value, label: TYPE_FILTER_LABEL[value] }),
);

/** 공개여부 축이 좁혀지지 않았을 때 트리거에 띄우는 말. 고른 값("전체")을 그대로 쓰지 않는 이유는
 * 바로 옆 칩에도 `전체`가 있어 같은 단어가 나란히 두 개면 무엇의 전체인지 읽히지 않아서다.
 * 나머지 셋은 `VISIBILITY_FILTER_LABEL`을 그대로 쓴다 — 여기서 다시 적으면 프로필의 같은 필터와
 * 문구가 갈릴 수 있다. */
const VISIBILITY_AXIS_LABEL = "공개 여부";

/** 이번 범위의 정렬은 최신순 하나뿐이고(US-009), 그건 `mergeMyWorks`가 이미 하는 일이다 — 컨트롤은
 * 그 사실을 말할 뿐 아무것도 바꾸지 않는다. 두 번째 옵션을 넣을 땐 값이 `mergeMyWorks`까지 닿아야 한다. */
const SORT_LABEL: Record<MyWorksSort, string> = { latest: "최신순" };

const SORT_OPTIONS: { value: MyWorksSort; label: string }[] = MY_WORKS_SORTS.map((value) => ({
  value,
  label: SORT_LABEL[value],
}));

type MyWorksPageProps = {
  userId: string;
  search: MyWorksSearch;
  onSearchChange: (patch: Partial<MyWorksSearch>) => void;
};

/** prd-creator-entry-and-my-works.md US-008 — 발행 여부와 상관없이 내가 만든 것을 한 화면에서 본다.
 * 서버에는 둘을 합쳐 주는 엔드포인트가 없어 캐릭터·스토리 발행작(`GET /users/{me}/contents`)과
 * 초안(`GET /me/drafts`)을 각각 받아 클라이언트에서 병합한다(확정 결정 9). */
export function MyWorksPage({ userId, search, onSearchChange }: MyWorksPageProps) {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      {/* 제목과 버튼은 접지 않고 한 줄에 둔다 — 390px 실측으로 `내 작품` 65.38px + `작품 만들기`
          85.92px = 151.3px이라 본문 342px의 44%다(최악인 320px에서도 간격 120.7px이 남는다). 버튼은
          `Button`의 base가 이미 `shrink-0`이라 제목이 먼저 줄어들고, 제목은 2어절이라 접힐 자리도 없다. */}
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">내 작품</h1>
        <CreateWorkButton />
      </div>

      <MyWorksBody userId={userId} search={search} onSearchChange={onSearchChange} />
    </main>
  );
}

/** US-011 — 만들기 진입점. 페이지 제목 옆과 "작품 0건" 빈 상태 두 곳이 쓰므로 목적지를 한 곳에만
 * 적는다. `primary` 솔리드는 DESIGN.md §2가 못박은 이 시스템의 **유일한 유채색 솔리드 채움**이라
 * 이 자리(화면의 유일한 앞길)에 정확히 해당한다.
 *
 * **두 자리를 크기가 아니라 라벨로 가른다.** 처음엔 빈 상태 쪽을 `size="lg"`로 올렸는데 (1) `lg`는
 * `default`와 패딩이 같아 두 버튼 폭이 85.92px로 **완전히 동일**하고 높이만 32→36(+4px)이라 위계가
 * 아니라 정렬 오차로 읽히고 (2) 앱의 다른 `size="lg"` 11곳은 전부 `h-10`/`h-12`로 높이를 덮어써
 * 36px은 존재하지 않는 티어이며 (3) 라벨·역할·목적지가 모두 같아 빈 상태 탭 스톱 8개 중 2개가
 * 스크린리더에 `링크, 작품 만들기`로 연달아 읽혔다(실측). 라벨을 가르면 셋이 한 번에 풀린다.
 *
 * 빈 상태 라벨이 `첫`이 아니라 **`새`**인 이유: `첫`은 서수를 주장하는데 이 화면에 도달하는 경로 둘이
 * 그걸 거짓으로 만든다 — (a) 발행작 두 쿼리가 실패하고 초안만 `[]`로 성공하면 작품 32건을 가진
 * 사용자가 이 패널을 본다 (b) US-007 지연 생성으로 만든 초안을 전부 지우고 돌아온 사용자도 본다.
 * `새`는 순수 수식어라 모든 분기에서 참이고, 폭도 101.44px로 `첫`과 픽셀 단위로 같다(실측). */
function CreateWorkButton({ label = "작품 만들기" }: { label?: string }) {
  return (
    <Button asChild>
      <Link to="/builder">{label}</Link>
    </Button>
  );
}

type MyWorksBodyProps = {
  userId: string;
  search: MyWorksSearch;
  onSearchChange: (patch: Partial<MyWorksSearch>) => void;
};

/** 세 쿼리를 합치는 화면이라 상태가 배타적이지 않다 — 하나는 실패하고 하나는 아직 로딩일 수 있다.
 * 그래서 조건부 렌더 나열이 아니라 early return으로 순서를 강제하고, **일부만 실패하면 성공한 목록은
 * 그대로 보여준다**(안 그러면 초안 엔드포인트 하나가 흔들릴 때 발행작 32건이 함께 사라진다 — 실측).
 *
 * 필터·정렬 툴바는 마지막 분기(볼 것이 하나라도 있는 상태)에서만 렌더한다 — 걸러낼 대상이 없는
 * 로딩·전면에러·"작품 0건" 화면에서 필터를 띄우면 아무 데도 닿지 않는 컨트롤이 된다. */
function MyWorksBody({ userId, search, onSearchChange }: MyWorksBodyProps) {
  const characterQuery = useProfileContentListQuery({ userId, type: "character" });
  const storyQuery = useProfileContentListQuery({ userId, type: "story" });
  const draftListQuery = useDraftListQuery();
  const typeFilterRef = useRef<HTMLDivElement>(null);

  const queries = [characterQuery, storyQuery, draftListQuery];
  const failedQueries = queries.filter((query) => query.isError);

  const handleRetryFailed = () => {
    for (const query of failedQueries) query.refetch();
  };

  // 빈 상태의 버튼들은 **자기가 속한 패널을 언마운트시킨다**. 먼저 포커스를 툴바로 옮겨 두지 않으면
  // `activeElement`가 `<body>`로 떨어져 다음 Tab이 헤더 워드마크부터 다시 시작한다(실측 — WCAG 2.4.3).
  // 툴바는 이 분기들에서 계속 살아 있으므로 대상이 항상 존재한다. 상태 변경 **전에** 동기로 옮기고
  // `[data-state=on]`이 아니라 **곧 켜질 칩**을 값으로 집는 이유: 라우터 내비게이션 후의 커밋 시점에
  // 기대지 않으면서도, 방금 지운 조건("캐릭터, 선택 안 됨")이 아니라 결과를 읽히게 하기 위해서다.
  const focusTypeFilter = (value: MyWorkTypeFilter) => {
    typeFilterRef.current?.querySelector<HTMLElement>(`[data-filter="${value}"]`)?.focus();
  };

  if (failedQueries.length === queries.length) {
    return <MyWorksFullErrorState onRetry={handleRetryFailed} />;
  }

  // `failureCount === 0`을 함께 보는 이유: 한 번이라도 실패해 재시도 백오프에 들어간 쿼리는 그동안 계속
  // `isPending`이라, 그것만 보면 이미 도착한 발행작 32건이 **7.07초**(retry 3회 1s→2s→4s) 동안 스켈레톤
  // 뒤에 갇힌다(실측). 첫 실패 순간 스켈레톤을 걷고, 백오프가 끝나 `isError`가 되면 아래 알림 배너가 붙는다.
  if (queries.some((query) => query.isPending && query.failureCount === 0)) return <MyWorksSkeleton />;

  const items = mergeMyWorks(
    [...(characterQuery.data?.items ?? []), ...(storyQuery.data?.items ?? [])],
    draftListQuery.data?.items ?? [],
  );

  // 부분 실패 알림은 목록이 0건인 분기에도 똑같이 필요하다 — 빠뜨리면 발행작 32건을 가진 사용자에게
  // 실패 사실은 감춘 채 "아직 만든 작품이 없어요"라고 말하게 된다(발행작 두 쿼리 실패 + 초안 `[]` 성공).
  const errorBanner =
    failedQueries.length > 0 ? (
      <MyWorksErrorState
        message={
          draftListQuery.isError
            ? "초안을 불러오지 못했어요. 발행한 작품만 보여주고 있어요."
            : "일부 작품을 불러오지 못했어요."
        }
        onRetry={handleRetryFailed}
      />
    ) : undefined;

  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        {errorBanner}
        {/* 이 화면에서 유일하게 할 수 있는 일이 만들기다 — 상태 통보("없어요")로 끝내면 막다른 길이
            되므로 남은 한 줄은 무엇이 만들어지고 어디에 쌓이는지를 말한다(US-011).
            제목은 **부분 실패가 없을 때만** 단다: 발행작 두 쿼리가 실패하고 초안만 `[]`로 성공하면
            여기 도달하는데(위 배너 주석의 그 상황), 그때 "아직 만든 작품이 없어요"는 거짓일 수 있다.
            한 줄 안내로 남기는 건 몰라도 배너가 반박하는 문장을 굵은 제목으로 승격시키지는 않는다. */}
        <ContentListEmptyState
          title={errorBanner ? undefined : "아직 만든 작품이 없어요"}
          message="캐릭터나 스토리를 만들면 여기에 모여요."
          action={<CreateWorkButton label="새 작품 만들기" />}
        />
      </div>
    );
  }

  const { type: typeFilter, visibility: visibilityFilter, sort } = resolveMyWorksSearch(search);
  const visibleItems = filterMyWorks(items, { type: typeFilter, visibility: visibilityFilter });

  return (
    <div className="flex flex-col gap-6">
      {errorBanner}

      <MyWorksToolbar
        typeFilterRef={typeFilterRef}
        typeFilter={typeFilter}
        visibilityFilter={visibilityFilter}
        sort={sort}
        count={visibleItems.length}
        onSearchChange={onSearchChange}
      />

      {visibleItems.length === 0 ? (
        <MyWorksEmptyResult
          isFiltered={typeFilter !== "all" || visibilityFilter !== "all"}
          filterLabel={describeFilter(typeFilter, visibilityFilter)}
          onResetFilter={() => {
            focusTypeFilter("all");
            onSearchChange({ type: undefined, visibility: undefined });
          }}
          onShowUnpublished={() => {
            focusTypeFilter("unpublished");
            onSearchChange({ type: "unpublished", visibility: undefined });
          }}
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          {visibleItems.map((item, index) => (
            <MyWorkCard
              key={`${item.kind}-${item.id}`}
              item={item}
              userId={userId}
              priority={index < 4}
              isLcpCandidate={index === 0}
            />
          ))}
        </div>
      )}
    </div>
  );
}

type MyWorksEmptyResultProps = {
  isFiltered: boolean;
  filterLabel: string;
  onResetFilter: () => void;
  onShowUnpublished: () => void;
};

/**
 * 목록에 볼 것이 있는데 지금 조건으로는 0건일 때. **두 경우가 서로 다른 문장과 다른 다음 행동을 가져야
 * 한다** — 문구만 다르고 할 수 있는 게 같으면 그 구분은 화면에서 아무 일도 하지 않는다.
 *
 * 필터가 하나도 안 걸렸는데 0건이면 가진 게 **초안뿐**이라는 뜻이다(`전체`는 FR-18에 따라 발행작만
 * 센다). US-007의 지연 생성 이후 이건 엣지가 아니라 **모든 신규 창작자의 첫 화면**이다. 그때 "조건에
 * 맞는 작품이 없어요" + `필터 모두 해제`를 띄우면 (1) 걸린 조건이 없으니 거짓말이고 (2) 유일한 탈출구가
 * 이미 해제 상태라 아무 일도 하지 않으며 (3) 초안이 `미등록`에 멀쩡히 있다는 사실을 말하지 않는다
 * (실측: 발행작 응답을 비우면 `전체 0건` + 죽은 버튼). `미등록 보기`는 이 분기에 도달한 이상 항상
 * 1건 이상으로 간다.
 */
function MyWorksEmptyResult({
  isFiltered,
  filterLabel,
  onResetFilter,
  onShowUnpublished,
}: MyWorksEmptyResultProps) {
  if (!isFiltered) {
    return (
      <ContentListEmptyState
        message="아직 발행한 작품이 없어요."
        action={
          // `size="sm"`(28px)이 아닌 이유: 이 버튼은 US-007 지연 생성 이후 **모든 신규 창작자의
          // 첫 화면**에서 유일한 앞길인데, 190px 패널 한가운데 28px 보조 액션으로 놓이면 위계가
          // 실제 역할과 어긋난다. `primary` 솔리드는 US-011의 `작품 만들기`가 가져갈 자리라
          // 채움이 아니라 크기로만 올린다.
          <Button type="button" variant="outline" onClick={onShowUnpublished}>
            미등록 보기
          </Button>
        }
      />
    );
  }

  // 패널 밖 건수 줄에만 조건이 적혀 있으면, 공유 URL로 이 화면에 바로 도착한 사람에게 패널이
  // "조건"이라는 대명사만 말하게 된다. 같은 문장을 패널 안에서 한 번 더 완결시킨다.
  return (
    <ContentListEmptyState
      message={`${filterLabel}에 해당하는 작품이 없어요.`}
      action={
        <Button type="button" variant="outline" onClick={onResetFilter}>
          필터 모두 해제
        </Button>
      }
    />
  );
}

type MyWorksToolbarProps = {
  typeFilterRef: RefObject<HTMLDivElement | null>;
  typeFilter: MyWorkTypeFilter;
  visibilityFilter: VisibilityFilter;
  sort: MyWorksSort;
  count: number;
  onSearchChange: (patch: Partial<MyWorksSearch>) => void;
};

/** US-009 — 필터 칩 한 줄(작품 종류 + 공개 여부)과 그 아래 결과 수 · 정렬.
 *
 * 종류 칩은 `Button`을 손으로 조립하지 않고 `ToggleGroup variant="outline" size="sm"`을 쓴다 —
 * DESIGN.md §Toggles가 단일선택 칩을 `toggleVariants` 한 곳에서만 정의하도록 못박았고(선택 상태는
 * `primary` 솔리드), "호출부에 선택 상태 클래스를 직접 붙이지 말 것"까지 명시한다. 홈의 장르 필터와
 * 프로필의 공개여부 필터가 이미 같은 프리미티브다. `apps/web/CLAUDE.md`의 `Button variant="secondary"
 * rounded-full` 레시피는 **선택 상태가 없는 클릭 칩**(제안 답장)용이라 여기 쓰면 선택 표현을 호출부에서
 * 새로 발명해야 한다. */
function MyWorksToolbar({
  typeFilterRef,
  typeFilter,
  visibilityFilter,
  sort,
  count,
  onSearchChange,
}: MyWorksToolbarProps) {
  return (
    // 툴바 안쪽은 `gap-2`, 툴바와 목록 사이는 `gap-6`(`MyWorksBody`) — 두 값이 4px밖에 안 벌어져 있으면
    // 건수 줄이 툴바의 꼬리인지 목록의 머리글인지 읽히지 않는다(실측: 12px vs 16px이었다).
    <div className="flex flex-col gap-2">
      {/* 칩이 한 줄에 못 들어가면 접지 않고 가로로 흘린다(제안 답장 칩과 같은 관용구). `-m-1 p-1`은
          focus 링(3px)이 잘리지 않게 하는 여백이다 — `overflow-x: auto`는 **네 방향 모두** 클립하고,
          첫 칩은 스크롤 컨테이너의 좌측 경계에 딱 붙어 있어 링이 통째로 사라진다(픽셀 실측: 패딩 없이는
          링 밴드가 rest와 완전히 같은 색, 홈의 같은 칩은 링이 보인다). 음수 마진이 그 패딩을 되돌린다. */}
      <div
        // 축 사이는 `gap-6`(24px), 칩 사이는 `gap-2`(8px, ToggleGroup 기본) — 잉크를 더하지 않고
        // 근접성만으로 축을 가른다. **3배여야 갈린다**: 처음엔 `gap-3`(12px)이었는데 1.5배는
        // Gestalt 임계 아래라 셸이 픽셀 단위로 같은(높이 28·radius·보더 전부 Δ0.0000) 다섯 컨트롤이
        // "한 축 5선택지"로 읽혔다. 바로 아래 건수 줄이 이미 같은 논리로 8 vs 24를 쓰고 있다.
        className="-m-1 flex gap-6 overflow-x-auto p-1 scroll-p-1"
        // 스크롤 줄 안의 컨트롤로 Tab 해도 브라우저가 가로로 끌어와 주지 않는다 — 320px에서 `공개 여부`가
        // 60px 잘린 채 포커스만 옮겨 갔다(실측: `scrollLeft` 0 고정, `scrollIntoView`는 정상 동작).
        // `event.target`은 실제로 포커스를 받은 컨트롤이다(React는 이 자리를 컨테이너 타입으로 보지만
        // 둘 다 `scrollIntoView`를 갖고 있어 결과는 같다). 이미 보이면 no-op이다.
        // Radix `SelectContent`는 body로 포털되지만 React 합성 이벤트는 컴포넌트 트리를 타고 올라와,
        // 드롭다운이 열리며 `SelectItem`이 포커스를 받는 순간에도 이 핸들러가 불린다(실측: 항목의
        // `inRow`가 false). 그 요소를 끌어오면 드롭다운 정렬이나 페이지가 함께 움직이므로 줄 안쪽으로
        // 한정한다(`apps/web/CLAUDE.md`의 "클릭 카드"가 같은 현상을 dropdown에서 기록해 뒀다).
        onFocus={(event) => {
          if (!event.currentTarget.contains(event.target)) return;
          event.target.scrollIntoView({ block: "nearest", inline: "nearest" });
        }}
      >
        <ToggleGroup
          ref={typeFilterRef}
          type="single"
          variant="outline"
          size="sm"
          value={typeFilter}
          onValueChange={(value) => {
            if (!isMyWorkTypeFilter(value)) return;
            // 공개범위는 항상 **정규화된 값**으로 다시 쓴다. 초안에는 그 축이 없어 미등록으로 갈 땐
            // 비우고, 미등록에서 나올 땐 `visibilityFilter`가 이미 `all`이라 역시 비워진다 — 그래야
            // 손으로 만든 `?type=unpublished&visibility=private`의 죽은 파라미터가 `전체`를 누르는
            // 순간 되살아나지 않는다(실측: 전체를 눌렀는데 `비공개 2건`이 됐다).
            onSearchChange({
              type: value === "all" ? undefined : value,
              visibility:
                value === "unpublished" || visibilityFilter === "all" ? undefined : visibilityFilter,
            });
          }}
          aria-label="작품 종류 필터"
          className="shrink-0"
        >
          {TYPE_FILTER_OPTIONS.map((option) => (
            // `data-filter`는 빈 상태에서 되돌아올 때 포커스를 이 칩으로 정확히 옮기기 위한 표식이다
            // (Radix는 `value`를 DOM에 남기지 않는다).
            <ToggleGroupItem key={option.value} value={option.value} data-filter={option.value}>
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        {/* 미등록(초안)에는 공개범위 축이 **존재하지 않는다** — 쓸 수 없는 컨트롤이 아니라 해당 없는
            축이라 `disabled`가 아니라 아예 렌더하지 않는다. `disabled:opacity-50`은 이 팔레트에서
            보더를 1.1658:1(다크)까지 떨어뜨려 "비활성"이 아니라 렌더링 사고처럼 보이기도 한다(실측).
            축이 빠졌다는 사실은 아래 건수 라벨이 `미등록 1건`으로 이미 말한다. */}
        {typeFilter !== "unpublished" && (
          <Select
            // `all`은 빈 값으로 넘긴다 — 그래야 `SelectValue`가 placeholder("공개 여부")를 띄운다.
            // 목록의 `전체` 항목은 그대로 두고, 고르면 파라미터를 지워 다시 빈 값으로 돌아온다.
            value={visibilityFilter === "all" ? "" : visibilityFilter}
            onValueChange={(value) => {
              if (!isVisibilityFilter(value)) return;
              onSearchChange({ visibility: value === "all" ? undefined : value });
            }}
          >
            {/* 트리거 안에는 반드시 `SelectValue`가 있어야 한다 — 직접 텍스트를 넣으면 Radix가 열린
                콘텐츠로 포커스를 옮기지 못해 키보드로도 마우스로도 항목을 고를 수 없다(브라우저 실측).
                축 이름은 `aria-label`로 함께 넘긴다(`aria-label`이 내용을 덮으므로 값도 같이 담는다). */}
            {/* 값이 걸리면 채움을 준다. 안 그러면 이 트리거는 **미선택 칩과 픽셀상 같아서**(높이·radius·
                보더·배경 전부 Δ0.0000 — 실측) 목록을 32→1건으로 줄인 축이 꺼진 칩처럼 보이고, 정작
                아무것도 안 거른 `전체` 칩만 핑크로 켜져 활성 표현이 뒤집힌다. `secondary`인 이유:
                DESIGN.md §Neutral이 이 토큰의 쓰임을 "hover/선택 배경, 배지, 필터 칩"으로 명시했고,
                무채색이라 화면의 유일한 유채색 솔리드 채움(활성 칩)을 늘리지 않는다. 칩과 형태로도
                갈린다 — 칩은 핑크 채움, 이쪽은 무채색 채움 + 셰브론. */}
            <SelectTrigger
              size="sm"
              className={cn("shrink-0", visibilityFilter !== "all" && "bg-secondary")}
              aria-label={
                visibilityFilter === "all"
                  ? VISIBILITY_AXIS_LABEL
                  : `${VISIBILITY_AXIS_LABEL}: ${VISIBILITY_FILTER_LABEL[visibilityFilter]}`
              }
            >
              <SelectValue placeholder={VISIBILITY_AXIS_LABEL} />
            </SelectTrigger>
            <SelectContent>
              {VISIBILITY_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div className="flex items-center justify-between gap-3">
        {/* 필터는 화면의 **다른 곳**을 바꾸는 컨트롤이라 결과가 announce되지 않으면 스크린리더
            사용자는 목록까지 내려가 직접 세야 한다. 이 문장은 걸린 축을 전부 이름으로 담고 있어
            그대로 읽히면 완결된 문장이 된다(`캐릭터 · 비공개 1건`).

            `aria-atomic`이 없으면 **바뀐 조각만** 읽힌다 — JSX가 이 문장을 텍스트 노드 4개
            (`캐릭터` / ` ` / `2` / `건`)로 쪼개 놓아서, `전체 32건` → `캐릭터 2건` 전환의 뮤테이션은
            `캐릭터`와 `2` 둘뿐이고 단위 `건`은 목록에 없다(MutationObserver 실측). 문장을 통째로
            다시 읽게 해야 "캐릭터 2건"이 된다. */}
        <p aria-live="polite" aria-atomic className="text-sm text-muted-foreground">
          {describeFilter(typeFilter, visibilityFilter)} {count}건
        </p>

        <Select
          value={sort}
          onValueChange={(value) => {
            // 세 축이 같은 규칙을 쓴다 — 기본값은 URL에 싣지 않는다(`myWorksSearch.ts`). 지금은 옵션이
            // 하나뿐이라 Radix가 재선택에서 이 콜백을 부르지도 않지만, 두 번째 옵션이 붙는 순간
            // "최신순으로 되돌리기"가 `?sort=latest`를 남기게 된다.
            if (isMyWorksSort(value)) onSearchChange({ sort: value === "latest" ? undefined : value });
          }}
        >
          {/* 축 이름을 눈에도 보이게 둔다 — `aria-label`에만 있으면 보는 사람에게는 `최신순`이
              둘째 줄 우측 끝에 홀로 뜬 정체불명 컨트롤이 된다. 옵션이 하나뿐인 지금은 이 트리거가
              고를 것을 약속하고 주지 않는데, 축 이름이 붙으면 "고르시오"가 아니라 "지금 이렇게
              정렬돼 있다"는 **사실 진술**로 읽힌다. 폭은 78.3 → 109.6px이고 390px에서 건수 라벨까지
              101.2px가 남아 이 줄에는 여유가 충분하다(칩 줄이 아니다 — 실측).
              `SelectValue`를 텍스트로 **대체**하면 안 되고 형제로만 둔다: Radix의 `item-aligned`가
              `valueNode`를 기다리다 포지셔닝·포커스 이관을 아예 못 해 마우스로도 키보드로도 못 고르는
              드롭다운이 된다(`apps/web/CLAUDE.md`). */}
          <SelectTrigger size="sm" aria-label={`정렬: ${SORT_LABEL[sort]}`}>
            <span className="text-muted-foreground">정렬</span>
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
    </div>
  );
}

/** 건수 앞에 걸려 있는 축을 전부 이름으로 적는다 — 좁혀 놓고 "전체 0건"이라고 하면 작품이 하나도 없는
 * 것처럼 읽힌다(실제로는 32건이 있고 그중 비공개가 0건인 상태다). 아무것도 안 걸렸을 때만 "전체"다. */
function describeFilter(typeFilter: MyWorkTypeFilter, visibilityFilter: VisibilityFilter): string {
  const axes: string[] = [];
  if (typeFilter !== "all") axes.push(TYPE_FILTER_LABEL[typeFilter]);
  if (visibilityFilter !== "all") axes.push(VISIBILITY_FILTER_LABEL[visibilityFilter]);

  return axes.length === 0 ? "전체" : axes.join(" · ");
}

type MyWorkCardProps = {
  item: MyWorkItem;
  userId: string;
  priority: boolean;
  isLcpCandidate: boolean;
};

/** 발행작은 홈·프로필과 같은 상세 모달로, 초안은 이어 쓰던 빌더로 간다. 초안이 `<Link>`가 아닌 이유는
 * 한 그리드 안에서 발행작 카드가 라우터를 우회하는 모달(`useContentDetailModal`)이라 링크가 될 수 없고,
 * 카드 안에 다른 동작을 넣을 자리(US-010의 ⋯ 메뉴)가 `role="button"` 패턴을 요구하기 때문이다. */
function MyWorkCard({ item, userId, priority, isLcpCandidate }: MyWorkCardProps) {
  const navigate = useNavigate();
  const { open } = useContentDetailModal();

  // 초안은 이름이 비어 있는 게 정상 상태다 — US-007의 지연 생성은 사용자가 이름을 넣기 전에도 초안을
  // 만든다. 폴백을 공용 `ContentCard`가 아니라 여기 두는 이유: 홈·즐겨찾기·프로필에는 이름 없는
  // 발행작이 올 수 없어서, 공용 쪽에 넣으면 그쪽의 진짜 결함을 조용히 가리게 된다.
  // 카드와 "⋯"가 **같은** 문자열을 쓰는 이유는 WCAG 2.5.3(보이는 이름과 접근가능 이름 일치)이다 —
  // 무명 초안끼리의 구별과는 별개 문제다(`MyWorkCardMenu`의 `title` prop 주석 참고).
  const title = item.kind === "draft" ? item.name || "제목 없는 초안" : item.name;

  return (
    <ContentCard
      thumbnailUrl={item.thumbnailUrl}
      title={title}
      metrics={
        item.kind === "published"
          ? { viewCount: item.viewCount, chatCount: item.chatCount, likeCount: item.likeCount }
          : undefined
      }
      // 초안에만 수정일을 단다 — 발행작의 `updatedAt`은 마지막 **발행** 시각이라(확정 결정 1)
      // 같은 "수정" 라벨을 붙이면 거짓말이 된다.
      metaLabel={item.kind === "draft" ? `${formatMyWorkUpdatedAt(item.updatedAt)} 수정` : undefined}
      tags={toTags(item)}
      actions={<MyWorkCardMenu item={item} title={title} userId={userId} />}
      priority={priority}
      isLcpCandidate={isLcpCandidate}
      onClick={() => {
        if (item.kind === "published") {
          open(item.type, item.id);
          return;
        }
        void navigate({ to: "/builder/$type/$draftId", params: { type: item.type, draftId: item.id } });
      }}
    />
  );
}

function toTags(item: MyWorkItem): ContentCardTag[] {
  // 초안에는 공개범위가 없다 — 배지는 "미등록" 하나뿐이다(확정 결정 6).
  return item.kind === "published" ? [item.type, item.visibility] : [item.type, "unpublished"];
}

/** 실제 카드 구조(썸네일 웰 + 제목 + 한 줄 + 배지)를 그대로 흉내 낸다 — `aspect-[3/4]` 한 장짜리
 * 스켈레톤은 390px에서 실제 카드보다 45.5px 짧아 목록이 도착할 때 2행이 46px, 3행이 91px씩 밀렸다(실측).
 *
 * `role="status"`가 있어야 `aria-label`이 읽힌다 — 암묵 role(generic)에 붙인 `aria-label`은 ARIA 1.2가
 * 금지하는 조합이라 스크린리더가 대개 무시한다(a11y 트리 실측). */
function MyWorksSkeleton() {
  return (
    <div
      role="status"
      aria-busy
      aria-label="내 작품 목록 불러오는 중"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
    >
      {[0, 1, 2, 3, 4, 5, 6, 7].map((key) => (
        <div
          key={key}
          className="flex flex-col gap-3 rounded-xl border border-border bg-background p-3 motion-safe:animate-pulse"
        >
          <div className="aspect-square rounded-lg bg-muted" />
          <div className="flex flex-col gap-1.5">
            {/* 28 / 16 / 22.5px는 실제 카드의 제목 줄 · 한 줄(text-xs) · 배지 행 높이다. 제목 줄이
                20이 아니라 28인 이유는 US-010의 ⋯ 버튼(`size-7`)이 그 행의 높이를 잡기 때문이다 —
                `h-5`로 두면 목록이 도착할 때 행마다 8px씩 누적해 밀린다(실측). */}
            <div className="h-7 w-3/4 rounded bg-muted" />
            <div className="h-4 w-1/2 rounded bg-muted" />
            <div className="h-5.5 w-2/3 rounded-full bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** 목록 일부만 실패했을 때 목록 **위에** 얹는 한 줄 알림. 아래에 볼 것이 남아 있으므로 자리를 적게 쓴다. */
function MyWorksErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3">
      <p className="text-sm text-destructive-text">{message}</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        다시 시도
      </Button>
    </div>
  );
}

/** 셋 다 실패해 목록이 통째로 없을 때. 같은 "보여줄 게 없음" 상황인 빈 상태(`ContentListEmptyState`)와
 * 같은 dashed 패널 셸을 써서 한 화면에 빈 상태 어휘가 둘이 되지 않게 한다 — **셸 클래스가 손으로
 * 복사돼 있으므로 저쪽을 고치면 여기도 함께 고쳐야 이 주석이 참으로 남는다**(US-011의 `px-6
 * break-keep`이 그렇게 갈렸다). 같은 셸의 세 번째 사본이 `GeneratedImageLibraryPanel`에 있다.
 *
 * `다시 시도`에 `size="sm"`을 주지 않는 이유는 형제 빈 상태들과 같다 — 이 패널의 유일한 앞길이
 * 복구인데 28px로 두면 바로 위 32px `primary` 솔리드 `작품 만들기`(목적지가 다른 버튼)보다 약하게
 * 읽힌다(`apps/web/CLAUDE.md`의 빈 상태 액션 규칙). 한 줄 배너인 `MyWorksErrorState`는 그대로 `sm`이다. */
function MyWorksFullErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center break-keep"
    >
      <p className="text-sm text-destructive-text">목록을 불러오지 못했어요.</p>
      <Button type="button" variant="outline" onClick={onRetry}>
        다시 시도
      </Button>
    </div>
  );
}
