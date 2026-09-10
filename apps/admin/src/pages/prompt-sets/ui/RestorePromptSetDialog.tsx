import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { useRestoreMutation } from "../api/useRestoreMutation";

type RestorePromptSetDialogProps = {
  id: string;
  version: string | null;
  publishedAt: string | null;
};

/** 복원은 게시가 아니라 초안 교체다 — 서비스에는 즉시 영향이 없지만, **지금 저장된 초안
 * 내용을 통째로 덮어써 되돌릴 방법이 없다**(클라이언트가 직전 초안을 따로 들고 있지 않다).
 * 그래서 인라인 버튼 하나로 바로 실행하지 않고 다이얼로그로 한 번 확인받는다 — 게시 다이얼로그와
 * 같은 이유, 같은 어휘(react-call, 자체 호출형). */
export const RestorePromptSetDialog = createCallable<RestorePromptSetDialogProps, void>(
  ({ call, id, version, publishedAt }) => {
    const restoreMutation = useRestoreMutation();

    const handleRestore = async () => {
      try {
        await restoreMutation.mutateAsync(id);
        toast.success("초안에 복원했어요. 서비스에 반영하려면 다시 게시하세요.");
        call.end();
      } catch {
        toast.error("복원에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>v{version ?? "?"}(으)로 복원</DialogTitle>
            <DialogDescription className="break-keep">
              {formatDateTime(publishedAt)}에 게시된 버전을 지금 초안으로 복제해요. 현재 저장된
              초안 내용은 사라지고, 서비스에는 다시 게시해야 반영돼요.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="button" disabled={restoreMutation.isPending} onClick={() => void handleRestore()}>
              {restoreMutation.isPending ? "복원 중..." : "이 버전으로 복원"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
