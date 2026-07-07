import { atom } from "jotai";

/**
 * techspec-content-detail.md §1 — 홈/프로필 등 카드 리스트가 상세화면을 모달로 여는 전역 상태.
 * `entities/content`의 `ContentType`을 재사용하지 않고 그대로 리터럴을 두는 이유는
 * `shared/model/content-type-toggle.ts`와 동일(하위 레이어는 상위 레이어를 import하지 않는다).
 */
export type ContentDetailModalState = { type: "character" | "story"; id: string } | null;

export const contentDetailModalAtom = atom<ContentDetailModalState>(null);
