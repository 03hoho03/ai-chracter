import { Button } from "@ai-character-chat/ui/components/button";

import { UserActionConfirmModal } from "./UserActionConfirmModal";

type Props = {
  userId: string;
  suspendedAt: string | null;
  restrictableContentCount: number;
};

/** ContentActionPanel과 같은 결 — `suspendedAt` 하나로 분기한다: null이면 [경고][정지],
 * not-null이면 [경고][정지 해제]. 경고는 정지 중에도 BE가 허용한다. */
export function UserActionPanel({ userId, suspendedAt, restrictableContentCount }: Props) {
  const isSuspended = suspendedAt !== null;

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">조치</h2>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void UserActionConfirmModal.call({ userId, action: "warn", restrictableContentCount })}
        >
          경고
        </Button>
        {isSuspended ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void UserActionConfirmModal.call({ userId, action: "unsuspend", restrictableContentCount })
            }
          >
            정지 해제
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              void UserActionConfirmModal.call({ userId, action: "suspend", restrictableContentCount })
            }
          >
            정지
          </Button>
        )}
      </div>
    </section>
  );
}
