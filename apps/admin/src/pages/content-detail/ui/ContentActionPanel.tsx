import { Button } from "@ai-character-chat/ui/components/button";

import type { ContentModerationStatusFilter } from "@/entities/admin-content";

import { ContentActionConfirmModal } from "./ContentActionConfirmModal";

type ContentActionPanelProps = {
  contentId: string;
  contentName: string;
  moderationStatus: ContentModerationStatusFilter;
};

/** goal-prompt.md 2단계 — ReportActionPanel의 두 축 판단 방식과 같은 결이다: restrict/delete는
 * `moderationStatus`가 그 상태가 **아닐 때**, lift-restriction은 `moderationStatus === "restricted"`
 * 일 때만 노출한다(API 제약: `reject`는 직접 조치에 없고, 비restricted에 lift-restriction은 400).
 * `deleted`는 갈 수 있는 유효한 조치가 없다 — lift-restriction은 restricted가 아니면 400이고
 * restrict/delete를 다시 거는 것도 의미가 없어, 조치 버튼 대신 안내 한 줄만 보여준다. */
export function ContentActionPanel({ contentId, contentName, moderationStatus }: ContentActionPanelProps) {
  if (moderationStatus === "deleted") {
    return (
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">조치</h2>
        <p className="text-sm text-muted-foreground">삭제된 작품입니다.</p>
      </section>
    );
  }

  const canRestrict = moderationStatus !== "restricted";
  const canLiftRestriction = moderationStatus === "restricted";

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">조치</h2>
      <div className="flex flex-wrap gap-2">
        {canRestrict && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void ContentActionConfirmModal.call({ contentId, contentName, action: "restrict" })}
          >
            이용제한 부과
          </Button>
        )}
        {canLiftRestriction && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void ContentActionConfirmModal.call({ contentId, contentName, action: "lift-restriction" })
            }
          >
            이용제한 해제
          </Button>
        )}
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={() => void ContentActionConfirmModal.call({ contentId, contentName, action: "delete" })}
        >
          삭제
        </Button>
      </div>
    </section>
  );
}
