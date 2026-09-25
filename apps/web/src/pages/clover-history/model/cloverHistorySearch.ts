import { z } from "zod";

/** 탭 상태는 URL 검색 파라미터(`?tab=`)로 둔다. 나중에 "충전"
 * 탭이 네 번째로 붙을 예정이라 이 목록 하나만 늘리면 되는 구조다(라우트를 늘리지 않는다). */
export const CLOVER_HISTORY_TABS = ["use", "earn", "expire"] as const;

export type CloverHistoryTab = (typeof CLOVER_HISTORY_TABS)[number];

/** `/my`의 `myWorksSearchSchema` 선례(`pages/my-works/model/myWorksSearch.ts`)를 그대로 따른다 —
 * 기본값(`use`)은 `.exclude()`로 열거형에서 빼 URL에 싣지 않고, 모르는/어긋난
 * 값은 `.catch(undefined)`로 부재에 접는다(던지면 라우터가 앱 크롬 없는 에러 상자를 띄운다). */
export const cloverHistorySearchSchema = z.object({
  tab: z.enum(CLOVER_HISTORY_TABS).exclude(["use"]).optional().catch(undefined),
});

export type CloverHistorySearch = z.infer<typeof cloverHistorySearchSchema>;

/** URL 파라미터 부재를 기본 탭(`use`)으로 편다 — 기본값 규칙은 여기 하나뿐이다. */
export function resolveCloverHistoryTab(search: CloverHistorySearch): CloverHistoryTab {
  return search.tab ?? "use";
}

/** Radix `Tabs`의 `onValueChange`가 주는 값은 `string`이라 좁힘이 필요하다(`isMyWorkTypeFilter`와
 * 같은 이유 — `as` 단언 대신 술어를 쓴다). */
export function isCloverHistoryTab(value: string): value is CloverHistoryTab {
  return CLOVER_HISTORY_TABS.some((tab) => tab === value);
}
