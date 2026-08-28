import { Loader2 } from "lucide-react";

import type { ImageJobStatusResponse } from "@/entities/image-job";

type GenerateImagesResultGridProps = {
  job: ImageJobStatusResponse | undefined;
  requestedCount: number;
  isQueryError: boolean;
}

// US-008 — 폴링 상태를 그리드로 보여준다. 완료 전엔 남은 칸을 스켈레톤으로 채워 진행률을 드러내고,
// 완료(succeeded)되면 실제 결과만, 실패(failed)면 에러 메시지를 보여준다.
// 그리드 스타일은 select-generated-image/GeneratedImagePickerModal과 동일(grid-cols-3 gap-2 + aspect-square rounded-md bg-muted).
export function GenerateImagesResultGrid({
  job,
  requestedCount,
  isQueryError,
}: GenerateImagesResultGridProps) {
  if (isQueryError) {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        진행 상황을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  if (!job) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="size-4 motion-safe:animate-spin" />
          <span>생성 준비 중...</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {Array.from({ length: requestedCount }, (_, i) => (
            <div key={i} className="aspect-square rounded-md bg-muted motion-safe:animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (job.status === "failed") {
    return (
      <p role="alert" className="text-sm text-destructive-text">
        {job.error ?? "이미지 생성에 실패했어요. 잠시 후 다시 시도해주세요."}
      </p>
    );
  }

  const isTerminal = job.status === "succeeded";
  const skeletonCount = isTerminal ? 0 : Math.max(job.requestedCount - job.images.length, 0);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {!isTerminal && <Loader2 aria-hidden className="size-4 motion-safe:animate-spin" />}
        <span>
          {isTerminal
            ? `${job.images.length}장 생성 완료`
            : `${job.completedCount}/${job.requestedCount}장 생성 중...`}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {job.images.map((image) => (
          <div key={image.assetId} className="aspect-square overflow-hidden rounded-md bg-muted">
            <img
              src={image.imageUrl}
              alt=""
              loading="lazy"
              decoding="async"
              className="size-full object-cover"
            />
          </div>
        ))}
        {Array.from({ length: skeletonCount }, (_, i) => (
          <div key={`pending-${i}`} className="aspect-square rounded-md bg-muted motion-safe:animate-pulse" />
        ))}
      </div>
    </div>
  );
}
