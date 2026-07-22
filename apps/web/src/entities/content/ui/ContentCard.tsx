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
  onClick,
  onAuthorClick,
}: {
  thumbnailUrl: string | null;
  title: string;
  viewCount: number;
  author?: { name: string; profileUrl: string };
  statusTag?: ContentCardStatusTag;
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
          <img src={thumbnailUrl} alt="" className="size-full object-cover" />
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
