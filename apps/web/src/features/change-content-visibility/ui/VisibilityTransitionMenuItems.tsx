import { DropdownMenuItem } from "@ai-character-chat/ui/components/dropdown-menu";
import { EyeOff, Globe, Link2, type LucideIcon } from "lucide-react";

import type { ContentVisibility } from "@/entities/content";

import { listVisibilityTransitions, VISIBILITY_TRANSITION_COPY } from "../model/visibilityTransition";
import { ChangeContentVisibilityModal } from "./ChangeContentVisibilityModal";

type VisibilityTransitionMenuItemsProps = {
  contentId: string;
  creatorUserId: string;
  currentVisibility: ContentVisibility;
};

const VISIBILITY_ICON: Record<ContentVisibility, LucideIcon> = {
  public: Globe,
  link: Link2,
  private: EyeOff,
};

/** US-005 — 공개범위 전환 항목 2개(현재 값은 뺀다). 진입점이 둘(콘텐츠 상세 "⋯" 메뉴 / 프로필 카드
 * "⋯" 메뉴)이라 항목 자체를 여기서 한 번만 그린다 — 라벨·아이콘·순서가 두 화면에서 갈라지지 않게.
 * 호출부는 `DropdownMenu`/`DropdownMenuContent`와 (필요하면) 구분선만 소유한다. */
export function VisibilityTransitionMenuItems({
  contentId,
  creatorUserId,
  currentVisibility,
}: VisibilityTransitionMenuItemsProps) {
  return listVisibilityTransitions(currentVisibility).map((target) => {
    const Icon = VISIBILITY_ICON[target];
    return (
      <DropdownMenuItem
        key={target}
        onSelect={() =>
          void ChangeContentVisibilityModal.call({ contentId, creatorUserId, targetVisibility: target })
        }
      >
        <Icon aria-hidden />
        {VISIBILITY_TRANSITION_COPY[target].label}로 전환
      </DropdownMenuItem>
    );
  });
}
