export interface ColorPaletteSwatch {
  name: string;
  label: string;
  /** CSS `color` 값(oklch) — 소비처가 별도 변환 없이 `style={{ backgroundColor: value }}`로 바로 쓸 수 있다. */
  value: string;
}

/**
 * 사전 정의 색상 팔레트(techspec-builder-story.md §1.2) — 스탯 등 사용자가 색상을 직접 고르는
 * 도메인에서 공유한다. 자유 hex 입력이 아니라 이 10개 중에서만 고르게 해 디자인 일관성을 유지한다.
 */
export const COLOR_PALETTE: ColorPaletteSwatch[] = [
  { name: "rose", label: "로즈", value: "oklch(0.62 0.19 350)" },
  { name: "orange", label: "오렌지", value: "oklch(0.68 0.17 45)" },
  { name: "amber", label: "앰버", value: "oklch(0.78 0.17 80)" },
  { name: "lime", label: "라임", value: "oklch(0.75 0.19 130)" },
  { name: "emerald", label: "에메랄드", value: "oklch(0.68 0.15 160)" },
  { name: "teal", label: "틸", value: "oklch(0.68 0.13 190)" },
  { name: "sky", label: "스카이", value: "oklch(0.68 0.14 230)" },
  { name: "indigo", label: "인디고", value: "oklch(0.55 0.18 270)" },
  { name: "violet", label: "바이올렛", value: "oklch(0.6 0.19 300)" },
  { name: "fuchsia", label: "푸시아", value: "oklch(0.62 0.22 320)" },
];
