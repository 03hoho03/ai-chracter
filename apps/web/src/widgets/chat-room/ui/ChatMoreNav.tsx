import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouter } from "@tanstack/react-router";
import { useSetAtom } from "jotai";
import { BookOpen, BookText, Cpu, History, IdCard, Images, Repeat, Sparkles } from "lucide-react";
import { useId } from "react";
import { toast } from "sonner";

import { chatRoomKeys } from "@/entities/chat-room";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import {
  isContentNovelizeForbiddenError,
  isNovelizeNotAllowedError,
  useEnsureRoomNovelMutation,
} from "@/entities/novel";
import { useSessionQuery } from "@/entities/session";
import { ChangeStartingSetupModal } from "@/features/change-starting-setup";
import { EndingCollectionModal } from "@/features/ending-collection";
import { ImageArchiveModal, StoryImageArchiveModal } from "@/features/image-archive";
import { PlayGuideModal } from "@/features/play-guide";
import { UpdateInfoModal } from "@/features/update-info";
import type { AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { chatSidePanelAtom } from "../model/atoms";
import { isStillInRoom } from "../model/roomNovelNavigation";
import { CHAT_MODEL_FEATURE_GATE, visibleMoreItems, type FeatureGatedItem } from "../model/visibleMoreItems";
import { RoomChatModelModal } from "./RoomChatModelModal";
import { RoomPersonaModal } from "./RoomPersonaModal";

type MorePanelItem = FeatureGatedItem & {
  key: string;
  label: string;
  icon: typeof BookOpen;
  isActive: boolean;
};

// 아이콘은 좌측 패널(좁은 화면은 드로어)의 `내 소설`과 같은 글리프다 — 같은 대상에 다른 그림을 붙이면 둘이 다른 기능으로 읽힌다.
// 플레이가이드의 `BookOpen`과는 일부러 다른 그림을 고른다(한 목록 안에서 펼친 책 둘이 나란히 놓인다).
const NOVEL_ITEM: MorePanelItem = {
  key: "novel",
  label: "소설로 보기",
  icon: BookText,
  isActive: true,
  requiredFeature: "novelize",
};

// 상위 모델 허용이 있는 계정에만 보인다. 허용이 없으면 고를 것이 기본 모델 하나뿐이라 항목 자체를 두지 않는다.
const CHAT_MODEL_ITEM: MorePanelItem = {
  key: "chat-model",
  label: "AI 모델",
  icon: Cpu,
  isActive: true,
  ...CHAT_MODEL_FEATURE_GATE,
};

const CHARACTER_ITEMS: MorePanelItem[] = [
  { key: "play-guide", label: "플레이가이드", icon: BookOpen, isActive: true },
  { key: "update-info", label: "업데이트 정보", icon: History, isActive: true },
  { key: "image-archive", label: "이미지 보관함", icon: Images, isActive: true },
  NOVEL_ITEM,
  { key: "persona", label: "대화 프로필", icon: IdCard, isActive: true },
  CHAT_MODEL_ITEM,
];

const STORY_ITEMS: MorePanelItem[] = [
  { key: "play-guide", label: "플레이가이드", icon: BookOpen, isActive: true },
  { key: "update-info", label: "업데이트 정보", icon: History, isActive: true },
  { key: "change-starting-setup", label: "시작설정 변경", icon: Repeat, isActive: true },
  { key: "ending-collection", label: "엔딩 컬렉션", icon: Sparkles, isActive: true },
  { key: "image-archive", label: "이미지 보관함", icon: Images, isActive: true },
  NOVEL_ITEM,
  { key: "persona", label: "대화 프로필", icon: IdCard, isActive: true },
  CHAT_MODEL_ITEM,
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
  /** 원작자가 소설 만들기를 허용하지 않아 이 방에서 새 소설을 만들 수 없는지(방 응답이 계산해 준다). */
  novelCreationBlocked: boolean;
};

/** 막힌 「소설로 보기」 아래에 적는 이유. 방을 연 뒤 원작자가 허락을 바꿔 생성 요청이 거절됐을 때의 토스트도 같은 문장이다 —
 * 기다려도 풀리지 않는 거절이라 "다시 시도"를 말하지 않는다. "작가"가 아니라 "원작자"인 이유: 이 화면의 이용자는 자기 대화로
 * 만들 소설의 작가이기도 해서, "작가"라고 쓰면 누구의 허락인지 흐려진다. */
const NOVEL_CREATION_BLOCKED_REASON = "원작자가 소설 만들기를 허용하지 않은 작품이에요.";

// 항목 목록 자체는 react-call을 쓰지 않는다
// (열림/닫힘만 있는 목록일 뿐 "호출→결과 반환"이 필요 없다). 항목을 누르면 패널을 닫고 해당 기능
// 전용 react-call 모달을 연다 — 데스크톱 인라인 사이드바(ChatMoreSidebar)와 모바일 Sheet
// (ChatMorePanel)가 이 목록과 핸들러를 공유하므로 두 곳에서 그려져도 정의는 여기 한 곳뿐이다.
// `소설로 보기`만 모달이 아니라 다른 화면으로 간다 — 그 방의 소설을 얻거나 만든 뒤 소설 주소로 옮긴다.
export function ChatMoreNav({
  roomId,
  contentType,
  startingSetupId,
  characterId,
  storyId,
  macroNames,
  novelCreationBlocked,
}: ChatMoreNavProps) {
  const setPanel = useSetAtom(chatSidePanelAtom);
  const queryClient = useQueryClient();
  const blockedLabelId = useId();
  const blockedReasonId = useId();
  const navigate = useNavigate();
  const router = useRouter();
  const { data: me } = useSessionQuery();
  const ensureRoomNovel = useEnsureRoomNovelMutation();
  const items = visibleMoreItems(contentType === "story" ? STORY_ITEMS : CHARACTER_ITEMS, me?.enabledFeatures ?? []);

  // 패널은 누르는 즉시 닫히므로(다른 항목과 같은 순서) 이 버튼은 결과를 기다리는 동안 화면에 없다 — 진행 표시를
  // 두지 않고 실패만 토스트로 알린다. `mutateAsync`를 쓰는 이유는 패널이 닫히며 이 컴포넌트가 언마운트돼도
  // 이동이 이어져야 해서다(`mutate`의 호출 단위 콜백은 언마운트와 함께 사라진다).
  // 중복 클릭은 막지 않는다 — 패널을 다시 열면 새 인스턴스라 `isPending` 가드가 늘 거짓이고, 서버가 같은 방의
  // 요청을 같은 소설로 돌려주므로(방마다 소설 하나) 두 번 눌러도 같은 주소로 두 번 옮길 뿐이다.
  // 이동 직전 경로는 응답이 온 시점의 것을 라우터에서 읽는다(이 컴포넌트는 이미 언마운트됐을 수 있다).
  async function openRoomNovel() {
    try {
      const novel = await ensureRoomNovel.mutateAsync(roomId);
      if (!isStillInRoom(router.state.location.pathname, roomId)) return;
      void navigate({ to: "/novels/$novelId", params: { novelId: novel.id } });
    } catch (error) {
      // 재동의가 필요하면 전역 처리가 재동의 모달을 띄운다 — 토스트를 겹치지 않는다.
      if (isLegalReconsentRequiredError(error)) return;
      // 방을 연 뒤 원작자가 허락을 거둔 경우다. 방을 다시 읽어 이 항목도 막힌 상태로 그린다.
      if (isContentNovelizeForbiddenError(error)) {
        void queryClient.invalidateQueries({ queryKey: chatRoomKeys.detail(roomId) });
        toast.error(NOVEL_CREATION_BLOCKED_REASON);
        return;
      }
      // 허용을 회수한 직후라면 전역 처리가 세션을 다시 읽어 이 항목도 사라진다.
      toast.error(
        isNovelizeNotAllowedError(error)
          ? "아직 열리지 않은 기능이에요."
          : "소설을 열지 못했어요. 잠시 후 다시 시도해주세요.",
      );
    }
  }

  function isBlocked(item: MorePanelItem) {
    return item.key === "novel" && novelCreationBlocked;
  }

  function handleItemClick(item: MorePanelItem) {
    // 막힌 항목은 눌러도 패널을 닫지 않는다 — 이유 문장이 그 자리에 남아야 한다.
    if (!item.isActive || isBlocked(item)) return;
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
    if (item.key === "chat-model") void RoomChatModelModal.call({ roomId });
    if (item.key === "image-archive" && characterId) {
      void ImageArchiveModal.call({ characterId });
    }
    if (item.key === "image-archive" && storyId) {
      void StoryImageArchiveModal.call({ storyId, macroNames });
    }
  }

  return (
    <nav className="flex flex-col gap-1 px-2">
      {items.map((item) => {
        // 막힌 「소설로 보기」는 숨기지 않고 이유와 함께 남긴다. `disabled` 가 아니라 `aria-disabled` 인 이유는 포커스 순회에
        // 남아 이름과 이유가 함께 읽히게 하려는 것이다(`disabled` 버튼은 Tab 이 건너뛴다). 이름은 항목 글자만 가리키고 이유는
        // 설명으로 따로 단다 — 버튼 안 글자 전부가 이름이 되면 이유가 이름과 설명으로 두 번 읽힌다.
        const isItemBlocked = isBlocked(item);
        return (
          <button
            key={item.key}
            type="button"
            disabled={!item.isActive}
            aria-disabled={isItemBlocked || undefined}
            aria-labelledby={isItemBlocked ? blockedLabelId : undefined}
            aria-describedby={isItemBlocked ? blockedReasonId : undefined}
            onClick={() => handleItemClick(item)}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2.5 text-left text-sm text-foreground motion-safe:transition-colors disabled:cursor-not-allowed disabled:text-muted-foreground/60",
              isItemBlocked ? "cursor-not-allowed items-start text-muted-foreground" : "enabled:hover:bg-secondary/50",
            )}
          >
            <item.icon aria-hidden className={cn("size-4 shrink-0", isItemBlocked && "mt-1")} />
            {isItemBlocked ? (
              <span className="flex flex-1 flex-col gap-0.5">
                <span id={blockedLabelId}>{item.label}</span>
                <span id={blockedReasonId} className="text-xs break-keep">
                  {NOVEL_CREATION_BLOCKED_REASON}
                </span>
              </span>
            ) : (
              <span className="flex-1">{item.label}</span>
            )}
            {!item.isActive && <span className="text-xs text-muted-foreground/60">준비 중</span>}
          </button>
        );
      })}
    </nav>
  );
}
