import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { toast } from "sonner";

import { isApiError } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { toKstDate } from "../model/effectiveDate";
import { LEGAL_KIND_LABELS, type LegalKind } from "../model/legalKind";
import { useWithdrawMutation } from "../api/useWithdrawMutation";

type WithdrawDialogProps = {
  kind: LegalKind;
  version: string;
  effectiveAt: string;
};

/** 시행 예정 판 철회 확인. 철회한 판은 이력에 "철회"로 남고 그 버전 이름은 다시 쓸 수 없다 — 이미 공지로 나갔을 수 있어서다.
 * 되돌릴 수 없지만 지우는 것은 아니라(고친 판을 다른 버전으로 다시 예약하면 된다) 이름 다시 치기 확인까지는 두지 않는다.
 * 서버가 거절하면(그새 시행됨·이미 철회됨) 그 문장을 토스트로 보이고 닫는다 — 이력이 다시 불러와져 지금 상태가 보인다. */
export const WithdrawDialog = createCallable<WithdrawDialogProps, void>(({ call, kind, version, effectiveAt }) => {
  const withdrawMutation = useWithdrawMutation(kind);

  const handleWithdraw = async () => {
    try {
      await withdrawMutation.mutateAsync(version);
      toast.success(`${LEGAL_KIND_LABELS[kind]} v${version} 예약을 철회했어요.`);
    } catch (error) {
      toast.error(
        isApiError(error) && typeof error.detail === "string"
          ? error.detail
          : "철회에 실패했어요. 잠시 후 다시 시도해주세요.",
      );
    }
    call.end();
  };

  return (
    // 철회 요청 중에는 닫지 않는다 — 닫힌 뒤에 결과 토스트가 따로 뜨지 않게, 결과를 본 뒤 닫힌다.
    <Dialog open={!call.ended} onOpenChange={(open) => !open && !withdrawMutation.isPending && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>v{version} 예약 철회</DialogTitle>
          <DialogDescription className="break-keep">
            {toKstDate(effectiveAt)} 시행 예정인 {LEGAL_KIND_LABELS[kind]} v{version}을 철회해요. 이 판은 시행되지 않고
            이력에 철회로 남으며, 같은 버전 이름은 다시 쓸 수 없어요. 이미 공지했다면 정정 공지는 따로 올려 주세요.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            autoFocus
            disabled={withdrawMutation.isPending}
            onClick={() => call.end()}
          >
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={withdrawMutation.isPending}
            onClick={() => void handleWithdraw()}
          >
            {withdrawMutation.isPending ? "철회 중..." : "예약 철회"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
