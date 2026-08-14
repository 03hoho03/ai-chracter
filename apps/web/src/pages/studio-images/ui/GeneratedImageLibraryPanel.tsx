import { Button } from "@ai-character-chat/ui/components/button";
import { Images } from "lucide-react";

import { useGeneratedImagesQuery } from "@/entities/generated-image";

const createdAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function LibraryGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((key) => (
        <div key={key} className="flex flex-col gap-1.5">
          <div className="aspect-square motion-safe:animate-pulse rounded-lg bg-muted" />
          <div className="h-3 w-16 motion-safe:animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

/** prd-image-library US-004 — '내 이미지' 탭. 생성 이미지를 최신순 그리드로 보여준다
 * (정렬은 서버의 created_at desc 그대로). 사용처 표시는 US-005, 삭제는 US-006이 붙인다. */
export function GeneratedImageLibraryPanel({
  onNavigateToGenerate,
}: {
  onNavigateToGenerate: () => void;
}) {
  const galleryQuery = useGeneratedImagesQuery(true);
  const images = galleryQuery.data;

  if (galleryQuery.isPending) {
    return <LibraryGridSkeleton />;
  }

  if (galleryQuery.isError) {
    return (
      <p className="py-4 text-sm text-destructive">
        목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (images === undefined || images.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center">
        <Images aria-hidden className="size-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          아직 생성한 이미지가 없어요.
          <br />
          프롬프트 한 줄로 첫 이미지를 만들어보세요.
        </p>
        <Button variant="outline" size="sm" onClick={onNavigateToGenerate}>
          이미지 생성하러 가기
        </Button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {images.map((image) => (
        <figure key={image.assetId} className="flex flex-col gap-1.5">
          <div className="aspect-square overflow-hidden rounded-lg bg-muted">
            <img src={image.imageUrl} alt="" className="size-full object-cover" />
          </div>
          <figcaption className="text-xs text-muted-foreground">
            <time dateTime={image.createdAt}>{createdAtFormatter.format(new Date(image.createdAt))}</time>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
