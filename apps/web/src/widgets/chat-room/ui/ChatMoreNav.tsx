import { useSetAtom } from "jotai";
import { BookOpen, History, Images, Repeat, Sparkles } from "lucide-react";

import { ChangeStartingSetupModal } from "@/features/change-starting-setup";
import { EndingCollectionModal } from "@/features/ending-collection";
import { ImageArchiveModal } from "@/features/image-archive";
import { PlayGuideModal } from "@/features/play-guide";
import { UpdateInfoModal } from "@/features/update-info";
import { chatMorePanelOpenAtom } from "../model/atom";

type MorePanelItem = {
  key: string;
  label: string;
  icon: typeof BookOpen;
  active: boolean;
};

const CHARACTER_ITEMS: MorePanelItem[] = [
  { key: "play-guide", label: "플레이가이드", icon: BookOpen, active: true },
  { key: "update-info", label: "업데이트 정보", icon: History, active: true },
  { key: "image-archive", label: "이미지 보관함", icon: Images, active: true },
];

const STORY_ITEMS: MorePanelItem[] = [
  { key: "play-guide", label: "플레이가이드", icon: BookOpen, active: true },
  { key: "update-info", label: "업데이트 정보", icon: History, active: true },
  { key: "change-starting-setup", label: "시작설정 변경", icon: Repeat, active: true },
  { key: "ending-collection", label: "엔딩 컬렉션", icon: Sparkles, active: true },
];

export type ChatMoreNavProps = {
  roomId: string;
  contentType: "character" | "story";
  startingSetupId?: string;
  characterId?: string;
};

// techspec-chat-story.md §6, techspec-chat-character.md — 항목 목록 자체는 react-call을 쓰지 않는다
// (열림/닫힘만 있는 목록일 뿐 "호출→결과 반환"이 필요 없다). 항목을 누르면 패널을 닫고 해당 기능
// 전용 react-call 모달을 연다 — 데스크톱 인라인 사이드바(ChatMoreSidebar)와 모바일 Sheet
// (ChatMorePanel)가 이 목록과 핸들러를 공유하므로 US-004 이후에도 정의는 여기 한 곳뿐이다.
export function ChatMoreNav({ roomId, contentType, startingSetupId, characterId }: ChatMoreNavProps) {
  const setOpen = useSetAtom(chatMorePanelOpenAtom);
  const items = contentType === "story" ? STORY_ITEMS : CHARACTER_ITEMS;

  function handleItemClick(item: MorePanelItem) {
    if (!item.active) return;
    setOpen(false);
    if (item.key === "play-guide") void PlayGuideModal.call({ roomId });
    if (item.key === "update-info") void UpdateInfoModal.call({ roomId });
    if (item.key === "change-starting-setup") void ChangeStartingSetupModal.call({ roomId });
    if (item.key === "ending-collection" && startingSetupId) {
      void EndingCollectionModal.call({ startingSetupId });
    }
    if (item.key === "image-archive" && characterId) {
      void ImageArchiveModal.call({ characterId });
    }
  }

  return (
    <nav className="flex flex-col gap-1 px-2">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          disabled={!item.active}
          onClick={() => handleItemClick(item)}
          className="flex items-center gap-2.5 rounded-md px-2.5 py-2.5 text-left text-sm text-foreground transition-colors enabled:hover:bg-secondary/50 disabled:cursor-not-allowed disabled:text-muted-foreground/60"
        >
          <item.icon aria-hidden className="size-4 shrink-0" />
          <span className="flex-1">{item.label}</span>
          {!item.active && <span className="text-xs text-muted-foreground/60">준비 중</span>}
        </button>
      ))}
    </nav>
  );
}
