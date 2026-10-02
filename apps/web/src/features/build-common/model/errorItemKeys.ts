import { get, type FieldErrors, type FieldValues } from "react-hook-form";

import type { BuilderTab } from "@/entities/content";

import { indexOpenKey, itemOpenKey } from "./builderUiState";
import { flattenFieldErrorPaths, matchTabForPath } from "./fieldErrorPaths";

/** 접히는 반복 항목 목록 하나. 열림 키의 목록 이름은 이 정의를 담은 객체의 키다. */
export type CollapsibleListSpec = {
  /** 배열 경로. 부모 배열의 인덱스 자리는 `*`(예: `startingSetups.*.stats`). */
  path: string;
  /** 이 목록을 그리는 탭. 오류 경로가 이 탭에 속할 때만 이 목록의 항목을 연다. */
  tabId: string;
  /** `id` 면 항목 값의 `id` 로, `index` 면 배열 위치로 열림 키를 만든다(값 id 가 없는 배열). */
  key: "id" | "index";
};

/**
 * 발행 실패 오류에서 "오류를 품은 항목"의 열림 키를 모은다. 순수 함수.
 *
 * 오류 경로마다 먼저 탭을 판정하고(`matchTabForPath`), 그 탭이 그리는 목록만 대조한다. `startingSetups.0.stats.1.name`
 * 은 `startingSetups` 목록의 0번 항목 아래이기도 하지만 스탯 탭 몫이라, 접두만 보면 스탯 오류 하나로 시작설정 카드까지
 * 펼쳐진다. 같은 탭의 목록끼리는 겹쳐도 된다 — 엔딩 안 규칙 오류는 엔딩 카드와 규칙 그룹을 함께 연다(규칙이 엔딩
 * 본문 안에 있다).
 *
 * 배열 자체에 걸린 오류(`.root`·배열 노드의 `message`)는 항목 인덱스가 없어 키를 내지 않는다 — 목록 머리의 오류 문장이
 * 맡는다. 값 id 는 `values` 에서 읽으며, 그 자리에 항목이 없거나 id 가 문자열이 아니면 건너뛴다.
 */
export function errorItemKeys<T extends FieldValues>(
  errors: FieldErrors<T>,
  values: T,
  lists: Readonly<Record<string, CollapsibleListSpec>>,
  tabs: readonly BuilderTab[],
): Set<string> {
  const keys = new Set<string>();
  const specs = Object.entries(lists);

  for (const path of flattenFieldErrorPaths(errors)) {
    const tabId = matchTabForPath(path, tabs);
    if (tabId === undefined) continue;
    const segments = path.split(".");

    for (const [list, spec] of specs) {
      if (spec.tabId !== tabId) continue;
      const key = itemKeyForPath(list, spec, segments, values);
      if (key !== undefined) keys.add(key);
    }
  }
  return keys;
}

function itemKeyForPath(
  list: string,
  spec: CollapsibleListSpec,
  segments: readonly string[],
  values: FieldValues,
): string | undefined {
  const pattern = spec.path.split(".");
  if (!pattern.every((part, index) => part === "*" || part === segments[index])) return undefined;

  // 배열 경로에서 끝나는 오류(배열 자체 오류)는 인덱스 자리가 비어 있다. 배열 자리 다음 세그먼트는 언제나 인덱스다 —
  // `.root` 는 오류 경로를 평탄화할 때 꼬리에서 벗겨진다.
  const indexSegment = segments[pattern.length];
  if (indexSegment === undefined) return undefined;
  if (spec.key === "index") return indexOpenKey(list, Number(indexSegment));

  const id: unknown = get(values, [...segments.slice(0, pattern.length + 1), "id"].join("."));
  return typeof id === "string" ? itemOpenKey(list, id) : undefined;
}
