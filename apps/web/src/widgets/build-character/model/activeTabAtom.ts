import { atom } from "jotai";

/** techspec-builder-character.md §0 AC — 캐릭터 빌더 5탭. */
export type CharacterBuilderTab = "profile" | "intro" | "prompt" | "advanced" | "detail";

export const characterBuilderActiveTabAtom = atom<CharacterBuilderTab>("profile");
