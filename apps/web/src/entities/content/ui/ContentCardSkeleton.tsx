import { cn } from "@ai-character-chat/ui/lib/utils";

import { toThumbnailAspectClass } from "./cardLayoutClass";
import { ContentCard, type ContentCardProps } from "./ContentCard";

export type ContentCardSkeletonProps = Pick<
  ContentCardProps,
  "thumbnailAspect" | "metrics" | "tags" | "actions"
>;

/** 보이지 않는 실제 카드가 레이아웃(높이)을 만들고, 그 위에 보이는 펄스 층을
 * 얹는 2층 구조다. 손으로 잰 높이 수치(제목 줄 32px·배지 행 22.5px 등)에 더는 의존하지 않는다 — 높이의
 * 유일한 소스가 카드 자신이라 카드 구조가 바뀌어도 스켈레톤이 자동으로 따라온다.
 *
 * 화면별 카드 구성 차이(⋯ 유무, 배지 유무, 지표 개수)는 이 더미 props로 표현한다 — 이 컴포넌트 자신은
 * 그 분기를 모른다. `metaLabel`은 받지 않는다 — 그 줄만 `break-keep`으로 2줄이 될 수 있는 소수 카드용
 * 이라 더미에 넣으면 다수 카드의 높이가 틀어진다. */
export function ContentCardSkeleton({ thumbnailAspect, metrics, tags, actions }: ContentCardSkeletonProps) {
  return (
    <div className="relative">
      <ContentCard
        inert
        className="invisible"
        thumbnailAspect={thumbnailAspect}
        // ⚠️ 반드시 `null` — `visibility: hidden`은 이미지 fetch를 막지 못한다(실측: 요청이 나가고 200
        // 응답). `null`이면 `ImageOff` 분기로 빠져 `<img>` 자체가 만들어지지 않는다.
        // ⚠️ 반드시 nbsp(` `) — 빈 문자열은 여전히 라인박스를 만들지 않는다(일반 공백 `" "`로 고쳐도
        // collapse 되어 똑같다 — nbsp라야 라인박스가 생긴다).
        // 제목 박스는 `line-clamp-2` + `min-h-[2lh]`로 콘텐츠 길이·줄 수와 무관하게 항상 45.7031px로
        // 고정되므로, nbsp 한 줄만 있어도 실제 제목과 정확히 같은 높이가 나온다. `actions`(32px 버튼)는
        // 이제 제목 행 높이보다 작아(32 < 45.7) 그 행 높이를 정하는 쪽이 아니므로, `actions` 유무가
        // 제목 행 높이에 영향을 주는 경로 자체가 사라졌다 — 이 계산은 `actions` 유무·`/my`·본인 프로필
        // 여부와 무관하게 모든 화면에서 똑같이 성립한다.
        title=" "
        metrics={metrics}
        tags={tags}
        actions={actions}
        onClick={() => {}}
      />
      <div aria-hidden className="absolute inset-0 flex flex-col gap-2">
        <div
          className={cn(toThumbnailAspectClass(thumbnailAspect), "rounded-xl bg-muted animate-pulse")}
        />
        <div className="flex-1 rounded-md bg-muted animate-pulse" />
      </div>
    </div>
  );
}
