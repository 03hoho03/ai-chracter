import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check, TriangleAlert } from "lucide-react";

import type { BuilderTab } from "@/entities/content";

import {
  BUILDER_STEP_IDS,
  BUILDER_STEP_LABELS,
  stepsWithErrors,
  tabForStep,
  tabsOfStep,
  type BuilderStepId,
  type TabStepTable,
} from "../model/builderSteps";

type BuilderStepNavProps<TTabId extends string> = {
  /** `column` 은 1280px 이상 왼쪽 열(묶음 아래 탭을 늘 펼친다), `bar` 는 그보다 좁은 폭의 폼 흐름 안 네 칸 줄이다. */
  variant: "column" | "bar";
  /** 셸의 탭 배열(`CHARACTER_TABS`·`STORY_TABS`). 묶음 안 탭 순서는 이 배열에서 걸러 낸 순서다. */
  tabs: readonly (BuilderTab & { id: TTabId })[];
  table: TabStepTable<TTabId>;
  activeTab: TTabId;
  /** 테스트를 고른 동안인지. 셸의 화면 상태이고 주소에 싣지 않는다. */
  isTesting: boolean;
  errorTabIds: ReadonlySet<string>;
  requiredTabIds: ReadonlySet<string>;
  completedTabIds: ReadonlySet<string>;
  /** 탭을 연다. 테스트 중이었으면 셸이 테스트를 끝낸다. 지금 탭과 같은 탭이 올 수 있다. */
  onSelectTab: (tabId: TTabId) => void;
  onSelectTesting: () => void;
};

/** 보내기 전에 알아야 할 것. 미리보기 대화의 첫 전송이 비용과 잔액을 다시 확인한다. */
const TESTING_NOTE = "미리보기에서 대화로 시험해요. 보내면 턴마다 클로버가 들어요.";

/** 고른 줄 표시. 좌측 패널 행과 같은 말이다 — 채움(`secondary`)과 밝기 천장 글자, 그리고 채움이 배경 대비 3:1 에 못 미쳐 남겨 두는
 * 왼쪽 1px 무채색 막대. */
const ROW_CLASS = cn(
  "relative flex w-full items-center gap-1.5 rounded-lg text-left text-sm font-medium text-muted-foreground",
  "motion-safe:transition-colors hover:bg-secondary hover:text-foreground",
  "focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring",
  "aria-[current=true]:bg-secondary aria-[current=true]:font-semibold aria-[current=true]:text-foreground",
  "aria-[current=true]:before:absolute aria-[current=true]:before:inset-y-2 aria-[current=true]:before:left-0 aria-[current=true]:before:w-px aria-[current=true]:before:bg-foreground",
);

/**
 * 빌더 탭을 넷(기본 설정·시작 장면·테스트·공개 준비)으로 묶어 보이는 목록. 탭 id·`?tab=`·작성 가이드 경로는 그대로이고, 묶음은
 * 지금 탭에서 도출하는 화면 표시다. 화면에 "단계" 낱말이나 번호를 쓰지 않는다 — 작성 가이드가 탭 하나를 "N단계"로 부른다.
 *
 * 두 꼴을 셸이 함께 그리고 CSS 로만 하나를 보인다(`column` 은 `BuilderLayout` 의 왼쪽 열, `bar` 는 `xl:hidden`). JS 로 폭을 판정해
 * 하나만 그리면 폭이 바뀌는 순간 형제 자리가 바뀌어 폼과 미리보기가 다시 마운트된다.
 *
 * 탭 전환은 Radix `Tabs` 가 아니라 평범한 버튼이다. `column` 은 넓은 화면에서 가로 탭 줄을 대신하므로, 탭 줄이 숨은 그 폭에서는
 * 화살표 키 이동 대신 Tab 순회로 줄을 옮긴다. 고른 줄은 `aria-current` 로 알린다.
 *
 * 필수 별표·채움 체크·오류 표시는 탭 줄(`BuilderTabStrip`)과 같은 규칙이다. 묶음 칸에는 오류 표시만 둔다 — `bar` 의 한 칸(약 88px)에
 * 별표·체크까지 얹으면 이름이 줄바꿈되고, 선택 탭이 비어 있는 것은 정상이라 묶음에 채움 표시를 따로 두지 않는다.
 */
