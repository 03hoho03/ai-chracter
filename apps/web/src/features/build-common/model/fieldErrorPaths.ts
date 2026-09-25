import type { BuilderTab } from "@/entities/content";

/** RHF `FieldErrors`는 중첩 객체/배열이고 **잎에만** `{type, message, ref}`가 있다 — `type`이 문자열인
 * 자리를 잎으로 판정하고 그 아래로는 내려가지 않는다.
 *
 * `type`만으로 판정하면 `form.setError(path, {message})`로 심은 에러를 놓친다 — RHF의 `setError`
 * 내부(`Ne`)가 호출자가 준 객체만 스프레드해 `{message, ref}`를 만들고 `type`을 채워 넣지 않는다.
 * 그래서 `type` 또는 `message`가 문자열이면 잎으로 본다. 중간 노드(중첩 객체/배열)는 이 필드를
 * 직접 갖지 않는다 — 배열 자체의 에러는 `root`라는 별도 키 아래 담기고(`errorTabs.test.ts`), 그
 * 자리가 같은 값이면 애초에 아래로 내려갈 자식이 없는 잎이다. */
function isFieldErrorLeaf(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  return ("type" in value && typeof value.type === "string") || ("message" in value && typeof value.message === "string");
}

/** `root`는 RHF의 예약 키라 폼 경로가 아니다 — 배열 자체의 위반(`.max()` 등)이 인덱스 자리를 못
 * 차지할 때 여기 담긴다(`errorTabs.test.ts`). 꼬리의 `.root`만 벗긴다 — `errors.root`(폼 전체
 * 에러)·`errors.root.server`처럼 접두 없이 단독인 `root`는 그 자체가 유효한 경로이므로 그대로 둔다
 * (길이 1이면 벗길 상위 세그먼트가 없다는 뜻이기도 하다). */
function stripTrailingRoot(segments: readonly string[]): readonly string[] {
  if (segments.length > 1 && segments[segments.length - 1] === "root") return segments.slice(0, -1);
  return segments;
}

function collectPaths(node: unknown, prefix: readonly string[], paths: string[]): void {
  if (node === undefined || node === null || typeof node !== "object") return;
  if (isFieldErrorLeaf(node)) {
    paths.push(stripTrailingRoot(prefix).join("."));
    return;
  }
  for (const [key, value] of Object.entries(node)) {
    collectPaths(value, [...prefix, key], paths);
  }
}

/**
 * `errors`를 `startingSetups.0.stats.1.name` 형태의 경로 문자열 배열로 평탄화한다.
 * 배열의 빈 인덱스(에러 없는 자리)는 `Object.entries`가 건너뛰므로 별도 처리가 필요 없다.
 *
 * 순서는 `Object.entries`의 열거 순서 — 문자열 키는 삽입 순서, 배열 인덱스는 오름차순이라 스키마
 * 선언 순서와 자연히 일치한다(`firstErrorLocation`이 한 탭 내부 결정론을 여기에 기댄다).
 */
export function flattenFieldErrorPaths(errors: unknown): string[] {
  const paths: string[] = [];
  collectPaths(errors, [], paths);
  return paths;
}

function matchesPrefix(pathSegments: readonly string[], prefixSegments: readonly string[]): boolean {
  if (prefixSegments.length > pathSegments.length) return false;
  return prefixSegments.every((segment, index) => segment === "*" || segment === pathSegments[index]);
}

/**
 * 경로 하나에 매칭되는 탭 id. 여러 탭의 `fields` 프리픽스가 매칭될 수 있어 **프리픽스 세그먼트 수
 * 내림차순**으로 가장 구체적인 것을 고른다 — 탭 배열의 선언 순서에 의존하지 않는다. 동률이면
 * (설계상 발생하지 않아야 하지만) 탭 배열에서 더 앞선 탭을 우선한다.
 */
export function matchTabForPath(path: string, tabs: readonly BuilderTab[]): string | undefined {
  const pathSegments = path.split(".");
  let best: { tabId: string; specificity: number; order: number } | undefined;

  tabs.forEach((tab, order) => {
    for (const prefix of tab.fields) {
      const prefixSegments = prefix.split(".");
      if (!matchesPrefix(pathSegments, prefixSegments)) continue;
      const specificity = prefixSegments.length;
      if (!best || specificity > best.specificity || (specificity === best.specificity && order < best.order)) {
        best = { tabId: tab.id, specificity, order };
      }
    }
  });

  return best?.tabId;
}
