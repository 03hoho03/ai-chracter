import { useId, useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";

import { ContentListEmptyState, ContentListLoadMore } from "@/entities/content";
import { useSessionQuery } from "@/entities/session";
import { useMyWorksQuery, useWorkBundlesQuery, type MyWorksParams, type WorkItem } from "@/entities/work";
import {
  clearDeletedWorkBundle,
  DeleteWorkBundleModal,
  toWorkBundleActionError,
  usePutWorkBundleItemMutation,
  useRemoveWorkBundleItemMutation,
  WorkBundleNameModal,
  WorkBundlesForWorkModal,
} from "@/features/manage-work-bundle";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";
import { UNDO_TOAST_DURATION_MS, UndoToastButton } from "@/shared/ui/UndoToastButton";

import { pickContinueWork } from "../model/continueWork";
import { resolveStudioBodyView, resolveStudioEmptyResult } from "../model/studioBodyView";
import { isStudioNovelAreaVisible } from "../model/studioNovelArea";
import { resolveStudioScope, resolveStudioSearch, type StudioScope, type StudioSearch } from "../model/studioSearch";
import { toStudioWorkTitle } from "../model/studioWorkRow";
import { StudioAddWorksModal } from "./StudioAddWorksModal";
import { StudioBackLink, StudioBundleHeader, StudioBundleHeaderSkeleton } from "./StudioBundleHeader";
import { StudioBundleMenu } from "./StudioBundleMenu";
import { StudioContinueCard, StudioContinueCardSkeleton } from "./StudioContinueCard";
import { StudioCreateTiles } from "./StudioCreateTiles";
import { describeStudioFilter, StudioToolbar } from "./StudioToolbar";
import { STUDIO_ROW_COLUMNS, StudioWorkRow } from "./StudioWorkRow";

type StudioPageProps = {
  userId: string;
  search: StudioSearch;
  onSearchChange: (patch: Partial<StudioSearch>) => void;
};

/** 조건 없는 목록. 이어 만들기 카드는 필터와 무관하게 이 목록의 첫 페이지에서 고른다 — 필터를 바꿀 때마다 카드가
 * 바뀌면 "가장 최근 일"이 아니게 된다. 필터가 없으면 아래 목록과 같은 캐시라 요청이 하나 더 나가지 않는다. */
const UNFILTERED: MyWorksParams = { type: "all", status: "all", q: undefined };

/**
 * `/studio` — 내가 만든 것과 만들 것을 한 화면에서. 위에서부터 제목 · 이어 만들기 + 새로 만들기 · 모든 작품(필터와 행
 * 목록)이다. 목록은 서버 통합 목록(`GET /me/works`) 하나라 일부만 실패하는 상태가 없다.
 *
 * `?bundle={id}` 면 같은 자리가 묶음 화면이 된다 — 제목이 묶음 이름이 되고 이어 만들기·새로 만들기·상태 셀렉트가 빠지며,
 * 목록은 그 묶음에 든 작품만이다. 묶음은 나만 보는 정리라 독자 화면 어디에도 나가지 않는다.
 *
 * 묶음 대화상자들은 이 화면에서만 열려 앱 루트가 아니라 여기 붙인다.
 *
 * 폭은 카드 목록 화면들과 같은 `max-w-list` 컬럼이다. 이어 만들기와 새로 만들기는 본문 폭이 넓을 때만 한 줄 두 열로
 * 선다 — 좌측 패널이 펴지고 접히며 본문 폭이 바뀌어 뷰포트가 아니라 컨테이너 폭으로 가른다.
 */
export function StudioPage({ userId, search, onSearchChange }: StudioPageProps) {
  const { data: session } = useSessionQuery();
  const isNovelAreaVisible = isStudioNovelAreaVisible(session?.enabledFeatures);
  const params = resolveStudioSearch(search, isNovelAreaVisible);
  const scope = resolveStudioScope(search);
  const navigate = useNavigate();

  const createBundle = async () => {
    const bundleId = await WorkBundleNameModal.call({ mode: "create" });
    // 새 묶음은 비어 있으니 홈의 필터를 들고 들어가지 않는다.
    if (bundleId !== null) await navigate({ to: "/studio", search: { bundle: bundleId } });
  };

  return (
    <main className="mx-auto flex max-w-list flex-col gap-8 px-4 sm:px-6 py-10 lg:pt-6">
      {scope.kind === "home" && (
        <>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">스튜디오</h1>
          <StudioStartSection isNovelAreaVisible={isNovelAreaVisible} />
          <StudioWorksSection
            userId={userId}
            scope={scope}
            params={params}
            isNovelAreaVisible={isNovelAreaVisible}
            onSearchChange={onSearchChange}
            onCreateBundle={() => void createBundle()}
          />
        </>
      )}
      {scope.kind === "bundle" && (
        <StudioBundleScreen
          key={scope.bundleId}
          userId={userId}
          scope={scope}
          params={params}
          isNovelAreaVisible={isNovelAreaVisible}
          onSearchChange={onSearchChange}
        />
      )}
      {scope.kind === "unreadableBundle" && <StudioBundleNotFound />}

      <WorkBundleNameModal />
      <DeleteWorkBundleModal />
      <WorkBundlesForWorkModal />
      <StudioAddWorksModal />
    </main>
  );
}

type StudioBundleScreenProps = {
  userId: string;
  scope: Extract<StudioScope, { kind: "bundle" }>;
  params: MyWorksParams;
  isNovelAreaVisible: boolean;
  onSearchChange: (patch: Partial<StudioSearch>) => void;
};

/** 묶음 화면. 묶음 이름은 내 묶음 목록에서 id 로 찾는다(묶음 하나를 따로 받는 조회가 없다). 목록에 없으면 — 지웠거나 남의
 * 묶음이거나 없는 id — 그 자리에서 찾을 수 없다고 말한다. 다른 곳(다른 탭)에서 지워 작품 목록이 404 로 돌아온 경우도 같다. */
function StudioBundleScreen({ userId, scope, params, isNovelAreaVisible, onSearchChange }: StudioBundleScreenProps) {
  const bundlesQuery = useWorkBundlesQuery();
  const worksQuery = useMyWorksQuery(params);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const bundle = bundlesQuery.data?.items.find((candidate) => candidate.id === scope.bundleId);
  const isWorksBundleGone = toWorkBundleActionError(worksQuery.error, "addItem")?.kind === "bundleGone";

  if ((bundlesQuery.isSuccess && bundle === undefined) || isWorksBundleGone) return <StudioBundleNotFound />;

  const deleteBundle = async (name: string) => {
    const isDeleted = await DeleteWorkBundleModal.call({ bundleId: scope.bundleId, name });
    if (!isDeleted) return;
    // 화면을 먼저 옮긴다 — 캐시를 먼저 비우면 이 화면이 다시 받아 "찾을 수 없어요"를 한 번 그린다.
    await navigate({ from: "/studio/", to: "/studio", search: (previous) => ({ ...previous, bundle: undefined }), replace: true });
    clearDeletedWorkBundle(queryClient, scope.bundleId);
  };

  return (
    <>
      <div className="flex flex-col gap-3">
        <StudioBackLink />
        {bundle !== undefined && (
          <StudioBundleHeader
            bundle={bundle}
            onAddWorks={() => void StudioAddWorksModal.call({ bundleId: bundle.id, bundleName: bundle.name })}
            onRename={() =>
              void WorkBundleNameModal.call({ mode: "rename", bundleId: bundle.id, currentName: bundle.name })
            }
            onDelete={() => void deleteBundle(bundle.name)}
          />
        )}
        {bundlesQuery.isError && bundle === undefined && (
          <div role="alert" className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">묶음</h1>
            <p className="text-sm text-destructive-text">묶음 이름을 불러오지 못했어요.</p>
            <RetryButton isBusy={bundlesQuery.isFetching} onRetry={() => void bundlesQuery.refetch()} />
          </div>
        )}
        {bundlesQuery.isPending && <StudioBundleHeaderSkeleton />}
      </div>
      <StudioWorksSection
        userId={userId}
        scope={scope}
        params={params}
        isNovelAreaVisible={isNovelAreaVisible}
        onSearchChange={onSearchChange}
        onAddWorks={
          bundle === undefined
            ? undefined
            : () => void StudioAddWorksModal.call({ bundleId: bundle.id, bundleName: bundle.name })
        }
      />
    </>
  );
}

/** 읽을 수 없는·지운·남의 묶음 주소. 다른 곳으로 저절로 옮기지 않는다 — 무엇이 일어났는지 읽히고 돌아갈 길 하나를 준다. */
function StudioBundleNotFound() {
  return (
    <>
      <h1 className="text-2xl font-bold tracking-tight text-foreground">스튜디오</h1>
      <ContentListEmptyState
        title="이 묶음을 찾을 수 없어요"
        message="지워졌거나 주소가 바뀐 묶음이에요."
        action={
          <Button asChild variant="outline">
            <Link from="/studio/" to="/studio" search={(previous) => ({ ...previous, bundle: undefined })}>
              스튜디오로
            </Link>
          </Button>
        }
      />
    </>
  );
}

/** 묶음에서 확인 없이 빼고 되돌리기를 내민다. 빼기는 소속만 지우는 가벼운 일이고 되돌리기로 그대로 되살린다.
 *
 * 되돌리기는 다시 넣기라 재동의 전 계정에서는 막힌다 — 그때는 전역 재동의 모달이 뜬다. */
function useRemoveFromBundleWithUndo(bundleId: string | undefined, onRemoved: () => void) {
  const removeMutation = useRemoveWorkBundleItemMutation();
  const putMutation = usePutWorkBundleItemMutation();

  if (bundleId === undefined) return undefined;

  return (item: WorkItem) => {
    const work = { kind: item.kind, id: item.id };
    const title = toStudioWorkTitle(item);
    removeMutation.mutate(
      { bundleId, work },
      {
        onSuccess: () => {
          onRemoved();
          toast(`‘${title}’${koreanParticle(title, "을/를")} 이 묶음에서 뺐어요`, {
            duration: UNDO_TOAST_DURATION_MS,
            action: (
              <UndoToastButton
                onClick={() =>
                  putMutation.mutate(
                    { bundleId, work },
                    {
                      onSuccess: () => toast.success("다시 넣었어요."),
                      onError: (error) => {
                        const notice = toWorkBundleActionError(error, "addItem");
                        if (notice !== null) toast.error(notice.message);
                      },
                    },
                  )
                }
              />
            ),
          });
        },
        onError: (error) => {
          const notice = toWorkBundleActionError(error, "removeItem");
          if (notice !== null) toast.error(notice.message);
        },
      },
    );
  };
}

function StudioStartSection({ isNovelAreaVisible }: { isNovelAreaVisible: boolean }) {
  const continueHeadingId = useId();
  const createHeadingId = useId();
  const query = useMyWorksQuery(UNFILTERED);
  const isLoading = query.isPending && query.failureCount === 0;
  const continueItem = pickContinueWork(query.data?.pages[0]?.items ?? [], isNovelAreaVisible);
  // 카드가 없으면(끝나지 않은 일 0건·조회 실패) 절째로 없고, 새로 만들기가 한 열 전체를 쓴다.
  const hasContinue = isLoading || continueItem !== undefined;

  return (
    <div className="@container">
      <div className={cn("grid gap-8", hasContinue && "@5xl:grid-cols-[1.15fr_1fr]")}>
        {hasContinue && (
          <section aria-labelledby={continueHeadingId} className="flex min-w-0 flex-col gap-3">
            <h2 id={continueHeadingId} className="text-lg font-semibold text-foreground">
              이어 만들기
            </h2>
            {continueItem ? <StudioContinueCard item={continueItem} /> : <StudioContinueCardSkeleton />}
          </section>
        )}
        <section aria-labelledby={createHeadingId} className="flex min-w-0 flex-col gap-3">
          <h2 id={createHeadingId} className="text-lg font-semibold text-foreground">
            새로 만들기
          </h2>
          <StudioCreateTiles />
        </section>
      </div>
    </div>
  );
}

type StudioWorksSectionProps = {
  userId: string;
  scope: Exclude<StudioScope, { kind: "unreadableBundle" }>;
  params: MyWorksParams;
  isNovelAreaVisible: boolean;
  onSearchChange: (patch: Partial<StudioSearch>) => void;
  /** 홈에서만 — 머리의 묶음 메뉴. */
  onCreateBundle?: () => void;
  /** 묶음 화면에서만 — 빈 묶음의 "작품 넣기". 묶음 이름을 받기 전에는 없다. */
  onAddWorks?: () => void;
};

function StudioWorksSection({
  userId,
  scope,
  params,
  isNovelAreaVisible,
  onSearchChange,
  onCreateBundle,
  onAddWorks,
}: StudioWorksSectionProps) {
  const headingId = useId();
  const query = useMyWorksQuery(params);
  const listRef = useRef<HTMLUListElement>(null);
  const isBundle = scope.kind === "bundle";
  const removeFromBundle = useRemoveFromBundleWithUndo(isBundle ? scope.bundleId : undefined, () =>
    listRef.current?.focus(),
  );
  const typeFilterRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const items = query.data?.pages.flatMap((page) => page.items) ?? [];
  const filterLabel = describeStudioFilter(params.type, params.status);
  const hasCondition = filterLabel !== undefined || params.q !== undefined;

  // 첫 시도 중에만 스켈레톤이다. 첫 시도가 실패하면 재시도 백오프 동안에도 `isPending` 이고 받은 행이 없어, 걸러내지
  // 않으면 아래 판정이 "아직 만든 작품이 없어요"로 떨어진다 — 실패 중엔 거짓일 수 있는 문장이다. 그래서 받은 첫 페이지가
  // 없는 실패는 재시도 중이든 끝났든 같은 실패 패널이다.
  const isFirstAttempt = query.isPending && query.failureCount === 0;
  const isFirstPageFailed = !isFirstAttempt && (query.isPending || (query.isError && items.length === 0));
  const view =
    isFirstAttempt || isFirstPageFailed
      ? undefined
      : resolveStudioBodyView({
          itemCount: items.length,
          hasCondition,
          isShowingPlaceholder: query.isPlaceholderData,
          isBundle,
        });

  // 툴바는 조건이 걸려 있으면 늘 그린다 — 칩을 처음 눌러 새 조건의 첫 응답을 기다리는 동안에도 칩·셀렉트·검색 칸이 자리를
  // 지켜야 누른 컨트롤의 포커스가 남는다. 조건 없이 처음 들어와 기다리는 동안·실패했을 때·만든 것이 하나도 없을 때는
  // 걸러낼 대상이 없어 그리지 않는다.
  const showToolbar = hasCondition || view === "list" || view === "awaiting" || view === "emptyResult";
  // 건수는 지금 조건의 응답이 왔을 때만 말한다. 자리표시(이전 검색어의 결과)를 보이는 동안 수를 적으면 응답이 오며
  // 뒤집힐 문장이 먼저 읽힌다.
  const isCountSettled = (view === "list" || view === "emptyResult") && !query.isPlaceholderData;

  const focusTypeFilter = (value: string) => {
    typeFilterRef.current?.querySelector<HTMLElement>(`[data-filter="${value}"]`)?.focus();
  };

  return (
    <section aria-labelledby={headingId} className="@container flex flex-col gap-4">
      {isBundle ? (
        <h2 id={headingId} className="sr-only">
          이 묶음의 작품
        </h2>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <h2 id={headingId} className="text-lg font-semibold text-foreground">
            모든 작품
          </h2>
          {onCreateBundle && <StudioBundleMenu onCreateBundle={onCreateBundle} />}
        </div>
      )}

      {showToolbar && (
        <>
          <StudioToolbar
            typeFilterRef={typeFilterRef}
            searchInputRef={searchInputRef}
            type={params.type}
            status={params.status}
            q={params.q}
            isNovelAreaVisible={isNovelAreaVisible}
            isStatusFilterVisible={!isBundle}
            onSearchChange={onSearchChange}
          />

          {/* 필터는 화면의 다른 곳을 바꾸는 컨트롤이라 결과 수를 읽어 준다. 커서 페이징이라 총계가 아니라 지금까지 불러온
              수이고, 남은 페이지가 있는 동안만 "표시 중"을 단다. */}
          <p aria-live="polite" aria-atomic aria-busy={!isCountSettled} className="text-sm text-muted-foreground">
            {isCountSettled
              ? `${toScopeLabel(params.q, filterLabel, isBundle)} ${items.length}건${query.hasNextPage ? " 표시 중" : ""}`
              : `${toScopeLabel(params.q, filterLabel, isBundle)} 불러오는 중`}
          </p>
        </>
      )}

      {(isFirstAttempt || view === "awaiting") && <StudioListSkeleton />}

      {isFirstPageFailed && (
        <div
          role="alert"
          className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center break-keep"
        >
          <p className="text-sm text-destructive-text">목록을 불러오지 못했어요.</p>
          <RetryButton isBusy={query.isFetching && !query.isPending} onRetry={() => void query.refetch()} />
        </div>
      )}

      {/* 바로 위 새로 만들기 칸과 같은 목적지 버튼을 다시 두지 않는다 — 같은 행동이 연달아 두 번 읽힌다. */}
      {view === "nothingMade" && (
        <ContentListEmptyState
          title="아직 만든 작품이 없어요"
          message={
            isNovelAreaVisible
              ? "위에서 캐릭터·스토리를 시작하거나 채팅에서 소설을 만들면 여기에 모여요."
              : "위에서 캐릭터나 스토리를 시작하면 여기에 모여요."
          }
        />
      )}

      {view === "nothingAdded" && (
        <ContentListEmptyState
          title="아직 넣은 작품이 없어요"
          message="작품을 넣어 나만 보는 정리를 시작해 보세요."
          action={
            onAddWorks && (
              <Button type="button" variant="outline" onClick={onAddWorks}>
                작품 넣기
              </Button>
            )
          }
        />
      )}

      {view === "emptyResult" && (
        <StudioEmptyResult
          q={params.q}
          filterLabel={filterLabel}
          onResetAll={() => {
            focusTypeFilter("all");
            onSearchChange({ type: undefined, status: undefined, q: undefined });
          }}
          onClearQuery={() => {
            searchInputRef.current?.focus();
            onSearchChange({ q: undefined });
          }}
        />
      )}

      {view === "list" && (
        <div className="flex flex-col gap-1">
          {/* 열 머리는 넓은 폭에서만, 보는 사람용이다 — 의미는 행 안 라벨이 갖는다. 썸네일·메뉴 폭만큼 들여 열을 맞춘다. */}
          <div
            aria-hidden
            className={`hidden pr-11 pl-[4.75rem] text-xs text-muted-foreground @3xl:grid @3xl:gap-x-4 ${STUDIO_ROW_COLUMNS}`}
          >
            <span>작품</span>
            <span>상태</span>
            <span>마지막 수정</span>
            <span>다음 행동</span>
          </div>
          {/* 마지막 페이지에서 "더 보기"가 사라지거나 행을 지웠을 때 포커스를 받을 자리다(Tab 순서에는 넣지 않는다). */}
          <ul ref={listRef} tabIndex={-1} aria-busy={query.isPlaceholderData} className="flex flex-col gap-1 outline-none">
            {items.map((item) => (
              <li key={`${item.kind}-${item.id}`}>
                <StudioWorkRow
                  item={item}
                  userId={userId}
                  onRemoved={() => listRef.current?.focus()}
                  onRemoveFromBundle={removeFromBundle && (() => removeFromBundle(item))}
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 더 보기 실패는 그 자리에서 다시 시도한다 — 이미 보인 행은 그대로 둔다. */}
      {view === "list" &&
        (query.isFetchNextPageError ? (
          <div role="alert" className="flex flex-wrap items-center justify-center gap-3">
            <p className="text-sm text-destructive-text">더 불러오지 못했어요.</p>
            <RetryButton isBusy={query.isFetchingNextPage} onRetry={() => void query.fetchNextPage()} />
          </div>
        ) : (
          <ContentListLoadMore
            hasMore={query.hasNextPage}
            isLoading={query.isFetchingNextPage}
            onLoadMore={() => {
              if (query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
            }}
            onExhausted={() => listRef.current?.focus()}
          />
        ))}
    </section>
  );
}

/** 건수 줄의 범위 이름 — 걸린 검색어와 필터를 함께 적고, 아무것도 안 걸렸으면 "전체"(묶음 화면은 "이 묶음")다. */
function toScopeLabel(q: string | undefined, filterLabel: string | undefined, isBundle: boolean): string {
  const parts = [q === undefined ? undefined : `‘${q}’`, filterLabel].filter((part) => part !== undefined);
  if (parts.length === 0) return isBundle ? "이 묶음" : "전체";
  return parts.join(" · ");
}

type StudioEmptyResultProps = {
  q: string | undefined;
  filterLabel: string | undefined;
  onResetAll: () => void;
  onClearQuery: () => void;
};

function StudioEmptyResult({ q, filterLabel, onResetAll, onClearQuery }: StudioEmptyResultProps) {
  const result = resolveStudioEmptyResult({ q, filterLabel });

  return (
    <ContentListEmptyState
      message={result.message}
      action={
        <Button type="button" variant="outline" onClick={result.action === "clearQuery" ? onClearQuery : onResetAll}>
          {result.action === "clearQuery" ? "검색어 지우기" : "필터 모두 해제"}
        </Button>
      }
    />
  );
}

/** 다시 가져오는 동안 `disabled` 를 걸면 누르는 순간 포커스가 `<body>` 로 떨어지므로 `aria-disabled` + 첫 줄 return 으로 막는다. */
function RetryButton({ isBusy, onRetry }: { isBusy: boolean; onRetry: () => void }) {
  return (
    <Button
      type="button"
      variant="outline"
      aria-disabled={isBusy}
      className="aria-disabled:opacity-65"
      onClick={() => {
        if (isBusy) return;
        onRetry();
      }}
    >
      다시 시도
    </Button>
  );
}

/** 행 모양 자리표시 다섯 줄. 진행 표시라 `motion-safe:` 를 붙이지 않는다(멈추면 멈춘 화면으로 읽힌다). */
function StudioListSkeleton() {
  return (
    <div role="status" aria-busy aria-label="작품 목록 불러오는 중" className="flex flex-col gap-1">
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} className="flex items-center gap-3 px-2 py-2">
          <span className="size-12 shrink-0 animate-pulse rounded-lg bg-muted @3xl:size-14" />
          <span className="flex flex-1 flex-col gap-2">
            <span className="h-4 w-1/3 animate-pulse rounded bg-muted" />
            <span className="h-4 w-1/5 animate-pulse rounded bg-muted" />
          </span>
        </div>
      ))}
    </div>
  );
}
