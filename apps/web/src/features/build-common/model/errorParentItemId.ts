import { get, type FieldErrors, type FieldValues } from "react-hook-form";

import type { BuilderTab } from "@/entities/content";

import { matchTabForPath } from "./fieldErrorPaths";
import { firstErrorLocation } from "./firstErrorLocation";

/** 부모 항목 하나를 골라 그 아래만 보여 주는 탭들(스토리의 스탯·엔딩 탭은 고른 시작설정 하나의 스탯·엔딩만 그린다). */
export type ErrorParentScope = {
  /** 부모 배열 경로(예: `startingSetups`). */
  path: string;
  tabIds: readonly string[];
};

function parentIdOfPath(
  path: string,
  values: FieldValues,
  scope: ErrorParentScope,
  tabs: readonly BuilderTab[],
): string | undefined {
  const tabId = matchTabForPath(path, tabs);
  if (tabId === undefined || !scope.tabIds.includes(tabId)) return undefined;
  const parent = scope.path.split(".");
  const segments = path.split(".");
  if (!parent.every((part, index) => part === segments[index])) return undefined;
  const indexSegment = segments[parent.length];
  if (indexSegment === undefined) return undefined;
  const id: unknown = get(values, `${scope.path}.${indexSegment}.id`);
  return typeof id === "string" ? id : undefined;
}

/**
 * 발행 실패 때 `scope` 의 탭들이 보여야 할 부모 항목 id. 순수 함수.
 *
 * 포커스가 갈 경로(`focusPath`)가 그 탭들 몫이면 그 경로의 부모가 이긴다 — 그 부모가 그려져 있어야 포커스가 닿는다. 아니면
 * 그 탭들의 오류 중 탭 순서상 첫 것의 부모다(나중에 그 탭을 열었을 때 오류가 보이게). 해당 오류가 없으면 `undefined` 라
 * 호출부는 지금 고른 값을 그대로 둔다. 목록 자리 오류(`startingSetups.0.endings` 처럼 부모 아래 배열 자체)도 그 부모다.
 */
export function errorParentItemId<T extends FieldValues>(
  errors: FieldErrors<T>,
  values: T,
  scope: ErrorParentScope,
  tabs: readonly BuilderTab[],
  focusPath: string | undefined,
): string | undefined {
  const fromFocus = focusPath === undefined ? undefined : parentIdOfPath(focusPath, values, scope, tabs);
  if (fromFocus !== undefined) return fromFocus;
  const first = firstErrorLocation(
    errors,
    tabs.filter((tab) => scope.tabIds.includes(tab.id)),
  );
  return first === undefined ? undefined : parentIdOfPath(first.fieldPath, values, scope, tabs);
}
