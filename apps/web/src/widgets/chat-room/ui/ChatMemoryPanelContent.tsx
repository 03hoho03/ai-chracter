import { useRef, useState, type ReactNode, type RefObject } from "react";
import { DialogBody } from "@ai-character-chat/ui/components/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";

import { useChatRoomMemoryItemsQuery, useChatRoomMemoryQuery } from "@/entities/chat-room";
import { RoomMemoryEditor } from "@/features/edit-room-memory";
import { itemCountLabel, RoomMemoryFacts, RoomMemoryScenes } from "@/features/forget-room-memory";

import { MEMORY_PANEL_DESCRIPTION } from "../config/memoryPanel";
import { confirmClearMemoryNote } from "../lib/confirmClearMemoryNote";

type ChatMemoryPanelLayout = "sidebar" | "dialog";

type ChatMemoryPanelContentProps = {
  roomId: string;
  /** `sidebar`는 lg 이상 인라인 패널의 머리 아래, `dialog`는 lg 미만 Dialog 의 `DialogHeader` 아래에 들어간다. */
  layout: ChatMemoryPanelLayout;
};

/** 기억 노트 패널의 본문. 서버가 장면·사실 목록을 열어 두었을 때만(`features.itemsVisible`) 노트·요약 / 장면 / 사실 탭으로
 * 나눈다. 닫혀 있으면 탭 없이 예전 그대로 노트·요약 편집기 하나다 — 목록 API 도 부르지 않는다. 기억을 받는 동안에도 탭
 * 없는 모양이다(편집기가 스스로 불러오는 중을 그린다). 패널이 열려 있을 때만 마운트되므로 닫힌 채로는 기억을 받지 않는다. */
export function ChatMemoryPanelContent({ roomId, layout }: ChatMemoryPanelContentProps) {
  const memoryQuery = useChatRoomMemoryQuery(roomId);

  if (memoryQuery.data?.features.itemsVisible) {
    // 방마다 탭과 편집 요청을 새로 시작한다(편집기 폼이 방마다 새로 만들어지는 것과 같은 이유).
    return <ChatMemoryTabs key={roomId} roomId={roomId} layout={layout} />;
  }

  const editor = <RoomMemoryEditor roomId={roomId} onClearNoteRequest={confirmClearMemoryNote} />;
  if (layout === "dialog") return <DialogBody>{editor}</DialogBody>;
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
      <p className="mb-5 text-xs break-keep text-muted-foreground">{MEMORY_PANEL_DESCRIPTION}</p>
      {editor}
    </div>
  );
}

type MemoryTab = "notes" | "scenes" | "facts";

function isMemoryTab(value: string): value is MemoryTab {
  return value === "notes" || value === "scenes" || value === "facts";
}

// 탭 패널은 Radix 가 Tab 정지로 둔다 — 포커스가 보이게 띄운 아웃라인을 준다(패널 바깥 링은 스크롤 영역에 잘린다).
const TAB_PANEL_CLASS = "rounded-sm focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring";

/** 탭 줄은 스크롤 영역 밖의 흐름 줄이다 — 목록을 내려 읽는 동안에도 탭이 보이고, sticky 를 쓰지 않는다. 탭 줄 아래 선은
 * 스크롤 영역의 위 모서리다(Dialog 는 `DialogBody`의 `border-t`). */
function ChatMemoryTabs({ roomId, layout }: { roomId: string; layout: ChatMemoryPanelLayout }) {
  const itemsQuery = useChatRoomMemoryItemsQuery(roomId, true);
  const [tab, setTab] = useState<MemoryTab>("notes");
  const [editSummaryRequest, setEditSummaryRequest] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  function handleTabChange(value: string) {
    if (!isMemoryTab(value)) return;
    setTab(value);
    // 스크롤 영역 하나를 세 탭이 함께 쓴다 — 긴 장면 목록을 내린 자리에서 다른 탭의 중간이 보이지 않게 맨 위로 올린다.
    scrollRef.current?.scrollTo({ top: 0 });
  }

  function handleEditSummaryRequest() {
    handleTabChange("notes");
    setEditSummaryRequest((count) => count + 1);
  }

  const items = itemsQuery.data;
  const tabList = (
    <TabsList variant="line" aria-label="기억 종류">
      <TabsTrigger value="notes">노트·요약</TabsTrigger>
      <TabsTrigger value="scenes">
        장면
        {items && <TabCount>{itemCountLabel(items.episodes.length, items.hasMoreEpisodes)}</TabCount>}
      </TabsTrigger>
      <TabsTrigger value="facts">
        사실
        {items && <TabCount>{itemCountLabel(items.facts.length, false)}</TabCount>}
      </TabsTrigger>
    </TabsList>
  );

  const panels = (
    <>
      {/* 노트·요약 탭은 다른 탭에 가 있는 동안에도 마운트해 둔다 — 저장하지 않은 노트·요약 입력이 탭을 오가며 사라지지 않게. */}
      <TabsContent value="notes" forceMount hidden={tab !== "notes"} className={TAB_PANEL_CLASS}>
        <RoomMemoryEditor
          roomId={roomId}
          onClearNoteRequest={confirmClearMemoryNote}
          editSummaryRequest={editSummaryRequest}
        />
      </TabsContent>
      <TabsContent value="scenes" className={TAB_PANEL_CLASS}>
        <RoomMemoryScenes roomId={roomId} onEditSummaryRequest={handleEditSummaryRequest} />
      </TabsContent>
      <TabsContent value="facts" className={TAB_PANEL_CLASS}>
        <RoomMemoryFacts roomId={roomId} onEditSummaryRequest={handleEditSummaryRequest} />
      </TabsContent>
    </>
  );

  if (layout === "dialog") {
    // 헤더와 본문 사이에 끼는 래퍼라 패딩 없는 flex 컬럼이다 — 본문만 스크롤하고 대화 상자의 최대 높이를 넘지 않게.
    return (
      <Tabs value={tab} onValueChange={handleTabChange} className="flex min-h-0 flex-1 flex-col gap-1">
        {tabList}
        <ScrollBody ref={scrollRef} layout={layout}>
          {panels}
        </ScrollBody>
      </Tabs>
    );
  }
  return (
    <Tabs value={tab} onValueChange={handleTabChange} className="min-h-0 flex-1 gap-1">
      <div className="flex shrink-0 flex-col gap-2 px-4">
        <p className="text-xs break-keep text-muted-foreground">{MEMORY_PANEL_DESCRIPTION}</p>
        {tabList}
      </div>
      <ScrollBody ref={scrollRef} layout={layout}>
        {panels}
      </ScrollBody>
    </Tabs>
  );
}

function ScrollBody({
  ref,
  layout,
  children,
}: {
  ref: RefObject<HTMLDivElement | null>;
  layout: ChatMemoryPanelLayout;
  children: ReactNode;
}) {
  if (layout === "dialog") return <DialogBody ref={ref}>{children}</DialogBody>;
  return (
    <div ref={ref} className="min-h-0 flex-1 overflow-y-auto border-t border-border px-4 pt-4 pb-4">
      {children}
    </div>
  );
}

function TabCount({ children }: { children: string }) {
  return <span className="text-xs text-muted-foreground tabular-nums">{children}</span>;
}
