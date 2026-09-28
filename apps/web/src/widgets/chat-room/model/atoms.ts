import { atom } from "jotai";

// 채팅 헤더 아래 옆 패널은 한 번에 하나만 열린다(더보기 또는 기억 노트). 불리언 두 개를 따로 두면 둘이
// 함께 열린 불가능한 상태가 생기므로 판별값 하나로 든다. URL 동기화는 하지 않는다.
export type ChatSidePanel = "more" | "memory";
export const chatSidePanelAtom = atom<ChatSidePanel | null>(null);
