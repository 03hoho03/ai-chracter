import type { GenerateImagesFormValues } from "./schema";

type ImageAspectRatio = GenerateImagesFormValues["aspectRatio"];

/** 결과 영역이 그릴 모양 — 몇 장을 어떤 비율로. 빈 상태는 폼의 현재 값, 생성 뒤에는 제출한 값이다. */
export type ResultShape = { aspectRatio: ImageAspectRatio; count: number };

/** 결과 타일 높이 상한. 결과 이미지는 어두운 화면에서 유일하게 밝은 면이라, 세로로 긴 비율이
 * 중앙 열 폭을 다 쓰면 한 장이 화면 대부분을 밝힌다. 글 속 그림 블록(`MediaImageFrame`)과 같은 값이다. */
export const RESULT_TILE_MAX_HEIGHT_PX = 320;

/** `"16:9"` 같은 비율 문자열을 폭·높이 숫자로 나눈다. 비율 칩 도형과 결과 타일이 같은 파서를 쓴다. */
export function parseAspectRatio(ratio: ImageAspectRatio): { width: number; height: number } {
  // noUncheckedIndexedAccess — split 결과의 각 자리는 string | undefined다.
  const [widthPart, heightPart] = ratio.split(":");
  return { width: Number(widthPart ?? ""), height: Number(heightPart ?? "") };
}

/** 결과 그리드의 열 정의와 타일 비율. 열 수는 장수와 같아 한 장일 때 빈 열이 남지 않는다.
 *
 * 높이 상한은 타일이 아니라 **열 폭**에 건다 — `aspect-ratio`에 `max-height`를 걸면 높이만 잘리고
 * 폭은 줄지 않는다(DESIGN.md Media images 절). 열 폭 상한을 "높이가 상한에 닿는 폭"으로 두면, 넓은
 * 열에서는 그 폭에서 멈추고 좁은 열에서는 열 폭에 맞춰 줄며 높이는 비율이 정한다. 빈 상태 칸·
 * 스켈레톤·결과 타일이 이 값 하나를 함께 써서 결과가 도착해도 칸 크기가 바뀌지 않는다. */
export function getResultTileLayout(
  ratio: ImageAspectRatio,
  count: number,
): { gridTemplateColumns: string; aspectRatio: string } {
  const { width, height } = parseAspectRatio(ratio);
  const maxColumnWidth = Math.round((RESULT_TILE_MAX_HEIGHT_PX * width) / height);
  return {
    gridTemplateColumns: `repeat(${count}, minmax(0, ${maxColumnWidth}px))`,
    aspectRatio: `${width} / ${height}`,
  };
}
