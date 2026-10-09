import type { BuilderTab } from "@/entities/content";

import { matchTabForPath } from "./fieldErrorPaths";

/**
 * 빈 초안을 발행 검증에 넣었을 때 나온 오류 경로들로 "언제나 필수인 탭"의 id 집합을 만든다. 순수 함수.
 *
 * 빈 초안에서 오류가 나는 탭은 작가가 무엇을 하든 채워야 하는 탭이다. 빈 배열 안 항목의 규칙은 돌지 않으므로
 * "항목을 만들면 그 항목만 필수"인 탭(스탯·엔딩·고급기능 등)은 자연히 빠지고, 기본값이 늘 들어 있는 칸(공개범위·
 * 템플릿)도 빠진다. 필수 여부를 탭 선언에 손으로 적지 않는 이유는 발행 검증과 어긋날 사본을 만들지 않기 위해서다.
 *
 * 경로 매칭은 탭 오류 표시와 같은 `matchTabForPath` 를 쓴다 — 같은 경로가 별표와 오류 표시에서 다른 탭으로 가지 않는다.
 */
export function requiredTabIds(
  issuePaths: readonly (readonly PropertyKey[])[],
  tabs: readonly BuilderTab[],
): ReadonlySet<string> {
  const result = new Set<string>();
  for (const path of issuePaths) {
    const tabId = matchTabForPath(path.map(String).join("."), tabs);
    if (tabId !== undefined) result.add(tabId);
  }
  return result;
}
