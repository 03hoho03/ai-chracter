import { atom } from "jotai";

// image-refact-goal-prompt.md IR-5/IR-6 — 보관함·옵션 시트는 열림 여부만 관리한다(URL 동기화
// 불필요 — widgets/chat-room의 chatMorePanelOpenAtom 선례와 동일). 트리거(탭 스트립)와 콘텐츠
// (각 Rail)가 같은 위젯 소유라 prop 드릴다운 없이 이 atom을 공유한다.
export const imageStudioLibrarySheetOpenAtom = atom(false);
export const imageStudioOptionsSheetOpenAtom = atom(false);
