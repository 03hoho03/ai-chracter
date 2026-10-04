import { Button } from "@ai-character-chat/ui/components/button";

import type { ContentModerationStatusFilter } from "@/entities/admin-content";

import { ContentActionConfirmModal } from "./ContentActionConfirmModal";

type ContentActionPanelProps = {
  contentId: string;
  contentName: string;
  moderationStatus: Exclude<ContentModerationStatusFilter, "deleted">;
  /** 조치가 성공하면(확인 모달이 닫힌 뒤) 부른다 — 상세 레이아웃이 시트를 닫는다. */
  onSuccess?: () => void;
};

/** ReportActionPanel의 두 축 판단 방식과 같은 결이다: restrict/delete는
 * `moderationStatus`가 그 상태가 **아닐 때**, lift-restriction은 `moderationStatus === "restricted"`
 * 일 때만 노출한다(API 제약: `reject`는 직접 조치에 없고, 비restricted에 lift-restriction은 400).
 * `deleted`는 갈 수 있는 유효한 조치가 없다 — lift-restriction은 restricted가 아니면 400이고
 * restrict/delete를 다시 거는 것도 의미가 없다. 그 판정은 상세 레이아웃이 조치 열을 그릴지 정해야 해서 호출부가
 * 하고, 이 패널은 삭제되지 않은 작품만 받는다. 제목·표면은 조치 열·시트가 진다. */
export function ContentActionPanel({ contentId, contentName, moderationStatus, onSuccess }: ContentActionPanelProps) {
  const canRestrict = moderationStatus !== "restricted";
  const canLiftRestriction = moderationStatus === "restricted";

  return (
    <div className="flex flex-col gap-2">
      {canRestrict && (
        <Button
          type="button"
          variant="outline"
          onClick={() => void ContentActionConfirmModal.call({ contentId, contentName, action: "restrict", onSuccess })}
        >
          이용제한 부과
        </Button>
      )}
      {canLiftRestriction && (
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            void ContentActionConfirmModal.call({ contentId, contentName, action: "lift-restriction", onSuccess })
          }
        >
          이용제한 해제
        </Button>
      )}
      <Button
        type="button"
        variant="destructive"
        onClick={() => void ContentActionConfirmModal.call({ contentId, contentName, action: "delete", onSuccess })}
      >
        삭제
      </Button>
    </div>
  );
}
