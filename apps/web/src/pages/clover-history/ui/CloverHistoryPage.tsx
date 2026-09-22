import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { useRef } from "react";

import {
  CLOVER_EXPIRY_NOTICE_MESSAGE,
  CLOVER_KIND_LABELS,
  formatCloverLedgerAmount,
  useCloverLedgerQuery,
  type CloverLedgerCategory,
  type CloverLedgerItem,
} from "@/entities/clover";
import { ContentListEmptyState, ContentListLoadMore } from "@/entities/content";
import { formatDate } from "@/shared/lib/time/formatDate";

import {
  CLOVER_HISTORY_TABS,
  isCloverHistoryTab,
  resolveCloverHistoryTab,
  type CloverHistorySearch,
  type CloverHistoryTab,
} from "../model/cloverHistorySearch";

const TAB_LABELS: Record<CloverHistoryTab, string> = {
  use: "사용",
  earn: "획득",
  expire: "소멸",
};

const EMPTY_MESSAGES: Record<CloverHistoryTab, string> = {
  use: "아직 사용한 클로버가 없어요.",
  earn: "아직 받은 클로버가 없어요.",
  expire: "아직 소멸된 클로버가 없어요.",
};

type CloverHistoryPageProps = {
  search: CloverHistorySearch;
  onSearchChange: (patch: Partial<CloverHistorySearch>) => void;
};

/** clover-page-goal-prompt.md CE-24·CE-26·CE-36 — 클로버 내역 화면. 탭(사용/획득/소멸) 상태는
 * URL 검색 파라미터(`?tab=`)로 두고, 각 탭은 별도 `useCloverLedgerQuery` 인스턴스를 갖는다(CE-26 —
 * `queryKey`에 `category`가 들어가 탭 전환이 그 자체로 새 쿼리다). 컨테이너 폭은 허브·마이페이지와
 * 같은 `max-w-md`(CE-36). */
export function CloverHistoryPage({ search, onSearchChange }: CloverHistoryPageProps) {
  const activeTab = resolveCloverHistoryTab(search);

  const handleTabChange = (value: string) => {
    if (!isCloverHistoryTab(value)) return;
    // `use`는 스키마가 `.exclude()`한 기본값이라 URL에 다시 실으면 안 된다 — 부재로 되돌린다.
    onSearchChange({ tab: value === "use" ? undefined : value });
  };

  return (
    <main className="mx-auto flex max-w-md flex-col gap-6 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">클로버 내역</h1>
        {/* clover-page-goal-prompt.md CE-33 — 허브 페이지(clover-hub)와 같은 상시 고지, 같은
            단일 소스(entities/clover의 cloverExpiryNotice.ts)를 쓴다. */}
        <p className="text-sm break-keep text-muted-foreground">{CLOVER_EXPIRY_NOTICE_MESSAGE}</p>
      </div>

      {/* apps/web/CLAUDE.md — 탭은 variant="line"(활성 탭은 primary가 아니라 foreground 밑줄). */}
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList variant="line">
          {CLOVER_HISTORY_TABS.map((tab) => (
            <TabsTrigger key={tab} value={tab}>
              {TAB_LABELS[tab]}
            </TabsTrigger>
          ))}
        </TabsList>

        {CLOVER_HISTORY_TABS.map((tab) => (
          <TabsContent key={tab} value={tab} className="mt-4">
            <CloverLedgerTabPanel category={tab} />
          </TabsContent>
        ))}
      </Tabs>
    </main>
  );
}

function CloverLedgerTabPanel({ category }: { category: CloverLedgerCategory }) {
  const query = useCloverLedgerQuery(category);
  const listRef = useRef<HTMLUListElement>(null);
  const items = query.data?.pages.flatMap((page) => page.items) ?? [];

  // `ProfileContentSection`(entities/content 소비처)과 같은 4갈래 early-return 순서(COMP-04) —
  // 재시도 백오프 중에도 isPending이라 failureCount===0으로 걸러야 이미 도착한 목록이 스켈레톤에
  // 안 갇힌다.
  if (query.isPending && query.failureCount === 0) {
    return <p className="text-sm text-muted-foreground">불러오는 중…</p>;
  }

  if (query.isError && items.length === 0) {
    return <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>;
  }

  if (items.length === 0) {
    return <ContentListEmptyState message={EMPTY_MESSAGES[category]} />;
  }

  return (
    <div className="flex flex-col gap-4">
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

      {/* `tabIndex={-1}`은 Tab 순서에 넣지 않으면서 프로그램 포커스만 받게 한다 — "더 보기"가
          마지막 페이지에서 사라질 때 포커스를 여기로 넘긴다(`ContentListLoadMore`의 `onExhausted`). */}
      <ul ref={listRef} tabIndex={-1} className="flex flex-col gap-2 outline-none">
        {items.map((item) => (
          <CloverLedgerRow key={item.id} item={item} />
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

function CloverLedgerRow({ item }: { item: CloverLedgerItem }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-xl border border-border px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">
          {CLOVER_KIND_LABELS[item.kind] ?? item.kind}
        </span>
        <span className="text-xs text-muted-foreground">{formatDate(item.createdAt)}</span>
      </div>
      {/* clover-page-goal-prompt.md CE-27 — 평소 무채색, 부호(+/-)만으로 방향을 말한다(색으로
          갈라 새 유채색을 만들지 않는다). */}
      <span className="text-sm font-medium tabular-nums text-foreground">
        {formatCloverLedgerAmount(item.amount)}
      </span>
    </li>
  );
}
