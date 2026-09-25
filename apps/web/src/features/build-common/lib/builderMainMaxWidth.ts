import { cn } from "@ai-character-chat/ui/lib/utils";

/**
 * `BuilderLayout`의 `main` 전용 함수다 — `BuilderTopBar`는 full-bleed로 바뀌며 이 함수를 더는
 * 호출하지 않는다(유일한 호출자는 `BuilderLayout`). 그래도 남기는
 * 이유는 프리뷰 열림 여부로 갈리는 max-width 식(`lg:max-w-7xl` vs `max-w-2xl`)을 한 곳에 두기
 * 위해서다.
 */
export function builderMainMaxWidth(isPreviewOpen: boolean): string {
  return cn("lg:max-w-7xl", !isPreviewOpen && "max-w-2xl");
}
