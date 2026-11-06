import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useMemo } from "react";
import { useForm } from "react-hook-form";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

import { useDeleteCredentialMutation } from "../api/useDeleteCredentialMutation";
import type { AdminLlmCredential } from "../model/credential";
import { classifyCredentialFailure } from "../model/failure";
import { deletedKeyText } from "../model/messages";
import { createDeleteConfirmSchema, type DeleteConfirmFormValues } from "../model/schema";
import type { CandidateChange } from "../model/status";
import { CandidateChangeList } from "./CandidateChangeList";
import { FailureAlert } from "./FailureAlert";

type DeleteCredentialDialogProps = {
  credential: AdminLlmCredential;
  /** 지우면 첫 후보가 바뀌는 축. 목록이 실제로 쓰이는 동안만 채운다. */
  changes: CandidateChange[];
  /** 목록이 쓰이는 동안 마지막 항목을 지운다 — 목록이 비면 런타임이 env 키로 돈다(실패가 아니다). */
  isLastOnLiveList: boolean;
};

export type DeleteCredentialOutcome = { status: "deleted" } | { status: "cancelled" };

/**
 * 지우기(확인 기록도 함께). 되돌릴 수 없어 이름을 정확히 다시 쳐야 확정된다 — 그 판정은 스키마 하나가 하고 버튼은 `isValid` 를 읽는다.
 * 이름 확인칸이 첫 포커스다. 콘솔에서 키를 폐기해도 되는지는 env 롤백 키와 같은 키인지로 갈린다.
 */
export const DeleteCredentialDialog = createCallable<DeleteCredentialDialogProps, DeleteCredentialOutcome>(
  ({ call, credential, changes, isLastOnLiveList }) => {
    const id = useId();
    const deleteMutation = useDeleteCredentialMutation();
    const schema = useMemo(() => createDeleteConfirmSchema(credential.label), [credential.label]);
    const {
      register,
      handleSubmit,
      setError,
      formState: { errors, isValid, isSubmitting },
    } = useForm<DeleteConfirmFormValues>({
      resolver: zodResolver(schema),
      defaultValues: { confirmText: "" },
      mode: "onChange",
    });
    const isConfirmBlocked = !isValid || isSubmitting;

    const onSubmit = async () => {
      try {
        await deleteMutation.mutateAsync(credential.id);
        call.end({ status: "deleted" });
      } catch (error) {
        setError("root.server", { type: "server", message: classifyCredentialFailure(error).message });
      }
    };

    const close = () => {
      if (!isSubmitting) call.end({ status: "cancelled" });
    };
    const inputId = `${id}-confirm`;
    const rootMessage = errors.root?.server?.message;

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && close()}>
        <DialogContent className="sm:max-w-lg" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle className="wrap-anywhere">‘{credential.label}’ 삭제</DialogTitle>
            <DialogDescription>이 항목과 확인 기록을 지워요. 되돌릴 수 없어요.</DialogDescription>
          </DialogHeader>

          <form
            noValidate
            autoComplete="off"
            onSubmit={(event) => {
              event.preventDefault();
              // 확정 버튼은 `aria-disabled` 라 눌러도 제출이 일어나고(포커스를 지키려고 `disabled` 를 쓰지 않는다), 입력칸 Enter 도
              // 제출한다. 이름이 맞지 않거나 보내는 중이면 여기서 멈춘다.
              if (isConfirmBlocked) return;
              void handleSubmit(onSubmit)(event);
            }}
            className="flex min-h-0 flex-1 flex-col gap-4"
          >
            <DialogBody scrollLabel="삭제 안내" className="flex flex-col gap-4">
              <div className="flex flex-col gap-2 text-sm break-keep text-foreground">
                <p>{deletedKeyText(credential.sameAsEnvKey)}</p>
                {isLastOnLiveList && <p>목록이 비면 env 키 경로로 돌아요.</p>}
                {!isLastOnLiveList && changes.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <p>다음 호출부터 이 모델들은 다른 항목으로 가요.</p>
                    <CandidateChangeList changes={changes} />
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor={inputId}>확인하려면 이름을 그대로 입력하세요</Label>
                <p className="text-sm font-medium break-keep text-foreground wrap-anywhere">{credential.label}</p>
                <Input
                  id={inputId}
                  autoFocus
                  data-initial-focus
                  autoComplete="off"
                  spellCheck={false}
                  {...register("confirmText")}
                />
              </div>

              {rootMessage !== undefined && <FailureAlert message={rootMessage} />}
            </DialogBody>

            <DialogFooter>
              <Button type="button" variant="outline" disabled={isSubmitting} onClick={close}>
                취소
              </Button>
              <Button
                type="submit"
                variant="destructive"
                aria-disabled={isConfirmBlocked}
                className="aria-disabled:opacity-65"
              >
                {isSubmitting ? "지우는 중…" : "삭제"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
