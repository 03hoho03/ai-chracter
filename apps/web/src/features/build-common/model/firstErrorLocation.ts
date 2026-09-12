import type { FieldErrors, FieldValues } from "react-hook-form";

import type { BuilderTab } from "@/entities/content";

import { flattenFieldErrorPaths, matchTabForPath } from "./fieldErrorPaths";

export type FirstErrorLocation = { tabId: string; fieldPath: string };

/**
 * 첫 에러의 `{tabId, fieldPath}`(builder-techspec.md §9-1이 쓸 탭 전환·포커스 입력값). 순수 함수.
 *
 * "첫"의 기준은 **탭 선언 순서**다(화면에 보이는 순서) — 스키마 키 순서와 반대일 수 있다. 같은 탭 안에
 * 에러가 여럿이면 `flattenFieldErrorPaths`가 주는 순회 순서(문자열 키는 선언 순서, 배열은 인덱스
 * 오름차순)에서 가장 먼저 나오는 경로를 고른다 — 결정론적이고 스키마 선언 순서와 자연히 일치한다.
 */
export function firstErrorLocation<T extends FieldValues>(
  errors: FieldErrors<T>,
  tabs: readonly BuilderTab[],
): FirstErrorLocation | undefined {
  const located = flattenFieldErrorPaths(errors)
    .map((fieldPath) => ({ fieldPath, tabId: matchTabForPath(fieldPath, tabs) }))
    .filter((entry): entry is FirstErrorLocation => entry.tabId !== undefined);

  for (const tab of tabs) {
    const match = located.find((entry) => entry.tabId === tab.id);
    if (match) return match;
  }
  return undefined;
}
