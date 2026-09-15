import type { Area } from "react-easy-crop";

export type CropToFileErrorCode =
  /** 디코드 실패 — 미지원 형식이거나 손상된 파일 */
  | "DECODE_FAILED"
  /** canvas -> Blob 인코딩 실패 */
  | "ENCODE_FAILED";

/** 호출부가 사유별로 다른 안내를 띄울 수 있도록 `code`로 실패를 구분한다
 * (`shared/lib/asset/resizeImage.ts`의 `ResizeImageError`와 같은 패턴). */
export class CropToFileError extends Error {
  constructor(
    readonly code: CropToFileErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "CropToFileError";
  }
}

/**
 * `react-easy-crop`의 `onCropComplete`가 주는 `croppedAreaPixels`(원본 naturalWidth/Height
 * 좌표계의 픽셀 사각형)로 파일을 잘라 새 `File`을 만든다. 이 결과는 `resizeImage(file, spec)`
 * (`shared/lib/asset/resizeImage.ts:51`)가 받아 WebP로 재인코딩하므로 여기서 포맷을 맞출 필요는
 * 없다 — canvas `toBlob`의 PNG(무손실)를 그대로 쓴다. 중간 산출물이라 화질 손실이 없는 쪽이
 * 안전하다는 판단이다(용량은 바로 뒤 리사이즈 단계에서 정리된다).
 *
 * EXIF 회전: `resizeImage`는 `createImageBitmap(file, { imageOrientation: "from-image" })`로
 * 회전을 구워 넣는다. `react-easy-crop`이 크롭 UI에 그리는 이미지도 같은 방향이다(브라우저
 * `<img>`가 기본으로 EXIF 방향을 반영해 렌더링하고 `naturalWidth/Height`도 그 기준으로 보고한다) —
 * 즉 `croppedAreaPixels`는 회전이 반영된 좌표계다. 크롭 단계에서 같은 옵션으로 디코드하지 않으면
 * 좌표계가 어긋나 회전된 사진에서 엉뚱한 곳이 잘린다.
 *
 * canvas를 쓰므로 유닛 테스트는 만들지 않는다 — `apps/web/vitest.config.ts`가 `environment: "node"`라
 * canvas가 없다(`shared/lib/asset/resizeImage.test.ts`가 canvas 경로를 테스트하지 않는 것과 같은 이유).
 */
export async function cropToFile(file: File, area: Area): Promise<File> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new CropToFileError("DECODE_FAILED", "Failed to decode image");
  }

  try {
    const canvas = document.createElement("canvas");
    canvas.width = area.width;
    canvas.height = area.height;

    const context = canvas.getContext("2d");
    if (!context) throw new CropToFileError("ENCODE_FAILED", "Failed to get canvas context");
    context.drawImage(bitmap, area.x, area.y, area.width, area.height, 0, 0, area.width, area.height);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/png");
    });
    if (!blob) throw new CropToFileError("ENCODE_FAILED", "Failed to encode PNG");

    return new File([blob], toPngName(file.name), { type: "image/png" });
  } finally {
    bitmap.close();
  }
}

function toPngName(name: string): string {
  return `${name.replace(/\.[^.]+$/, "")}.png`;
}
