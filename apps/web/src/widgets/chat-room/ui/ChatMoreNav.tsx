import { useNavigate } from "@tanstack/react-router";
import { useSetAtom } from "jotai";
import { BookOpen, BookText, History, IdCard, Images, Repeat, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { isLegalReconsentRequiredError } from "@/entities/legal";
import { isNovelizeNotAllowedError, useEnsureRoomNovelMutation } from "@/entities/novel";
import { useSessionQuery } from "@/entities/session";
import { ChangeStartingSetupModal } from "@/features/change-starting-setup";
import { EndingCollectionModal } from "@/features/ending-collection";
import { ImageArchiveModal, StoryImageArchiveModal } from "@/features/image-archive";
import { PlayGuideModal } from "@/features/play-guide";
import { UpdateInfoModal } from "@/features/update-info";
import type { AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { chatSidePanelAtom } from "../model/atoms";
import { visibleMoreItems, type FeatureGatedItem } from "../model/visibleMoreItems";
import { RoomPersonaModal } from "./RoomPersonaModal";

type MorePanelItem = FeatureGatedItem & {
  key: string;
  label: string;
  icon: typeof BookOpen;
  isActive: boolean;
};

// 아이콘은 프로필 메뉴의 `내 소설`과 같은 글리프다 — 같은 대상에 다른 그림을 붙이면 둘이 다른 기능으로 읽힌다.
// 플레이가이드의 `BookOpen`과는 일부러 다른 그림을 고른다(한 목록 안에서 펼친 책 둘이 나란히 놓인다).
const NOVEL_ITEM: MorePanelItem = {
  key: "novel",
  label: "소설로 보기",
  icon: BookText,
  isActive: true,
  requiredFeature: "novelize",
};

const CHARACTER_ITEMS: MorePanelItem[] = [
  { key: "play-guide", label: "플레이가이드", icon: BookOpen, isActive: true },
  { key: "update-info", label: "업데이트 정보", icon: History, isActive: true },
  { key: "image-archive", label: "이미지 보관함", icon: Images, isActive: true },
  NOVEL_ITEM,
  { key: "persona", label: "대화 프로필", icon: IdCard, isActive: true },
];

const STORY_ITEMS: MorePanelItem[] = [
  { key: "play-guide", label: "플레이가이드", icon: BookOpen, isActive: true },
  { key: "update-info", label: "업데이트 정보", icon: History, isActive: true },
  { key: "change-starting-setup", label: "시작설정 변경", icon: Repeat, isActive: true },
  { key: "ending-collection", label: "엔딩 컬렉션", icon: Sparkles, isActive: true },
  { key: "image-archive", label: "이미지 보관함", icon: Images, isActive: true },
  NOVEL_ITEM,
  { key: "persona", label: "대화 프로필", icon: IdCard, isActive: true },
];

export type ChatMoreNavProps = {
  roomId: string;
  contentType: "character" | "story";
  startingSetupId?: string;
  characterId?: string;
  /** 스토리 방일 때만 있다(캐릭터 방은 undefined) — 보관함이 작품마다 갈린다. */
  storyId?: string;
  /** 이 방의 `{{user}}`·`{{char}}` 이름. 여기서 여는 모달은 방 밖(루트)에 마운트돼 방을 모르므로 이름을 넘겨받는다. */
  macroNames: AuthorMacroNames;
};

// 항목 목록 자체는 react-call을 쓰지 않는다
// (열림/닫힘만 있는 목록일 뿐 "호출→결과 반환"이 필요 없다). 항목을 누르면 패널을 닫고 해당 기능
// 전용 react-call 모달을 연다 — 데스크톱 인라인 사이드바(ChatMoreSidebar)와 모바일 Sheet
// (ChatMorePanel)가 이 목록과 핸들러를 공유하므로 두 곳에서 그려져도 정의는 여기 한 곳뿐이다.
// `소설로 보기`만 모달이 아니라 다른 화면으로 간다 — 그 방의 소설을 얻거나 만든 뒤 소설 주소로 옮긴다.
export function ChatMoreNav({ roomId, contentType, startingSetupId, characterId, storyId, macroNames }: ChatMoreNavProps) {
  const setPanel = useSetAtom(chatSidePanelAtom);
  const navigate = useNavigate();
  const { data: me } = useSessionQuery();
  const ensureRoomNovel = useEnsureRoomNovelMutation();
  const items = visibleMoreItems(contentType === "story" ? STORY_ITEMS : CHARACTER_ITEMS, me?.enabledFeatures ?? []);

  // 패널은 누르는 즉시 닫히므로(다른 항목과 같은 순서) 이 버튼은 결과를 기다리는 동안 화면에 없다 — 진행 표시를
  // 두지 않고 실패만 토스트로 알린다. `mutateAsync`를 쓰는 이유는 패널이 닫히며 이 컴포넌트가 언마운트돼도
  // 이동이 이어져야 해서다(`mutate`의 호출 단위 콜백은 언마운트와 함께 사라진다).
  async function openRoomNovel() {
    if (ensureRoomNovel.isPending) return;
    try {
      const novel = await ensureRoomNovel.mutateAsync(roomId);
      void navigate({ to: "/novels/$novelId", params: { novelId: novel.id } });
    } catch (error) {
      // 재동의가 필요하면 전역 처리가 재동의 모달을 띄운다 — 토스트를 겹치지 않는다.
      if (isLegalReconsentRequiredError(error)) return;
      // 허용을 회수한 직후라면 전역 처리가 세션을 다시 읽어 이 항목도 사라진다.
      toast.error(
        isNovelizeNotAllowedError(error)
          ? "아직 열리지 않은 기능이에요."
          : "소설을 열지 못했어요. 잠시 후 다시 시도해주세요.",
      );
    }
  }

  function handleItemClick(item: MorePanelItem) {
    if (!item.isActive) return;
    setPanel(undefined);
    if (item.key === "novel") void openRoomNovel();
    if (item.key === "play-guide") void PlayGuideModal.call({ roomId, macroNames });
    if (item.key === "update-info") void UpdateInfoModal.call({ roomId });
    if (item.key === "change-starting-setup") void ChangeStartingSetupModal.call({ roomId, macroNames });
    if (item.key === "ending-collection" && startingSetupId) {
      void EndingCollectionModal.call({ startingSetupId, macroNames });
    }
    // 선택 UI를 모달로 둔 근거는 RoomPersonaModal 주석.
    if (item.key === "persona") void RoomPersonaModal.call({ roomId });
    if (item.key === "image-archive" && characterId) {
      void ImageArchiveModal.call({ characterId });
    }
    if (item.key === "image-archive" && storyId) {
      void StoryImageArchiveModal.call({ storyId, macroNames });
    }
  }

  return (
    <nav className="flex flex-col gap-1 px-2">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          disabled={!item.isActive}
          onClick={() => handleItemClick(item)}
          className="flex items-center gap-2.5 rounded-md px-2.5 py-2.5 text-left text-sm text-foreground motion-safe:transition-colors enabled:hover:bg-secondary/50 disabled:cursor-not-allowed disabled:text-muted-foreground/60"
        >
          <item.icon aria-hidden className="size-4 shrink-0" />
          <span className="flex-1">{item.label}</span>
          {!item.isActive && <span className="text-xs text-muted-foreground/60">준비 중</span>}
        </button>
      ))}
    </nav>
  );
}
