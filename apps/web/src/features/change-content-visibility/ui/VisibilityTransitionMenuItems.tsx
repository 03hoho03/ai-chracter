import {
  DropdownMenuItem,
  DropdownMenuLabel,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { EyeOff, Globe, Link2, type LucideIcon } from "lucide-react";
import { useId } from "react";

import { resolveAccessStatus, type ContentVisibility, type ModerationStatus } from "@/entities/content";

import {
  listVisibilityTransitions,
  VISIBILITY_TRANSITION_BLOCKED_REASON,
  VISIBILITY_TRANSITION_COPY,
} from "../model/visibilityTransition";
import { ChangeContentVisibilityModal } from "./ChangeContentVisibilityModal";

type VisibilityTransitionMenuItemsProps = {
  contentId: string;
  creatorUserId: string;
  currentVisibility: ContentVisibility;
  /** 이용제한 작품에서는 전환 항목이 비활성이 된다(US-008). **required로 둔 것은 의도다** — 이 스토리의
   * 원래 결함이 정확히 "목록 화면이 `moderationStatus`를 안 읽는 것"이었고, 새 진입점이 생길 때 컴파일러가
   * 그 질문을 다시 하게 만드는 게 유일하게 반복되지 않는 방어선이다. */
  moderationStatus: ModerationStatus;
};

const VISIBILITY_ICON: Record<ContentVisibility, LucideIcon> = {
  public: Globe,
  link: Link2,
  private: EyeOff,
};

/** US-005 — 공개범위 전환 항목 2개(현재 값은 뺀다). 진입점이 셋(콘텐츠 상세 "⋯" 메뉴 / 프로필 카드
 * "⋯" 메뉴 / `/my` 카드 "⋯" 메뉴)이라 항목 자체를 여기서 한 번만 그린다 — 라벨·아이콘·순서가 화면마다
 * 갈라지지 않게. 호출부는 `DropdownMenu`/`DropdownMenuContent`와 (필요하면) 구분선만 소유한다.
 *
 * **비활성은 `disabled`가 아니라 `aria-disabled`다.** Radix는 `disabled` 항목을 `RovingFocusGroup.Item`의
 * `focusable: !disabled`로 포커스 대상에서 빼고 타입어헤드에서도 거른다 — 그러면 **왜 못 누르는지가
 * 키보드·스크린리더에 영원히 닿지 않는다**(사유를 항목 이름에 넣든 옆에 두든 마찬가지다). `aria-disabled`면
 * 항목이 순회에 남아 이름과 `aria-describedby` 사유가 함께 읽히고, `onSelect`를 `preventDefault`로 막아
 * 눌러도 아무 일이 없고 메뉴도 닫히지 않는다 — 사유가 그 자리에 그대로 남는다.
 *
 * `deleted`는 여기 오지 않는다(목록 엔드포인트가 소유자에게도 거르고, 상세는 `canViewDetailPage`가
 * 막는다) — 그래서 사유 문구를 이용제한 하나로 둔다. */
export function VisibilityTransitionMenuItems({
  contentId,
  creatorUserId,
  currentVisibility,
  moderationStatus,
}: VisibilityTransitionMenuItemsProps) {
  const reasonId = useId();
  const isRestricted = resolveAccessStatus(currentVisibility, moderationStatus).kind === "restricted";

  return (
    <>
      {listVisibilityTransitions(currentVisibility).map((target) => {
        const Icon = VISIBILITY_ICON[target];
        return (
          <DropdownMenuItem
            key={target}
            aria-disabled={isRestricted || undefined}
            aria-describedby={isRestricted ? reasonId : undefined}
            onSelect={(event) => {
              if (isRestricted) {
                event.preventDefault();
                return;
              }
              void ChangeContentVisibilityModal.call({ contentId, creatorUserId, targetVisibility: target });
            }}
          >
            <Icon aria-hidden />
            {VISIBILITY_TRANSITION_COPY[target].label}로 전환
          </DropdownMenuItem>
        );
      })}

      {/* 구분선을 넣지 않는다 — 이건 다음 그룹의 머리가 아니라 **바로 위 두 항목의 사유**라서, 갈라 놓으면
          무엇에 대한 설명인지가 끊긴다. `max-w`가 없으면 메뉴 폭이 트리거가 아니라 이 한 문장으로 정해진다
          (`ContentCardActionMenu`가 콘텐츠에 맞추려고 `w-auto`를 준다). */}
      {isRestricted && (
        <DropdownMenuLabel id={reasonId} className="max-w-52 break-keep">
          {VISIBILITY_TRANSITION_BLOCKED_REASON}
        </DropdownMenuLabel>
      )}
    </>
  );
}
