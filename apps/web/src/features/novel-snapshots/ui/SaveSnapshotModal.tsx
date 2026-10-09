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
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";

import {
  novelKeys,
  toNovelActionError,
  useCreateNovelSnapshotMutation,
  type NovelSnapshotSummary,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { createSnapshotNameSchema, type SnapshotNameFormValues } from "../model/snapshotName";

type SaveSnapshotModalProps = {
  novelId: string;
  /** 상세의 `limits.snapshotNameMaxLength`. */
  maxLength: number;
  /** 입력칸에 채워 둘 이름(`toDefaultSnapshotName`). */
  defaultName: string;
};

/** 지금 상태를 이름 붙여 남긴다. 저장까지 이 모달이 한다(호출부마다 뒤처리가 같다 — 버전 목록이 다시 받아진다).
 * 저장한 버전을 돌려주고, 그만두면 `null` 이다.
 *
 * 이름 붙인 버전만으로 상한이 차 있으면 서버가 거부한다 — 그 이유와 할 일(하나 지운 뒤 다시)을 입력칸 아래에 남기고
 * 모달은 닫지 않는다. 쓴 이름은 그대로라 지운 뒤 같은 이름으로 다시 저장할 수 있다. */
export const SaveSnapshotModal = createCallable<SaveSnapshotModalProps, NovelSnapshotSummary | null>(
  ({ call, novelId, maxLength, defaultName }) => {
    const queryClient = useQueryClient();
    const inputId = useId();
    const errorId = useId();
    const mutation = useCreateNovelSnapshotMutation();
    const [saveError, setSaveError] = useState<string | undefined>(undefined);
    const form = useForm<SnapshotNameFormValues>({
      resolver: zodResolver(createSnapshotNameSchema(maxLength)),
      defaultValues: { name: defaultName },
    });
    const errorMessage = form.formState.errors.name?.message ?? saveError;
    const isSaving = mutation.isPending;

    async function handleValidSubmit(values: SnapshotNameFormValues) {
      setSaveError(undefined);
      try {
        call.end(await mutation.mutateAsync({ novelId, name: values.name.trim() }));
      } catch (error) {
        const notice = toNovelActionError(error, "saveSnapshot");
        // 재동의가 필요하면 전역 재동의 모달이 뜬다 — 그 위에 이 모달을 남겨 두지 않는다.
        if (notice === null) {
          call.end(null);
          return;
        }
        setSaveError(notice.message);
        if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
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
              <DialogTitle>지금 상태 저장</DialogTitle>
              <DialogDescription className="break-keep">
                화의 글·제목·작가의 말, 소설 제목·소개, 설정 노트, 인물 메모를 지금 그대로 남겨요. 언제든 이 때로 되돌릴 수
                있어요.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <Label htmlFor={inputId}>버전 이름</Label>
              <Input
                id={inputId}
                autoFocus
                autoComplete="off"
                aria-invalid={errorMessage !== undefined}
                aria-describedby={errorMessage !== undefined ? errorId : undefined}
                onFocus={(event) => event.currentTarget.select()}
                {...form.register("name")}
              />
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
                {isSaving ? "저장 중…" : "저장"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
