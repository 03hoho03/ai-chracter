import { ImageOff } from "lucide-react";

import type { ContentVisibility } from "../model/content";

export type ContentCardStatusTag = ContentVisibility | "restricted";

const STATUS_TAG_LABEL: Record<ContentCardStatusTag, string> = {
  public: "공개",
  link: "링크공개",
  private: "비공개",
  restricted: "이용제한",
};

/** techspec-home-discovery.md §3 — 홈/프로필/즐겨찾기 3곳이 공용으로 쓰는 카드. 카드 전체가 클릭 영역
 * (상세 모달 오픈, US-042)이며, `onAuthorClick`이 있으면 작가명만 별도 클릭 영역이 된다(홈의 크리에이터
 * 필터, US-044) — 그래서 바깥 컨테이너는 `<button>`이 아니라 `role="button"` `div`를 쓴다(버튼 안에
 * 버튼을 중첩할 수 없다). */
export function ContentCard({
  thumbnailUrl,
  title,
  viewCount,
  author,
  statusTag,
  priority = false,
  isLcpCandidate = false,
  onClick,
  onAuthorClick,
}: {
  thumbnailUrl: string | null;
  title: string;
  viewCount: number;
  author?: { name: string; profileUrl: string };
  statusTag?: ContentCardStatusTag;
  /** US-013 — 첫 화면에 보이는 카드만 lazy를 풀고 즉시 로드한다. 그리드가
   * `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`라 첫 줄이 뷰포트에 따라 2/3/4장으로 갈리므로,
   * 호출부는 최대값 4를 기준으로 `index < 4`에 준다(좁은 화면에선 2장이 과하게 당겨지는 정도). */
  priority?: boolean;
  /** LCP 후보 1장(`index === 0`)에만 준다 — 여러 장에 주면 우선순위 신호가 희석돼 의미가 없다. */
  isLcpCandidate?: boolean;
  onClick: () => void;
  onAuthorClick?: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onClick();
      }}
      className="flex cursor-pointer flex-col gap-3 rounded-xl border border-border bg-card p-3 text-left transition-colors hover:bg-accent/50"
    >
      <div className="aspect-square overflow-hidden rounded-lg bg-muted">
        {thumbnailUrl ? (
          <img
            src={thumbnailUrl}
            alt=""
            loading={priority ? "eager" : "lazy"}
            fetchPriority={isLcpCandidate ? "high" : "auto"}
            decoding="async"
            className="size-full object-cover"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <p className="truncate text-sm font-semibold text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">조회수 {viewCount.toLocaleString()}</p>
        {author &&
          (onAuthorClick ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onAuthorClick();
              }}
              className="w-fit truncate text-left text-xs text-muted-foreground hover:underline"
            >
              {author.name}
            </button>
          ) : (
            <p className="truncate text-xs text-muted-foreground">{author.name}</p>
          ))}
        {statusTag && (
          <span className="mt-0.5 inline-flex w-fit items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {STATUS_TAG_LABEL[statusTag]}
          </span>
        )}
      </div>
    </div>
  );
}
