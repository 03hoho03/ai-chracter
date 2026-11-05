import { atomWithStorage } from "jotai/utils";

import { createSafeJsonStorage } from "@/shared/lib/storage/safeJsonStorage";

import { DEFAULT_READER_SETTINGS, readerSettingsSchema, type ReaderSettings } from "./readerSettings";

/** 뷰어 설정은 이 기기에만 남는 편의값이다(테마는 전역 `themeAtom` 이 따로 맡는다). 저장소가 막혀도 화면이 죽지
 * 않게 안전 저장소를 쓰고, 첫 렌더부터 저장값으로 그리도록 atom 을 만들 때 읽는다. */
export const readerSettingsAtom = atomWithStorage<ReaderSettings>(
  "novel-reader:v1",
  DEFAULT_READER_SETTINGS,
  createSafeJsonStorage(readerSettingsSchema),
  { getOnInit: true },
);
