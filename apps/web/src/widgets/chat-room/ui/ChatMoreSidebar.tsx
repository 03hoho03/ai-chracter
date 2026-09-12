import { useEffect } from "react";
import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import { X } from "lucide-react";

import { useIsChatMoreSidebarLayout } from "../lib/useIsChatMoreSidebarLayout";
import { chatMorePanelOpenAtom } from "../model/atoms";
import type { ChatMoreNavProps } from "./ChatMoreNav";
import { ChatMoreNav } from "./ChatMoreNav";

type ChatMoreSidebarProps = ChatMoreNavProps;

// US-004 — lg 이상의 더보기 패널. 오버레이 시트가 아니라 채팅과 폭을 나눠 갖는 인라인 <aside>다:
// 열어둔 채로 메시지를 읽고 입력·전송할 수 있어야 하므로 포털+모달 전제인 shadcn Sheet를 쓸 수 없다.
// 깊이는 그림자가 아니라 명도로 만든다(DESIGN.md Flat-at-Rest) — bg-card가 background 위 반 칸이고
// 경계는 border-l 한 줄이다. 닫기는 헤더 ⋮ 재클릭 / 이 안의 닫기 버튼 / ESC 셋 다 동작한다.
//
// slide-in을 뺀 이유 — 이 <aside>는 오버레이가 아니라 부모 flex 행의 in-flow 아이템이다. 아래 실측
// 당시엔 그 행에 컬럼 제한이 없어 뷰포트 폭 전체를 썼다(지금은 행 자체에 max-w-5xl이 붙어 있다 —
// ChatRoomView 참고). 그래서 motion-safe:slide-in-from-right-10(translateX(2.5rem) 진입)이
// 문서를 넘치게 했다 — 포털되는 Sheet였다면 없었을 문제다. 1440×900 실측: 더보기 클릭 후
// documentElement.scrollWidth - clientWidth가 8프레임 동안 양수, 관측 최대 14px, 약 70ms에 0으로
// 수렴했다. 조상(ChatRoomView의 flex 행)에 overflow-x-hidden을 걸어 넘침만 가리는 대안도 시도했지만
// 같은 행에 사는 ShortcutAutocomplete(absolute bottom-full max-h-60)가 잘려버렸다 — 844×390 가로
// 폰 + 팝업이 240px까지 찬 상태로 A/B 실측하면 overflow-x-hidden이 있을 때 팝업 상단 지점(y=77)의
// document.elementFromPoint가 팝업 항목이 아니라 채팅 헤더의 캐릭터 이름 span이었다(그 행에
// 스크롤이 생기지 않아 도달 불가). 그래서 넘침을 가리는 대신 원인(슬라이드)을 뺐다. 남은 건
// 페이드뿐이지만 duration-200과 fade-in-0이 그대로라 등장이 급작스럽지 않고, DESIGN.md도 슬라이드를
// 요구하지 않는다. 슬라이드를 되살리려면 이 <aside>만 감싸는 래퍼에 클리핑을 걸어야 한다(행
// 전체가 아니라) — DOM 노드를 하나 더 만드는 구조 변경이라 이번에는 하지 않았다.
export function ChatMoreSidebar(props: ChatMoreSidebarProps) {
  const [isOpen, setIsOpen] = useAtom(chatMorePanelOpenAtom);
  const isSidebarLayout = useIsChatMoreSidebarLayout();
  const isVisible = isSidebarLayout && isOpen;

  // Sheet와 달리 Radix의 ESC 처리가 없으므로 직접 듣는다. 항목을 누르면 패널이 먼저 닫히고 모달이
  // 열리므로(ChatMoreNav) 모달과 ESC를 다툴 일은 없다.
  useEffect(() => {
    if (!isVisible) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isVisible, setIsOpen]);

  if (!isVisible) return null;

  return (
    <aside
      aria-label="더보기"
      className="flex w-72 shrink-0 flex-col border-l border-border bg-card motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-3">
        <h2 className="font-heading text-lg font-medium text-foreground">더보기</h2>
        <Button variant="ghost" size="icon-sm" aria-label="더보기 닫기" onClick={() => setIsOpen(false)}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-3">
        <ChatMoreNav {...props} />
      </div>
    </aside>
  );
}
