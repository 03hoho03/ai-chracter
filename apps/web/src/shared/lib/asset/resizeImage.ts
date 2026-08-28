/** 브라우저 메모리 보호용 원본 상한 — 이보다 큰 파일은 디코드 자체를 시도하지 않는다. */
export const MAX_SOURCE_BYTES = 15 * 1024 * 1024;

export type ResizeImageErrorCode =
  /** 원본이 MAX_SOURCE_BYTES 초과 */
  | "FILE_TOO_LARGE"
  /** 디코드 실패 — 미지원 형식이거나 손상된 파일 */
  | "DECODE_FAILED"
  /** canvas -> WebP 인코딩 실패 */
  | "ENCODE_FAILED";

/** 호출부가 사유별로 다른 안내를 띄울 수 있도록 `code`로 실패를 구분한다. */
export class ResizeImageError extends Error {
  constructor(readonly code: ResizeImageErrorCode, message: string) {
    super(message);
    this.name = "ResizeImageError";
  }
}

export type ResizeSpec = {
  /** 결과물의 긴 변 최대 픽셀 */
  maxEdge: number;
  /** WebP 인코딩 품질 (0~1) */
  quality: number;
}

/**
 * 긴 변이 `maxEdge`가 되도록 비율을 유지해 축소한다. 원본이 이미 `maxEdge` 이하면
 * 확대하지 않고 그대로 돌려준다(서버의 `generate_thumbnail`과 같은 규칙).
 */
export function calculateTargetSize(
  width: number,
  height: number,
  maxEdge: number,
): { width: number; height: number } {
  const longEdge = Math.max(width, height);
  if (longEdge <= maxEdge) return { width, height };

  const scale = maxEdge / longEdge;
  // 극단적인 비율(예: 10000x1)에서 짧은 변이 0으로 반올림되면 canvas가 그리지 못한다.
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

/**
 * 업로드 전에 브라우저에서 이미지를 축소해 WebP File로 바꾼다. 치수가 그대로여도
 * 항상 재인코딩하므로 결과 타입은 언제나 `image/webp`다(호출부의 Content-Type과 일치).
 */
export async function resizeImage(file: File, spec: ResizeSpec): Promise<File> {
  if (file.size > MAX_SOURCE_BYTES) {
    throw new ResizeImageError("FILE_TOO_LARGE", `File exceeds ${MAX_SOURCE_BYTES} bytes`);
  }

  let bitmap: ImageBitmap;
  try {
    // 아이폰 세로 사진이 눕지 않도록 EXIF 회전을 디코드 단계에서 반영한다.
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new ResizeImageError("DECODE_FAILED", "Failed to decode image");
  }

  try {
    const { width, height } = calculateTargetSize(bitmap.width, bitmap.height, spec.maxEdge);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext("2d");
    if (!context) throw new ResizeImageError("ENCODE_FAILED", "Failed to get canvas context");
    context.drawImage(bitmap, 0, 0, width, height);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, "image/webp", spec.quality);
    });
    if (!blob) throw new ResizeImageError("ENCODE_FAILED", "Failed to encode WebP");

    return new File([blob], toWebpName(file.name), { type: "image/webp" });
  } finally {
    bitmap.close();
  }
}

function toWebpName(name: string): string {
  return `${name.replace(/\.[^.]+$/, "")}.webp`;
}
