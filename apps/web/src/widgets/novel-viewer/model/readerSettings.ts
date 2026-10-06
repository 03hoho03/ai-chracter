import { atomWithStorage } from "jotai/utils";
import { z } from "zod";

import { createSafeJsonStorage } from "@/shared/lib/storage/safeJsonStorage";

export const READER_FONT_SIZES = ["small", "medium", "large"] as const;
export const READER_LINE_HEIGHTS = ["normal", "relaxed", "loose"] as const;
export const READER_MARGINS = ["narrow", "medium", "wide"] as const;

export type ReaderFontSize = (typeof READER_FONT_SIZES)[number];
export type ReaderLineHeight = (typeof READER_LINE_HEIGHTS)[number];
export type ReaderMargin = (typeof READER_MARGINS)[number];

export type ReaderSettings = {
  fontSize: ReaderFontSize;
  lineHeight: ReaderLineHeight;
  margin: ReaderMargin;
};

/** 본문 기본(`text-sm`)·v1 소설 본문의 줄 간격(`leading-relaxed`)과 같은 값에서 시작한다. */
export const DEFAULT_READER_SETTINGS: ReaderSettings = {
  fontSize: "small",
  lineHeight: "relaxed",
  margin: "medium",
};

/** 칸마다 `.catch` 로 기본값에 떨어진다 — 저장된 값 중 하나만 깨졌거나(옛 단계 이름) 나중에 칸이 늘어 옛 저장값에
 * 없을 때, 나머지 사용자가 고른 값까지 버리지 않기 위해서다. 저장값이 객체가 아니면 통째로 기본값이 된다. */
export const readerSettingsSchema = z.object({
  fontSize: z.enum(READER_FONT_SIZES).catch(DEFAULT_READER_SETTINGS.fontSize),
  lineHeight: z.enum(READER_LINE_HEIGHTS).catch(DEFAULT_READER_SETTINGS.lineHeight),
  margin: z.enum(READER_MARGINS).catch(DEFAULT_READER_SETTINGS.margin),
});

/** 뷰어 설정은 이 기기에만 남는 편의값이다(테마는 전역 `themeAtom` 이 따로 맡는다). 저장소가 막혀도 화면이 죽지
 * 않게 안전 저장소를 쓰고, 첫 렌더부터 저장값으로 그리도록 atom 을 만들 때 읽는다. */
export const readerSettingsAtom = atomWithStorage<ReaderSettings>(
  "novel-reader:v1",
  DEFAULT_READER_SETTINGS,
  createSafeJsonStorage(readerSettingsSchema),
  { getOnInit: true },
);
