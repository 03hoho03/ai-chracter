/** 빌더 탭을 묶는 넷. 탭을 품는 셋과, 탭이 아니라 미리보기 대화로 시험하는 `test` 하나다. 배열 순서가 화면에 그리는 순서다. */
export const BUILDER_STEP_IDS = ["basics", "opening", "test", "publish"] as const;

export type BuilderStepId = (typeof BUILDER_STEP_IDS)[number];

/** 탭을 품는 묶음. `test` 는 탭이 없어 탭 → 묶음 표의 값이 될 수 없다. */
export type TabStepId = Exclude<BuilderStepId, "test">;

/** 화면에 쓰는 묶음 이름. 번호는 붙이지 않는다 — 작성 가이드가 탭 하나를 "N단계"로 부르고 있어, 빌더가 묶음에 번호를 매기면
 * 같은 말이 두 뜻이 된다. */
export const BUILDER_STEP_LABELS: Readonly<Record<BuilderStepId, string>> = {
  basics: "기본 설정",
  opening: "시작 장면",
  test: "테스트",
  publish: "공개 준비",
};

/** 탭 id → 묶음. 빌더마다 `satisfies Record<탭 id, TabStepId>` 로 적어 탭을 빠뜨리면 타입 오류가 나게 한다. */
export type TabStepTable<TTabId extends string> = Readonly<Record<TTabId, TabStepId>>;

type TabLike<TTabId extends string> = { readonly id: TTabId };

/**
 * 탭을 묶음 순서로 다시 줄 세운다. 같은 묶음 안에서는 받은 배열 순서 그대로다. 순수 함수.
 *
 * 탭 줄과 `?tab=` 은 탭 배열을 그대로 쓰고, 이 순서는 사용자가 묶음 순서로 읽는 곳(첫 오류로 가는 이동, 발행 전 확인 목록)에만 넘긴다.
 */
export function tabsInStepOrder<TTabId extends string, TTab extends TabLike<TTabId>>(
  tabs: readonly TTab[],
  table: TabStepTable<TTabId>,
): TTab[] {
  // `sort` 는 안정 정렬이라 같은 묶음 안에서는 배열 순서가 남는다.
  return [...tabs].sort((a, b) => BUILDER_STEP_IDS.indexOf(table[a.id]) - BUILDER_STEP_IDS.indexOf(table[b.id]));
}

/** 한 묶음의 탭. 배열 순서 그대로 거른다. 순수 함수. */
export function tabsOfStep<TTabId extends string, TTab extends TabLike<TTabId>>(
  tabs: readonly TTab[],
  table: TabStepTable<TTabId>,
  step: TabStepId,
): TTab[] {
  return tabs.filter((tab) => table[tab.id] === step);
}

/** 묶음을 고르면 열 탭. 지금 탭이 그 묶음에 있으면 그대로 두고, 아니면 그 묶음의 첫 탭이다. 순수 함수. */
export function tabForStep<TTabId extends string>(
  tabs: readonly TabLike<TTabId>[],
  table: TabStepTable<TTabId>,
  step: TabStepId,
  activeTab: TTabId,
): TTabId {
  if (table[activeTab] === step) return activeTab;
  return tabsOfStep(tabs, table, step)[0]?.id ?? activeTab;
}

/** 오류가 있는 탭을 하나라도 품은 묶음. 순수 함수. */
export function stepsWithErrors<TTabId extends string>(
  errorTabIds: ReadonlySet<string>,
  table: TabStepTable<TTabId>,
): Set<TabStepId> {
  const steps = new Set<TabStepId>();
  for (const [tabId, step] of Object.entries<TabStepId>(table)) {
    if (errorTabIds.has(tabId)) steps.add(step);
  }
  return steps;
}

/** 미리보기 칸에 그릴 것. 테스트를 고른 동안은 어느 탭에서든 대화다. 아니면 그 탭이 정한 것이다. 순수 함수. */
export function previewKindFor(tabPreview: "card" | "chat", isTesting: boolean): "card" | "chat" {
  return isTesting ? "chat" : tabPreview;
}
