import { useCallback, useEffect, useRef } from "react";
import { TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { TriangleAlert } from "lucide-react";

import type { BuilderTab } from "@/entities/content";
import { useHorizontalScrollClip } from "@/shared/lib/scroll/useHorizontalScrollClip";

type BuilderTabStripProps = {
  /** 그릴 탭 목록. 셸의 `TABS`(`CHARACTER_TABS`·`STORY_TABS`)가 단일 소스다. */
  tabs: readonly BuilderTab[];
  /** 지금 열린 탭 id. 탭 줄이 넘칠 때 이 탭이 보이도록 줄을 민다. */
  activeTab: string;
  /** 에러를 품은 탭 id 집합(`errorTabs`의 반환값) — 라벨에 경고 아이콘과 destructive 색을 붙인다. */
  errorTabIds: ReadonlySet<string>;
  /** 언제나 필수인 탭 id 집합(`requiredTabIds` 로 셸 밖에서 한 번 계산한 값) — 라벨 뒤에 빨간 별표를 붙인다. */
  requiredTabIds: ReadonlySet<string>;
};

/** 열린 탭을 탭 줄 안으로 밀 때 양끝에 남기는 여백. 페이드(`w-8`) 밑에 탭이 걸리지 않게 같은 폭을 둔다. */
const SCROLL_EDGE_PX = 32;

/**
 * 빌더 스텝 탭 스트립. 두 셸이 글자 단위로 같은 JSX를 들고 있던 것을 모았다 — 활성 탭 값과 전환은
 * `TabsList`/`TabsTrigger`가 부모 `Tabs`의 컨텍스트에서 읽는다. `activeTab` 은 탭 줄을 밀 때만 쓴다.
 *
 * `TabsList`는 `inline-flex w-fit`이고 `overflow-x-auto`가 없어(packages/ui/tabs.tsx는
 * 고치지 않는다, 호출부 처방) 8개 탭이 넘치면 이 스트립이 아니라 페이지 전체가 가로로 밀렸다
 * (390px 실측 428px). 스트립 자체를 스크롤 컨테이너로 감싼다 — `-m-1 p-1`은 `overflow-x-auto`가
 * 포커스 링을 클립하는 걸 상쇄한다(apps/web/CLAUDE.md "overflow-x-auto는 focus 링을 네 방향 모두
 * 클립한다"). 양쪽 페이드는 실제로 잘렸을 때만(`isClippedLeft`·`isClippedRight`) 뜬다 — iOS Safari 오버레이
 * 스크롤바엔 상시 표시가 없어(`useHorizontalScrollClip` 주석, packages/ui의 `data-clipped-below`와
 * 같은 이유) 신호가 따로 필요하다. 왼쪽 페이드가 있어야 줄을 민 뒤 앞쪽 탭이 숨었다는 것도 보인다.
 *
 * 열린 탭이 줄 밖에 있으면 줄만 가로로 민다. 탭을 고를 때와 발행 실패로 첫 오류 탭이 열릴 때, 그리고 오류 표시가 붙어 탭 폭이
 * 늘어날 때(`errorTabIds`) 다시 잰다 — 마지막 탭(스토리 '등록')이 오류 아이콘에 밀려 줄 밖으로 나가는 일을 여기서 막는다.
 * `scrollIntoView` 를 쓰지 않는 이유는 좁은 화면에서 문서가 스크롤러라 문서도 세로로 움직이고, 그게 첫 오류 칸으로 가는 스크롤과
 * 다투기 때문이다. 줄을 처음 그릴 때는 밀지 않는다. 움직임 줄이기 설정이면 바로 옮긴다.
 *
 * 필수 탭의 별표는 칸 라벨(`RequiredText`)과 같은 빨간 `*` 지만 보조기기에는 별표 대신 "필수"를 읽힌다(DESIGN.md Inputs / Fields 의
 * Required 항목). 오류가 있는 탭은 별표와 "필수" 대신 오류 표시만 둔다 — 고칠 곳이라는 말이 이미 필수라는 말을 포함한다.
 */
export function BuilderTabStrip({ tabs, activeTab, errorTabIds, requiredTabIds }: BuilderTabStripProps) {
  const tabsScroll = useHorizontalScrollClip();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const setContainerRef = useCallback(
    (el: HTMLDivElement | null) => {
      containerRef.current = el;
      return tabsScroll.ref(el);
    },
    [tabsScroll.ref],
  );

  // 같은 값으로 다시 돈 effect(첫 그리기, 개발 모드의 두 번 실행)는 줄을 밀지 않도록 직전에 잰 조건을 기억한다.
  const errorKey = [...errorTabIds].join(",");
  const measuredRef = useRef({ activeTab, errorKey });
  useEffect(() => {
    const previous = measuredRef.current;
    if (previous.activeTab === activeTab && previous.errorKey === errorKey) return;
    measuredRef.current = { activeTab, errorKey };
    const container = containerRef.current;
    const trigger = container?.querySelector<HTMLElement>(`[data-tab-id="${activeTab}"]`);
    if (!container || !trigger) return;
    const left = scrollLeftToReveal(container, trigger);
    if (left === container.scrollLeft) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    container.scrollTo({ left, behavior: reduceMotion ? "auto" : "smooth" });
  }, [activeTab, errorKey]);

  return (
    <div className="relative">
      <div ref={setContainerRef} className="-m-1 overflow-x-auto p-1">
        {/* 손가락 포인터에서는 탭을 40px 로 올린다. 프리미티브가 목록 높이(`h-9`)에서 탭 높이를 빼므로 목록 높이를 풀고 탭에
            높이를 직접 준다 — 목록 높이 쪽 클래스는 그룹 속성 셀렉터라 같은 변형 사슬로 덮어야 이긴다. */}
        <TabsList variant="line" className="pointer-coarse:group-data-horizontal/tabs:h-auto">
          {tabs.map((tab) => {
            const hasError = errorTabIds.has(tab.id);
            const isRequired = !hasError && requiredTabIds.has(tab.id);
            return (
              <TabsTrigger
                key={tab.id}
                value={tab.id}
                data-tab-id={tab.id}
                // 좌우 패딩을 프리미티브(`px-1.5`)보다 한 단계 줄인다 — 필수 별표가 붙으며 스토리 열 탭이 1440px 의 폼 열(632px)을
                // 28px 넘어 마지막 '등록'이 처음부터 페이드 밑에 숨었다. 탭 사이 간격이 16px 에서 12px 가 된다.
                className={cn(
                  "px-1 pointer-coarse:h-10",
                  hasError &&
                    "text-destructive-text hover:text-destructive-text data-active:text-destructive-text dark:text-destructive-text dark:hover:text-destructive-text dark:data-active:text-destructive-text",
                )}
              >
                {hasError && <TriangleAlert aria-hidden className="size-3.5 shrink-0" />}
                {/* 글자와 별표를 한 덩어리로 묶는다 — 탭은 `gap-1.5` 플렉스라 따로 두면 별표가 띄어쓰기 대신 6px 떨어진다. */}
                <span>
                  {tab.label}
                  {isRequired && <span aria-hidden className="text-destructive-text"> *</span>}
                </span>
                {isRequired && <span className="sr-only"> (필수)</span>}
                {hasError && <span className="sr-only"> (입력 오류가 있어요)</span>}
              </TabsTrigger>
            );
          })}
        </TabsList>
      </div>
      {tabsScroll.isClippedLeft && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-1 left-1 w-8 bg-linear-to-r from-background"
        />
      )}
      {tabsScroll.isClippedRight && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-1 right-1 w-8 bg-linear-to-l from-background"
        />
      )}
    </div>
  );
}

/** `trigger` 가 `container` 의 보이는 폭 안(양끝 `SCROLL_EDGE_PX` 안쪽)에 들어오는 `scrollLeft`. 이미 들어와 있으면 지금 값 그대로다.
 * 범위 밖 값은 `scrollTo` 가 스스로 0~최댓값으로 자른다. */
function scrollLeftToReveal(container: HTMLElement, trigger: HTMLElement): number {
  const box = container.getBoundingClientRect();
  const target = trigger.getBoundingClientRect();
  const visibleLeft = box.left + SCROLL_EDGE_PX;
  const visibleRight = box.right - SCROLL_EDGE_PX;
  if (target.left < visibleLeft) return container.scrollLeft - (visibleLeft - target.left);
  if (target.right > visibleRight) return container.scrollLeft + (target.right - visibleRight);
  return container.scrollLeft;
}
