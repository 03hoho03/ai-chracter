import type { ContentCardProps } from "@/entities/content";

import type { StoryBuilderFormValues } from "./schema";

type StoryToCardContext = {
  thumbnailUrl: string | null;
  authorNickname: string;
};

/**
 * builder-techspec.md §4-3(T-2) — 폼 값 → 프리뷰 카드 props. `formToServer.ts`/`serverToForm.ts`와
 * 같은 변환 경계 자리에 둔다.
 *
 * `thumbnailUrl`은 인자로 받는다 — 폼 값엔 `{assetId}`뿐이라 URL을 만들 수 없다(§7, 1단계에서 추가된
 * `thumbnailUrl` 응답 필드가 그 출처). 발행 전이라 `metrics`는 0, `tags`엔 아직 발행되지 않았음을
 * 나타내는 `unpublished` 배지를 `/my` 초안 카드(`toMyWorkTags`)와 같은 관례로 단다.
 *
 * `onClick`은 `ContentCardProps`에서 필수이지만 프리뷰 카드는 눌러도 갈 상세 페이지가 없다(아직
 * 미발행) — 타입을 바꾸는 대신 아무 일도 하지 않는 핸들러를 준다.
 */
export function formToCard(values: StoryBuilderFormValues, ctx: StoryToCardContext): ContentCardProps {
  return {
    thumbnailUrl: ctx.thumbnailUrl,
    thumbnailAspect: "portrait",
    title: values.profile.name,
    metrics: { viewCount: 0 },
    author: { name: ctx.authorNickname, profileUrl: "" },
    tags: ["story", "unpublished"],
    onClick: () => {},
  };
}
