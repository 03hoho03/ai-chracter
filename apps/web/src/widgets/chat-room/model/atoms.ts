import { atom } from "jotai";

// 채팅 헤더 아래 옆 패널은 한 번에 하나만 열린다(더보기 또는 기억 노트). 불리언 두 개를 따로 두면 둘이
// 함께 열린 불가능한 상태가 생기므로 판별값 하나로 든다. URL 동기화는 하지 않는다.
export type ChatSidePanel = "more" | "memory";
export const chatSidePanelAtom = atom<ChatSidePanel | undefined>(undefined);

// 데스크톱 더보기 사이드바(인라인 <aside>)의 id. 헤더 ⋮ 버튼이 열려 있는 동안 `aria-controls` 로 가리킨다 —
// 사이드바 항목을 누르면 패널이 닫히며 모달이 열리므로, 모달이 닫힐 때 돌아갈 곳이 이 짝으로만 남는다.
export const CHAT_MORE_SIDEBAR_ID = "chat-more-sidebar";

// 기억 노트 패널에서 고른 탭. 패널 본문은 창 폭이 lg 경계를 넘으면 인라인 패널과 대화 상자 사이를 옮겨 새로 마운트되므로,
// 컴포넌트 상태로 두면 폭만 바꿔도 첫 탭으로 돌아간다. 다른 방에서는 첫 탭부터 보이도록 방 id 와 함께 든다.
export type ChatMemoryTab = "notes" | "scenes" | "facts";
export const chatMemoryTabAtom = atom<{ roomId: string; tab: ChatMemoryTab } | undefined>(undefined);
