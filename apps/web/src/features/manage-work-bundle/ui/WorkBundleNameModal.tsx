import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";

import { WORK_BUNDLE_NAME_MAX_LENGTH } from "@/entities/work";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useCreateWorkBundleMutation, useRenameWorkBundleMutation } from "../api/workBundleMutations";
import { toWorkBundleActionError } from "../model/bundleActionError";
import { countBundleNameChars, workBundleNameSchema, type WorkBundleNameFormValues } from "../model/bundleName";

const SUBMIT_LABEL = {
  create: { idle: "만들기", busy: "만드는 중…" },
  rename: { idle: "바꾸기", busy: "바꾸는 중…" },
} as const;

type WorkBundleNameModalProps =
  | { mode: "create" }
  | { mode: "rename"; bundleId: string; currentName: string };

/** 묶음 만들기·이름 바꾸기. 저장까지 이 모달이 하고, 만들었거나 이름을 바꾼 묶음의 id 로 끝난다(그만두면 `null`).
 *
 * 서버가 거절하면(묶음 수 한도 등) 이유를 입력칸 아래에 남기고 닫지 않는다 — 쓴 이름이 그대로 남는다. 재동의가 필요하면
 * 전역 재동의 모달이 뜨므로 그 위에 이 모달을 남겨 두지 않는다.
 *
 * 입력칸에 `maxLength` 를 걸지 않는다 — 브라우저는 UTF-16 단위로 세어 이모지를 2자로 막는다. 상한은 서버처럼 코드
 * 포인트로 세는 검사와 글자 수 표시가 맡는다. */
export const WorkBundleNameModal = createCallable<WorkBundleNameModalProps, string | null>(({ call, ...props }) => {
  const inputId = useId();
  const countId = useId();
  const errorId = useId();
  const createMutation = useCreateWorkBundleMutation();
  const renameMutation = useRenameWorkBundleMutation();
  const [saveError, setSaveError] = useState<string | undefined>(undefined);
  const form = useForm<WorkBundleNameFormValues>({
    resolver: zodResolver(workBundleNameSchema),
    defaultValues: { name: props.mode === "rename" ? props.currentName : "" },
  });
  const nameLength = countBundleNameChars(form.watch("name"));
  const errorMessage = form.formState.errors.name?.message ?? saveError;
  const isSaving = createMutation.isPending || renameMutation.isPending;

  async function handleValidSubmit(values: WorkBundleNameFormValues) {
    setSaveError(undefined);
    const name = values.name.trim();
    try {
      if (props.mode === "create") {
        call.end(await createMutation.mutateAsync(name));
      } else {
        await renameMutation.mutateAsync({ bundleId: props.bundleId, name });
        call.end(props.bundleId);
      }
    } catch (error) {
      const notice = toWorkBundleActionError(error, props.mode);
      if (notice === null) {
        call.end(null);
        return;
      }
      setSaveError(notice.message);
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
      <DialogContent className="sm:max-w-sm">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (isSaving) return;
            void form.handleSubmit(handleValidSubmit)(event);
          }}
        >
          <DialogHeader>
            <DialogTitle>{props.mode === "create" ? "새 묶음" : "묶음 이름 바꾸기"}</DialogTitle>
            <DialogDescription>나만 보는 정리예요. 독자에게는 보이지 않아요.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={inputId}>이름</Label>
            <Input
              id={inputId}
              autoFocus
              autoComplete="off"
              aria-invalid={errorMessage !== undefined}
              aria-describedby={errorMessage !== undefined ? `${countId} ${errorId}` : countId}
              onFocus={(event) => event.currentTarget.select()}
              {...form.register("name", { onChange: () => setSaveError(undefined) })}
            />
            <p
              id={countId}
              className={
                nameLength > WORK_BUNDLE_NAME_MAX_LENGTH
                  ? "self-end text-xs text-destructive-text tabular-nums"
                  : "self-end text-xs text-muted-foreground tabular-nums"
              }
            >
              <span className="sr-only">글자 수 </span>
              {nameLength} / {WORK_BUNDLE_NAME_MAX_LENGTH}
            </p>
            {errorMessage !== undefined && (
              <p id={errorId} role="alert" className="text-sm break-keep text-destructive-text">
                {errorMessage}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(null)}>
              취소
            </Button>
            <Button type="submit" aria-disabled={isSaving} className="aria-disabled:opacity-65">
              {SUBMIT_LABEL[props.mode][isSaving ? "busy" : "idle"]}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
