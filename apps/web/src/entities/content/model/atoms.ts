import { atom } from "jotai";

import type { ContentType } from "./content";

/** 홈/프로필 등 카드 리스트가 상세화면을 모달로 여는 전역 상태. */
export type ContentDetailModalState = { type: ContentType; id: string } | undefined;

export const contentDetailModalAtom = atom<ContentDetailModalState>(undefined);
