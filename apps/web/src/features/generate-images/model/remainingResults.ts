import type { ImageJobStatusResponse } from "@/entities/image-job";

type RemainingResultsInput = {
  job: Pick<ImageJobStatusResponse, "status"> & { images: readonly { assetId: string }[] };
  /** 제출한 장수 — 아직 안 나온 칸(스켈레톤)이 남았는지 센다. */
  requestedCount: number;
  hasPollError: boolean;
  hiddenAssetIds: ReadonlySet<string>;
};

/** 받은 결과를 이 화면에서 모두 지워, 결과 영역에 보여 줄 칸이 하나도 안 남았는가.
 *
 * 참이면 결과 영역은 첫 생성 전의 빈 상태로 돌아간다 — 지운 칸을 빈 열로 남기면 "완료" 문구 아래에
 * 아무것도 없는 화면이 된다. 아직 나올 칸(스켈레톤)이 남았거나 실패·폴링 오류 안내를 띄울 때는
 * 보여 줄 것이 있으므로 거짓이다. 받은 이미지가 없으면 지운 것도 없으니 거짓이다. */
export function isEveryResultHidden({
  job,
  requestedCount,
  hasPollError,
  hiddenAssetIds,
}: RemainingResultsInput): boolean {
  if (job.status === "failed" || job.images.length === 0) return false;
  if (job.status !== "succeeded" && (hasPollError || job.images.length < requestedCount)) return false;
  return job.images.every((image) => hiddenAssetIds.has(image.assetId));
}
