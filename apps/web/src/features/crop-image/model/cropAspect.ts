/** 자르기 창에서 고를 수 있는 비율 하나. `original` 은 그림 자체의 비율이다 — 확대하지 않으면 그림이 잘리지 않고 남는다. */
export type CropAspectChoice = { label: string; ratio: number | "original" };

/** 고른 비율 칩의 가로 대 세로. 원본 칩은 그림 크기가 와야 정해진다(그 전에는 `undefined`). */
export function toCropAspect(
  choice: CropAspectChoice,
  media: { width: number; height: number } | undefined,
): number | undefined {
  if (choice.ratio !== "original") return choice.ratio;
  return media === undefined ? undefined : media.width / media.height;
}
