import { useAtom } from "jotai";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@ai-character-chat/ui/components/sheet";
import { BookOpen, History, Images, MoreVertical, Repeat, Sparkles } from "lucide-react";

import { ChangeStartingSetupModal } from "../../../features/change-starting-setup";
import { EndingCollectionModal } from "../../../features/ending-collection";
import { ImageArchiveModal } from "../../../features/image-archive";
import { PlayGuideModal } from "../../../features/play-guide";
import { UpdateInfoModal } from "../../../features/update-info";
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

// techspec-chat-story.md §6, techspec-chat-character.md — 패널 자체는 react-call을 쓰지 않는다
// (열림/닫힘만 있는 목록일 뿐 "호출→결과 반환"이 필요 없다). 항목 클릭 시 Sheet를 닫고 해당 기능
// 전용 react-call 모달을 연다 — 지금은 플레이가이드만 활성, 나머지는 이후 스토리에서 활성화한다.
export function ChatMorePanel({
  roomId,
  contentType,
  startingSetupId,
  characterId,
}: {
  roomId: string;
  contentType: "character" | "story";
  startingSetupId?: string;
  characterId?: string;
}) {
  const [open, setOpen] = useAtom(chatMorePanelOpenAtom);
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
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="더보기">
          <MoreVertical aria-hidden className="size-4" />
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>더보기</SheetTitle>
        </SheetHeader>
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
      </SheetContent>
    </Sheet>
  );
}
