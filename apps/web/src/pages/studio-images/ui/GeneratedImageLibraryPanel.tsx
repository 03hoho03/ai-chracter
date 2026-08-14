import { useState } from "react";

import { Button } from "@ai-character-chat/ui/components/button";
import { Images } from "lucide-react";

import { useGeneratedImagesQuery } from "@/entities/generated-image";

import { GeneratedImageDetailModal } from "./GeneratedImageDetailModal";

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

/** prd-image-library US-004/US-005/US-006 — '내 이미지' 탭. 생성 이미지를 최신순 그리드로
 * 보여준다(정렬은 서버의 created_at desc 그대로). 사용 중인 이미지에는 사용처 배지를 달고,
 * 셀을 누르면 사용처 목록·삭제가 있는 상세 모달을 연다. */
export function GeneratedImageLibraryPanel({
  onNavigateToGenerate,
}: {
  onNavigateToGenerate: () => void;
}) {
  const galleryQuery = useGeneratedImagesQuery(true);
  const images = galleryQuery.data;
  // 항목 스냅샷이 아니라 id로 선택하고 목록에서 매번 찾는다 — 삭제 409로 목록을 다시 받으면
  // 열려 있는 상세 모달이 갱신된 usages를 보여줘야 한다(항목이 사라지면 모달도 내려간다).
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const selectedImage = images?.find((image) => image.assetId === selectedAssetId);

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
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {images.map((image) => {
          const createdAtLabel = createdAtFormatter.format(new Date(image.createdAt));
          return (
            <figure key={image.assetId} className="flex flex-col gap-1.5">
              <button
                type="button"
                aria-label={`${createdAtLabel} 생성 이미지 상세 보기`}
                onClick={() => setSelectedAssetId(image.assetId)}
                className="aspect-square overflow-hidden rounded-lg bg-muted motion-safe:transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <img src={image.imageUrl} alt="" className="size-full object-cover" />
              </button>
              <figcaption className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
                <time dateTime={image.createdAt}>{createdAtLabel}</time>
                {image.usages.length > 0 && (
                  <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                    {image.usages.length}곳에서 사용 중
                  </span>
                )}
              </figcaption>
            </figure>
          );
        })}
      </div>

      {selectedImage !== undefined && (
        <GeneratedImageDetailModal image={selectedImage} onClose={() => setSelectedAssetId(null)} />
      )}
    </>
  );
}
