import { atom } from "jotai";

// 열림 여부만 관리한다(URL 동기화 불필요).
export const chatMorePanelOpenAtom = atom(false);
