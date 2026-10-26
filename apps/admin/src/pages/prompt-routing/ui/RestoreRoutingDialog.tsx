import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import type { AdminPromptRoutingResponse } from "@/entities/prompt-routing";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import type { AdminPromptRouteRevisionSummary } from "../api/useRevisionListQuery";
import { useRestoreRoutingMutation } from "../api/useRestoreRoutingMutation";
import type { RoutingOutcome } from "../model/outcome";
import { classifyRouteSaveError } from "../model/routeErrors";
import { cellKeyMap, ROUTING_SCOPE_LABELS, type RoutingScope } from "../model/schema";

type RestoreRoutingDialogProps = {
  revision: AdminPromptRouteRevisionSummary;
  /** 되돌릴 범위. 그 이력의 표에서 이 범위의 행만 꺼내고, 다른 범위의 지금 행은 그대로 둔다. */
  scope: RoutingScope;
  /** 그 이력의 표에서 이 범위에 든 행 수. */
  scopeRowCount: number;
  /** 화면이 보던 표 — 기준 이력과 다음 번호, 거부된 칸을 표의 칸으로 좁히는 데 쓴다. */
  data: AdminPromptRoutingResponse;
  /** 저장하지 않은 편집 칸 수. 되돌리면 폼이 새 표로 바뀌어 사라진다. */
  dirtyCount: number;
};

type RestoreFormValues = { note: string };

/** 되돌리기도 새 이력으로 저장해 다음 턴부터 운영 경로를 바꾸므로 저장과 같은 무게로 확인받는다. 옛 표를 지금 env·게시 세트로 다시
 * 검사하므로 그 사이 바뀐 것이 있으면 거부될 수 있다는 사실을 함께 알린다. */
export const RestoreRoutingDialog = createCallable<RestoreRoutingDialogProps, RoutingOutcome | undefined>(
  ({ call, revision, scope, scopeRowCount, data, dirtyCount }) => {
    const restoreMutation = useRestoreRoutingMutation(scope);
    const scopeName = ROUTING_SCOPE_LABELS[scope];
    const {
      register,
      handleSubmit,
      formState: { isSubmitting },
    } = useForm<RestoreFormValues>({ defaultValues: { note: "" } });
    const nextNumber = (data.revisionNumber ?? 0) + 1;

    const onSubmit = async (values: RestoreFormValues) => {
      try {
        const restored = await restoreMutation.mutateAsync({
          id: revision.id,
          baseRevisionId: data.revisionId,
          note: values.note,
        });
        call.end({ status: "saved", data: restored });
      } catch (error) {
        const failure = classifyRouteSaveError(error, cellKeyMap(data));
        if (failure.kind === "other") {
          toast.error("되돌리기에 실패했어요. 잠시 후 다시 시도해주세요.");
          return;
        }
        call.end({ status: "failed", failure });
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end(undefined)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {scopeName} 칸을 r{revision.number} 로 되돌리기
            </DialogTitle>
            <DialogDescription>
              {formatDateTime(revision.createdAt)} 표의 {scopeName} 칸({scopeRowCount}칸)을 지금 env·게시 세트로 다시 검사해
              새 이력(r{nextNumber})으로 저장해요. {scope === "chat" ? "소설" : "채팅"} 칸은 지금 그대로예요. 그 사이 env
              배정이나 게시 세트가 바뀌었으면 거부될 수 있어요. 바로 반영돼요.
              {dirtyCount > 0 && ` 저장하지 않은 편집 ${dirtyCount}칸은 버려져요.`}
            </DialogDescription>
          </DialogHeader>
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="prompt-routing-restore-note">메모</Label>
              <Textarea
                id="prompt-routing-restore-note"
                placeholder="왜 되돌리는지 남겨두면 나중에 이력을 볼 때 도움이 돼요."
                {...register("note")}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" autoFocus onClick={() => call.end(undefined)}>
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "되돌리는 중..." : "되돌리기"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
