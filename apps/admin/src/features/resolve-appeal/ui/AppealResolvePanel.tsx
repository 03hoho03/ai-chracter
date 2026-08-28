import { toast } from "sonner";
import { Button } from "@ai-character-chat/ui/components/button";

import {
  APPEAL_VERDICT_LABELS,
  useResolveAppealMutation,
  type AdminAppealListItem,
} from "@/entities/appeal";

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

type Props = {
  appeal: AdminAppealListItem;
};

/** techspec-admin.md §2 — US-123이 만든 POST /admin/appeals/{id}/resolve의 첫 FE 소비처. */
export function AppealResolvePanel({ appeal }: Props) {
  const resolveAppeal = useResolveAppealMutation(appeal.id);

  if (appeal.status !== "pending") {
    return (
      <p className="text-sm text-muted-foreground">
        처리결과: {appeal.verdict ? APPEAL_VERDICT_LABELS[appeal.verdict] : "-"}
      </p>
    );
  }

  const handleResolve = (verdict: "accepted" | "rejected") => {
    resolveAppeal.mutate(verdict, {
      onSuccess: () => toast.success(`${APPEAL_VERDICT_LABELS[verdict]} 처리했어요.`),
      onError: () => toast.error(ERROR_MESSAGE),
    });
  };

  return (
    <div className="flex gap-2">
      <Button
        type="button"
        variant="outline"
        disabled={resolveAppeal.isPending}
        onClick={() => handleResolve("rejected")}
      >
        기각
      </Button>
      <Button type="button" disabled={resolveAppeal.isPending} onClick={() => handleResolve("accepted")}>
        인용
      </Button>
    </div>
  );
}
