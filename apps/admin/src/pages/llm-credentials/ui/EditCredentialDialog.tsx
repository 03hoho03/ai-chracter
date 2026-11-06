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
import { zodResolver } from "@hookform/resolvers/zod";
import { useId } from "react";
import { useForm } from "react-hook-form";

import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

import { useUpdateCredentialMutation } from "../api/useUpdateCredentialMutation";
import type { AdminLlmCredential } from "../model/credential";
import { classifyCredentialFailure } from "../model/failure";
import { planFormFailure } from "../model/formFailure";
import {
  editCredentialSchema,
  editFormToServer,
  editServerToForm,
  type EditCredentialFormValues,
} from "../model/schema";
import { FailureAlert } from "./FailureAlert";
import { FormTextField } from "./FormTextField";

type EditCredentialDialogProps = {
  credential: AdminLlmCredential;
};

export type EditCredentialOutcome = { status: "saved"; credential: AdminLlmCredential } | { status: "cancelled" };

const EDIT_FIELDS = ["label", "alertPct"] as const;

/** 이름·임계 수정. 충전액 칸을 싣지 않는다 — 이 대화상자는 사용액 기준을 건드릴 수 없다(충전액은 따로 맞춘다). */
export const EditCredentialDialog = createCallable<EditCredentialDialogProps, EditCredentialOutcome>(({ call, credential }) => {
  const id = useId();
  const updateMutation = useUpdateCredentialMutation();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<EditCredentialFormValues>({
    resolver: zodResolver(editCredentialSchema),
    defaultValues: editServerToForm(credential),
  });

  const onSubmit = async (values: EditCredentialFormValues) => {
    try {
      const saved = await updateMutation.mutateAsync({ id: credential.id, body: editFormToServer(values) });
      call.end({ status: "saved", credential: saved });
    } catch (error) {
      const plan = planFormFailure(classifyCredentialFailure(error), EDIT_FIELDS);
      plan.fieldErrors.forEach(({ field, message }, index) =>
        setError(field, { type: "server", message }, { shouldFocus: index === 0 }),
      );
      if (plan.rootMessage !== undefined) setError("root.server", { type: "server", message: plan.rootMessage });
    }
  };

  const close = () => {
    if (!isSubmitting) call.end({ status: "cancelled" });
  };
  const fieldId = (name: string) => `${id}-${name}`;
  const rootMessage = errors.root?.server?.message;

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && close()}>
      <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
        <DialogHeader>
          <DialogTitle className="wrap-anywhere">‘{credential.label}’ 이름·임계 수정</DialogTitle>
          <DialogDescription>충전액과 사용액 기준은 그대로예요. 충전액은 사용액 블록의 충전액 맞추기에서 바꿔요.</DialogDescription>
        </DialogHeader>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(onSubmit)(event);
          }}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <DialogBody className="flex flex-col gap-4">
            <FormTextField
              id={fieldId("label")}
              label="이름"
              hint="40자까지예요."
              isRequired
              registration={register("label")}
              error={errors.label?.message}
            />
            <FormTextField
              id={fieldId("alert")}
              label="알림 임계(%)"
              hint="추정 잔액이 충전액의 이 비율 아래로 내려가면 임계 아래로 표시하고 알려요."
              inputMode="numeric"
              isRequired
              registration={register("alertPct")}
              error={errors.alertPct?.message}
            />
            {rootMessage !== undefined && <FailureAlert message={rootMessage} />}
          </DialogBody>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus data-initial-focus disabled={isSubmitting} onClick={close}>
              취소
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "저장하는 중…" : "저장"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
