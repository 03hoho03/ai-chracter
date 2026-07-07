import { ImageOff } from "lucide-react";

import type { ContentVisibility } from "../model/types";

export type ContentCardStatusTag = ContentVisibility | "restricted";

const STATUS_TAG_LABEL: Record<ContentCardStatusTag, string> = {
  public: "공개",
  link: "링크공개",
  private: "비공개",
  restricted: "이용제한",
};

/** techspec-home-discovery.md §3 — 홈/프로필/즐겨찾기 3곳이 공용으로 쓰는 카드. 인터랙션 버튼 없이
 * 카드 전체가 클릭 영역이며, 호출부가 onClick으로 상세 모달 오픈 등에 사용한다(US-042). */
export function ContentCard({
  thumbnailUrl,
  title,
  viewCount,
  author,
  statusTag,
  onClick,
}: {
  thumbnailUrl: string | null;
  title: string;
  viewCount: number;
  author?: { name: string; profileUrl: string };
  statusTag?: ContentCardStatusTag;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 text-left transition-colors hover:bg-accent/50"
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
        {author && <p className="truncate text-xs text-muted-foreground">{author.name}</p>}
        {statusTag && (
          <span className="mt-0.5 inline-flex w-fit items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {STATUS_TAG_LABEL[statusTag]}
          </span>
        )}
      </div>
    </button>
  );
}
