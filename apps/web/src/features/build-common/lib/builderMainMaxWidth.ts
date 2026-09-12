import { cn } from "@ai-character-chat/ui/lib/utils";

/**
 * builder-preview-validation 회귀 수정 — `BuilderLayout`의 `main`과 `BuilderTopBar`가 각자 문자열로
 * max-width 클래스를 베껴 적으면 한쪽만 고쳤을 때 두 컨테이너의 왼쪽 좌표가 갈린다(672~1023px에서
 * drift가 발생한 원인). 둘 다 이 함수 하나를 호출해 폭을 구조적으로 같게 만든다.
 *
 * `isPreviewOpen`이 `undefined`인 화면(`BuilderTypeSelectPage`, 스켈레톤/에러 상태)은 2단 그리드가
 * 없어 lg 이상에서도 항상 `max-w-2xl`이다 — `BuilderLayout`을 쓰지 않는 화면들이라 이 값도 따로 둔다.
 */
export function builderMainMaxWidth(isPreviewOpen?: boolean): string {
  if (isPreviewOpen === undefined) return "max-w-2xl";
  return cn("lg:max-w-7xl", !isPreviewOpen && "max-w-2xl");
}