export function BuilderStepNav<TTabId extends string>(props: BuilderStepNavProps<TTabId>) {
  const { tabs, table, activeTab, isTesting, errorTabIds, onSelectTab, onSelectTesting } = props;
  const currentStep: BuilderStepId = isTesting ? "test" : table[activeTab];
  const errorSteps = stepsWithErrors(errorTabIds, table);

  function selectStep(step: BuilderStepId) {
    if (step === "test") onSelectTesting();
    else onSelectTab(tabForStep(tabs, table, step, activeTab));
  }

  if (props.variant === "bar") {
    return (
      <nav aria-label="만들기 순서" className="flex flex-col gap-2">
        <ul className="grid grid-cols-4 gap-1">
          {BUILDER_STEP_IDS.map((step) => {
            const hasError = step !== "test" && errorSteps.has(step);
            return (
              <li key={step} className="flex">
                <button
                  type="button"
                  aria-current={step === currentStep ? "true" : undefined}
                  className={cn(
                    ROW_CLASS,
                    "min-h-11 justify-center px-1 text-center break-keep",
                    hasError && "text-destructive-text hover:text-destructive-text aria-[current=true]:text-destructive-text",
                  )}
                  onClick={() => selectStep(step)}
                >
                  {hasError && <TriangleAlert aria-hidden className="size-3.5 shrink-0" />}
                  <span>{BUILDER_STEP_LABELS[step]}</span>
                  {hasError && <span className="sr-only"> (입력 오류가 있어요)</span>}
                </button>
              </li>
            );
          })}
        </ul>
        {isTesting && <p className="text-xs text-muted-foreground break-keep">{TESTING_NOTE}</p>}
      </nav>
    );
  }

  return (
    <nav aria-label="만들기 순서">
      <ul className="flex flex-col gap-4">
        {BUILDER_STEP_IDS.map((step) => {
          const hasError = step !== "test" && errorSteps.has(step);
          return (
            <li key={step} className="flex flex-col gap-0.5">
              <button
                type="button"
                // 탭을 품은 묶음은 그 안의 탭 줄이 고른 표시를 맡는다. 줄이 없는 테스트만 묶음 줄 자체가 고른 줄이 된다.
                aria-current={step === "test" && isTesting ? "true" : undefined}
                className={cn(
                  ROW_CLASS,
                  "h-9 px-3 font-semibold text-foreground pointer-coarse:h-10",
                  hasError && "text-destructive-text hover:text-destructive-text",
                )}
                onClick={() => selectStep(step)}
              >
                <span>{BUILDER_STEP_LABELS[step]}</span>
                {hasError && <TriangleAlert aria-hidden className="size-3.5 shrink-0" />}
                {hasError && <span className="sr-only"> (입력 오류가 있어요)</span>}
              </button>
              {step === "test" ? (
                <p className="px-3 text-xs text-muted-foreground break-keep">{TESTING_NOTE}</p>
              ) : (
                <ul className="flex flex-col gap-0.5">
                  {tabsOfStep(tabs, table, step).map((tab) => (
                    <li key={tab.id}>
                      <StepTabRow {...props} tab={tab} />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function StepTabRow<TTabId extends string>({
  tab,
  activeTab,
  isTesting,
  errorTabIds,
  requiredTabIds,
  completedTabIds,
  onSelectTab,
}: BuilderStepNavProps<TTabId> & { tab: BuilderTab & { id: TTabId } }) {
  const hasError = errorTabIds.has(tab.id);
  const isRequired = !hasError && requiredTabIds.has(tab.id);
  const isCompleted = isRequired && completedTabIds.has(tab.id);
  const isActive = tab.id === activeTab;
  return (
    <button
      type="button"
      // 테스트 중에도 폼 열은 이 탭을 그대로 보인다. 고른 줄은 테스트 하나로 두고, 이 탭은 밝은 글자로만 남긴다.
      aria-current={isActive && !isTesting ? "true" : undefined}
      className={cn(
        ROW_CLASS,
        "h-9 pr-3 pl-6 pointer-coarse:h-10",
        isActive && isTesting && "text-foreground",
        hasError && "text-destructive-text hover:text-destructive-text aria-[current=true]:text-destructive-text",
      )}
      onClick={() => onSelectTab(tab.id)}
    >
      {hasError && <TriangleAlert aria-hidden className="size-3.5 shrink-0" />}
      <span>
        {tab.label}
        {isRequired && !isCompleted && <span aria-hidden className="text-destructive-text"> *</span>}
        {isCompleted && (
          <Check aria-hidden strokeWidth={3} className="ml-px inline size-2.5 -translate-y-px align-middle text-muted-foreground" />
        )}
      </span>
      {isRequired && <span className="sr-only">{isCompleted ? " (필수, 입력 완료)" : " (필수)"}</span>}
      {hasError && <span className="sr-only"> (입력 오류가 있어요)</span>}
    </button>
  );
}
