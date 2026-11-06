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
import type { AdminLlmCredential, AdminLlmCredentialUpdateRequest } from "../model/credential";
import { classifyCredentialFailure } from "../model/failure";
import { planFormFailure } from "../model/formFailure";
import {
  clearCreditToServer,
  creditBasisSchema,
  creditBasisToServer,
  creditServerToForm,
  type CreditBasisFormValues,
} from "../model/schema";
import { FailureAlert } from "./FailureAlert";
import { FormTextField } from "./FormTextField";

type CreditBasisDialogProps = {
  credential: AdminLlmCredential;
};

export type CreditBasisOutcome = { status: "saved"; credential: AdminLlmCredential } | { status: "cancelled" };

const CREDIT_FIELDS = ["creditUsd"] as const;

/**
 * 충전 뒤 사용액 기준 다시 잡기. 콘솔 잔액을 넣으면 그때부터 추정 사용액을 0 부터 다시 센다 — 값이 같아도 다시 잡는다. 충전액이
 * 있으면 지우는 길도 둔다(그 뒤로는 사용액을 세지 않는다). 충전액이 없는데 기준만 다시 잡으라는 요청은 서버가 거절한다.
 */
export const CreditBasisDialog = createCallable<CreditBasisDialogProps, CreditBasisOutcome>(({ call, credential }) => {
  const id = useId();
  const updateMutation = useUpdateCredentialMutation();
  const {
    register,
    handleSubmit,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<CreditBasisFormValues>({
    resolver: zodResolver(creditBasisSchema),
    defaultValues: creditServerToForm(credential),
  });
  const isBusy = isSubmitting || updateMutation.isPending;
  const hasCredit = credential.creditUsd !== null;
  const confirmLabel = hasCredit ? "기준 다시 잡기" : "충전액 넣기";

  const save = async (body: AdminLlmCredentialUpdateRequest) => {
    try {
      const saved = await updateMutation.mutateAsync({ id: credential.id, body });
      call.end({ status: "saved", credential: saved });
    } catch (error) {
      const plan = planFormFailure(classifyCredentialFailure(error), CREDIT_FIELDS);
      plan.fieldErrors.forEach(({ field, message }, index) =>
        setError(field, { type: "server", message }, { shouldFocus: index === 0 }),
      );
      if (plan.rootMessage !== undefined) setError("root.server", { type: "server", message: plan.rootMessage });
    }
  };

  const clearCredit = () => {
    if (isBusy) return;
    clearErrors();
    void save(clearCreditToServer());
  };

  const close = () => {
    if (!isBusy) call.end({ status: "cancelled" });
  };
  const rootMessage = errors.root?.server?.message;

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && close()}>
      <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
        <DialogHeader>
          <DialogTitle className="wrap-anywhere">
            ‘{credential.label}’ {hasCredit ? "충전액 맞추기" : "충전액 넣기"}
          </DialogTitle>
          <DialogDescription>
            {hasCredit
              ? "콘솔 잔액을 넣으면 지금부터 추정 사용액을 0 부터 다시 세요. 값이 같아도 기준을 다시 잡아요."
              : "콘솔 잔액을 넣으면 지금부터 추정 사용액을 세요."}
          </DialogDescription>
        </DialogHeader>

        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit((values) => save(creditBasisToServer(values)))(event);
          }}
          className="flex min-h-0 flex-1 flex-col gap-4"
        >
          <DialogBody className="flex flex-col gap-4">
            <FormTextField
              id={`${id}-credit`}
              label="충전액(달러)"
              hint="소수 둘째 자리까지 넣어요(예: 50 또는 49.5)."
              inputMode="decimal"
              isRequired
              registration={register("creditUsd")}
              error={errors.creditUsd?.message}
            />
            {hasCredit && (
              <div className="flex flex-col items-start gap-1">
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="h-auto px-0 admin-hit-area aria-disabled:opacity-65"
                  aria-disabled={isBusy}
                  onClick={clearCredit}
                >
                  충전액 지우기
                </Button>
                <p className="text-xs break-keep text-muted-foreground">지우면 사용액을 세지 않아요.</p>
              </div>
            )}
            {rootMessage !== undefined && <FailureAlert message={rootMessage} />}
          </DialogBody>

          <DialogFooter>
            <Button type="button" variant="outline" autoFocus data-initial-focus disabled={isBusy} onClick={close}>
              취소
            </Button>
            <Button type="submit" disabled={isBusy}>
              {isBusy ? "저장하는 중…" : confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
