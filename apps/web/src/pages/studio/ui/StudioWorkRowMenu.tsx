import { DropdownMenuItem, DropdownMenuSeparator } from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { ExternalLink, FolderMinus, FolderPlus, RotateCcw, Trash2 } from "lucide-react";

import { ContentCardActionMenu } from "@/entities/content";
import type { WorkItem } from "@/entities/work";
import { VisibilityTransitionMenuItems } from "@/features/change-content-visibility";
import { DeleteNovelModal } from "@/features/delete-novel";
import { DeleteContentDraftModal, ResetContentDraftModal } from "@/features/manage-content-draft";
import { WorkBundlesForWorkModal } from "@/features/manage-work-bundle";

type StudioWorkRowMenuProps = {
  item: WorkItem;
  /** 행에 보이는 제목 — "⋯"의 접근 이름에 같은 글자를 쓴다. */
  title: string;
  /** 작품의 작가 = 언제나 나. 공개 범위 전환·편집분 버리기가 무효화할 목록 키를 만든다. */
  userId: string;
  /** 지운 행의 메뉴 버튼은 행과 함께 사라진다 — 포커스를 받아 둘 자리로 옮긴다. */
  onRemoved: () => void;
  /** 묶음 화면에서만 — "이 묶음에서 빼기". 확인 없이 빼고 되돌리기를 내민다(페이지가 한다). */
  onRemoveFromBundle?: () => void;
};

/**
 * 행에서 바로 손대는 관리 메뉴. 행 자체가 다음 행동(빌더·작품 정보)으로 가는 링크라 메뉴에는 그 밖의 일만 둔다.
 *
 * - 발행작: 작품 페이지 보기 · 공개 범위 바꾸기(현재 값은 뺀다) · 편집한 내용 버리기(버릴 편집분이 있을 때만)
 * - 초안: 삭제하기
 * - 소설: 소설 지우기
 *
 * 셋 모두 맨 위에 "묶음에 넣기…"가 있고, 묶음 화면이면 그 아래 "이 묶음에서 빼기"가 있다.
 *
 * 할 수 없는 항목은 비활성이 아니라 부재로 둔다 — 내 작품 화면의 카드 메뉴와 같은 규칙이고, 항목은 그 메뉴와 같은
 * 기능 조각을 쓴다(확인 모달·문구·캐시 무효화가 한 곳).
 */
export function StudioWorkRowMenu({ item, title, userId, onRemoved, onRemoveFromBundle }: StudioWorkRowMenuProps) {
  const bundleItems = (
    <>
      <DropdownMenuItem onSelect={() => void WorkBundlesForWorkModal.call({ work: { kind: item.kind, id: item.id }, title })}>
        <FolderPlus aria-hidden />
        묶음에 넣기…
      </DropdownMenuItem>
      {onRemoveFromBundle && (
        <DropdownMenuItem onSelect={onRemoveFromBundle}>
          <FolderMinus aria-hidden />이 묶음에서 빼기
        </DropdownMenuItem>
      )}
      <DropdownMenuSeparator />
    </>
  );

  if (item.kind === "novel") {
    return (
      <ContentCardActionMenu title={title}>
        {bundleItems}
        <DropdownMenuItem
          variant="destructive"
          onSelect={() =>
            void DeleteNovelModal.call({ novelId: item.id, title, hasActiveJob: undefined }).then((isDeleted) => {
              if (isDeleted) onRemoved();
            })
          }
        >
          <Trash2 aria-hidden />
          소설 지우기
        </DropdownMenuItem>
      </ContentCardActionMenu>
    );
  }

  if (!item.hasPublished) {
    return (
      <ContentCardActionMenu title={title}>
        {bundleItems}
        <DropdownMenuItem
          variant="destructive"
          onSelect={() =>
            void DeleteContentDraftModal.call({ contentId: item.id }).then((isDeleted) => {
              if (isDeleted) onRemoved();
            })
          }
        >
          <Trash2 aria-hidden />
          삭제하기
        </DropdownMenuItem>
      </ContentCardActionMenu>
    );
  }

  return (
    <ContentCardActionMenu title={title}>
      {bundleItems}
      <DropdownMenuItem asChild>
        <Link to="/content/$type/$id" params={{ type: item.kind, id: item.id }}>
          <ExternalLink aria-hidden />
          작품 페이지 보기
        </Link>
      </DropdownMenuItem>

      <DropdownMenuSeparator />

      <VisibilityTransitionMenuItems
        contentId={item.id}
        creatorUserId={userId}
        currentVisibility={item.visibility}
        moderationStatus={item.moderationStatus}
      />

      {item.hasUnpublishedChanges && (
        <>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => void ResetContentDraftModal.call({ contentId: item.id, creatorUserId: userId })}
          >
            <RotateCcw aria-hidden />
            편집한 내용 버리기
          </DropdownMenuItem>
        </>
      )}
    </ContentCardActionMenu>
  );
}
