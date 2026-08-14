import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Link } from "@tanstack/react-router";
import { BookOpen, ChevronRight, UserRound } from "lucide-react";

import type { GeneratedImageItem } from "@/entities/generated-image";

const createdAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const FIELD_LABEL: Record<GeneratedImageItem["usages"][number]["field"], string> = {
  thumbnail: "썸네일",
  situationalImage: "상황 이미지",
};

/** prd-image-library US-005 — 그리드 셀을 눌러 여는 생성 이미지 상세 모달. 이 이미지를 쓰는
 * 작품(usages) 목록을 보여주고 각 항목에서 해당 작품 상세로 이동한다. US-006 삭제 액션은
 * 여기에 붙는다. */
export function GeneratedImageDetailModal({
  image,
  onClose,
}: {
  image: GeneratedImageItem;
  onClose: () => void;
}) {
  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>생성 이미지</DialogTitle>
          <DialogDescription>
            <time dateTime={image.createdAt}>
              {createdAtFormatter.format(new Date(image.createdAt))}
            </time>{" "}
            생성
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-hidden rounded-lg bg-muted">
          <img src={image.imageUrl} alt="" className="aspect-square w-full object-cover" />
        </div>

        <div className="flex flex-col gap-1.5">
          <h3 className="text-sm font-medium text-foreground">사용 중인 작품</h3>
          {image.usages.length === 0 ? (
            <p className="text-sm text-muted-foreground">아직 사용 중인 작품이 없어요.</p>
          ) : (
            <ul className="flex flex-col">
              {image.usages.map((usage) => (
                <li key={`${usage.contentId}-${usage.field}`}>
                  <Link
                    to="/content/$type/$id"
                    params={{ type: usage.contentType, id: usage.contentId }}
                    className="-mx-2 flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-accent motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    {usage.contentType === "character" ? (
                      <UserRound aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <BookOpen aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                      {usage.contentTitle}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {FIELD_LABEL[usage.field]}
                    </span>
                    <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
