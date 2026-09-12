import { TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { TriangleAlert } from "lucide-react";

import type { BuilderTab } from "@/entities/content";

import { useHorizontalScrollClip } from "../lib/useHorizontalScrollClip";

type BuilderTabStripProps = {
  /** 그릴 탭 목록. 셸의 `TABS`(`CHARACTER_TABS`·`STORY_TABS`)가 단일 소스다(builder-techspec.md §4-1). */
  tabs: readonly BuilderTab[];
  /** 에러를 품은 탭 id 집합(`errorTabs`의 반환값) — 라벨에 경고 아이콘과 destructive 색을 붙인다. */
  errorTabIds: ReadonlySet<string>;
};

/**
 * 빌더 스텝 탭 스트립. 두 셸이 글자 단위로 같은 JSX를 들고 있던 것을 모았다
 * (fe-convention-refactor-goal-prompt.md R-3) — 활성 탭 값과 전환은 `TabsList`/`TabsTrigger`가
 * 부모 `Tabs`의 컨텍스트에서 읽으므로 이 컴포넌트는 activeTab도, 그 값을 좁히는 술어도 모른다.
 *
 * P2 — `TabsList`는 `inline-flex w-fit`이고 `overflow-x-auto`가 없어(packages/ui/tabs.tsx는
 * 고치지 않는다, 호출부 처방) 8개 탭이 넘치면 이 스트립이 아니라 페이지 전체가 가로로 밀렸다
 * (390px 실측 428px). 스트립 자체를 스크롤 컨테이너로 감싼다 — `-m-1 p-1`은 `overflow-x-auto`가
 * 포커스 링을 클립하는 걸 상쇄한다(apps/web/CLAUDE.md "overflow-x-auto는 focus 링을 네 방향 모두
 * 클립한다"). 오른쪽 페이드는 실제로 잘렸을 때만(`isClippedRight`) 뜬다 — iOS Safari 오버레이
 * 스크롤바엔 상시 표시가 없어(`useHorizontalScrollClip` 주석, packages/ui의 `data-clipped-below`와
 * 같은 이유) 신호가 따로 필요하다.
 */
export function BuilderTabStrip({ tabs, errorTabIds }: BuilderTabStripProps) {
  const tabsScroll = useHorizontalScrollClip();

  return (
    <div className="relative">
      <div ref={tabsScroll.ref} className="-m-1 overflow-x-auto p-1">
        <TabsList variant="line">
          {tabs.map((tab) => {
            const hasError = errorTabIds.has(tab.id);
            return (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                className={cn(
                  hasError &&
                    "text-destructive-text hover:text-destructive-text data-active:text-destructive-text dark:text-destructive-text dark:hover:text-destructive-text dark:data-active:text-destructive-text",
                )}
              >
                {hasError && <TriangleAlert aria-hidden className="size-3.5 shrink-0" />}
                {tab.label}
                {hasError && <span className="sr-only"> (입력 오류가 있어요)</span>}
              </TabsTrigger>
            );
          })}
        </TabsList>
      </div>
      {tabsScroll.isClippedRight && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-1 right-1 w-8 bg-linear-to-l from-background"
        />
      )}
    </div>
  );
}
