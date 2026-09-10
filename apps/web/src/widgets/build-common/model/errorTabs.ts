import type { FieldErrors, FieldValues } from "react-hook-form";

import type { BuilderTab } from "@/shared/model/builderTab";

import { flattenFieldErrorPaths, matchTabForPath } from "./fieldErrorPaths";

/**
 * builder-techspec.md §4-2 — RHF `errors`를 경로 문자열로 평탄화한 뒤 각 경로를 `tabs[].fields`
 * 프리픽스와 대조해, 에러를 하나라도 품은 탭의 id 집합을 돌려준다. 순수 함수.
 */
export function errorTabs<T extends FieldValues>(errors: FieldErrors<T>, tabs: readonly BuilderTab[]): Set<string> {
  const result = new Set<string>();
  for (const path of flattenFieldErrorPaths(errors)) {
    const tabId = matchTabForPath(path, tabs);
    if (tabId !== undefined) result.add(tabId);
  }
  return result;
}
