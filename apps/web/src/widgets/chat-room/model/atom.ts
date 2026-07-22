import { atom } from "jotai";

// techspec-chat-story.md §6 — 열림 여부만 관리한다(URL 동기화 불필요).
export const chatMorePanelOpenAtom = atom(false);
