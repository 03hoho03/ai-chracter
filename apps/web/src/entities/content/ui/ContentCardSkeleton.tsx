import { cn } from "@ai-character-chat/ui/lib/utils";

import { toThumbnailAspectClass } from "../model/cardLayout";
import { ContentCard, type ContentCardProps } from "./ContentCard";

export type ContentCardSkeletonProps = Pick<
  ContentCardProps,
  "thumbnailAspect" | "metrics" | "tags" | "actions"
>;

/** card-grid-techspec.md T-5 — 보이지 않는 실제 카드가 레이아웃(높이)을 만들고, 그 위에 보이는 펄스 층을
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
        thumbnailUrl={null}
        // ⚠️ 반드시 nbsp(` `) — 빈 문자열은 `truncate`(`overflow: hidden`) <p>의 라인박스를
        // 0px로 붕괴시킨다. 일반 공백 `" "`로 고쳐도 collapse 되어 똑같이 0px이라 안 된다 — nbsp라야
        // 라인박스가 생긴다. 내용이 무엇인지는 상관없다 — 카드가 `invisible`이고 제목은 `truncate`라
        // 항상 1줄이라 라인박스만 생기면 높이가 정확히 맞는다. `actions`가 있는 화면은 그 32px 버튼이
        // 제목 줄 높이를 정해 이 붕괴가 가려지므로, 실제 영향은 `actions` 없는 홈·즐겨찾기·타인 프로필
        // (`isOwner=false`)뿐이고 `/my`·본인 프로필은 영향 없다.
        // 근거: card-grid-techspec.md T-5 · card-grid-progress.md 2-19 실측.
        title=" "
        metrics={metrics}
        tags={tags}
        actions={actions}
        onClick={() => {}}
      />
      <div aria-hidden className="absolute inset-0 flex flex-col overflow-hidden rounded-xl">
        <div
          className={cn(toThumbnailAspectClass(thumbnailAspect), "bg-muted animate-pulse")}
        />
        <div className="flex-1 bg-muted animate-pulse" />
      </div>
    </div>
  );
}
