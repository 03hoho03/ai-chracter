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

import { useReplaceSecretMutation } from "../api/useReplaceSecretMutation";
import type { AdminLlmCredential } from "../model/credential";
import { classifyCredentialFailure } from "../model/failure";
import { planFormFailure } from "../model/formFailure";
import {
  REPLACE_SECRET_DEFAULT_VALUES,
  replaceFormToServer,
  replaceSecretSchema,
  type ReplaceSecretFormValues,
} from "../model/schema";
import type { CandidateChange } from "../model/status";
import { CandidateChangeList } from "./CandidateChangeList";
import { FailureAlert } from "./FailureAlert";
import { SecretField } from "./SecretField";

type ReplaceSecretDialogProps = {
  /** 연 순간의 항목. 같은 키인지·옛 키가 env 키였는지는 이 값과 응답을 견준다 — 응답 뒤의 캐시는 이미 새 값이다. */
  credential: AdminLlmCredential;
  /** 다른 키로 바꾸면 이 항목이 확인 전까지 받지 않아 첫 후보가 바뀌는 축. 목록이 실제로 쓰이는 동안만 채운다. */
  changes: CandidateChange[];
  notificationsConfigured: boolean;
};

export type ReplaceSecretOutcome = { status: "replaced"; credential: AdminLlmCredential } | { status: "cancelled" };

const REPLACE_FIELDS = ["apiKey"] as const;

/**
 * 키만 바꾼다(같은 조직의 키로만). 붙여넣을 키가 예전에 이 항목에서 쓰던 키인지, 지금 키와 같은 키인지 화면은 미리 모른다 — 그래서
 * 미리보기는 "다른 키면"으로 조건을 단다. 실제로 무엇이 되었는지는 응답의 지문과 확인 기록이 정한다.
 *
 * 키를 다루는 방식은 추가 대화상자와 같다 — 성공하면 폼을 비우고, 제출 처리가 끝날 때마다 뮤테이션을 비우고, 보내는 동안은 닫지 않는다.
 */
export const ReplaceSecretDialog = createCallable<ReplaceSecretDialogProps, ReplaceSecretOutcome>(
  ({ call, credential, changes, notificationsConfigured }) => {
    const id = useId();
    const replaceMutation = useReplaceSecretMutation();
    const {
      register,
      handleSubmit,
      reset,
      resetField,
      setError,
      formState: { errors, isSubmitting },
    } = useForm<ReplaceSecretFormValues>({
      resolver: zodResolver(replaceSecretSchema),
      defaultValues: REPLACE_SECRET_DEFAULT_VALUES,
    });

    const onSubmit = async (values: ReplaceSecretFormValues) => {
      try {
        const replaced = await replaceMutation.mutateAsync({ id: credential.id, ...replaceFormToServer(values) });
        reset(REPLACE_SECRET_DEFAULT_VALUES);
        call.end({ status: "replaced", credential: replaced });
      } catch (error) {
        const plan = planFormFailure(classifyCredentialFailure(error, { notificationsConfigured }), REPLACE_FIELDS);
        if (plan.clearsSecret) resetField("apiKey");
        plan.fieldErrors.forEach(({ field, message }, index) =>
          setError(field, { type: "server", message }, { shouldFocus: index === 0 }),
        );
        if (plan.rootMessage !== undefined) setError("root.server", { type: "server", message: plan.rootMessage });
      } finally {
        replaceMutation.reset();
      }
    };

    const close = () => {
      if (!isSubmitting) call.end({ status: "cancelled" });
    };
    const rootMessage = errors.root?.server?.message;

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && close()}>
        <DialogContent className="sm:max-w-lg" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle className="wrap-anywhere">‘{credential.label}’ 키 교체</DialogTitle>
            <DialogDescription>같은 조직의 키로만 바꿀 수 있어요.</DialogDescription>
          </DialogHeader>

          <form
            noValidate
            autoComplete="off"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex min-h-0 flex-1 flex-col gap-4"
          >
            <DialogBody scrollLabel="키 교체 안내" className="flex flex-col gap-4">
              <div className="flex flex-col gap-2 text-sm break-keep text-foreground">
                <p>
                  다른 키면 확인 호출이 통과할 때까지 이 항목을 쓰지 않아요(예전에 이 항목에서 쓰던 키면 그 키로 한 이전 확인이 바로
                  다시 세요).
                </p>
                {changes.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <p>다른 키면 다음 호출부터 이 모델들은 다른 항목으로 가요.</p>
                    <CandidateChangeList changes={changes} />
                  </div>
                )}
                {credential.sameAsEnvKey && (
                  <p>다른 키면 지금 키는 env 롤백 키와 같으니 콘솔에서 폐기하지 마세요.</p>
                )}
                <p className="text-muted-foreground">
                  같은 키를 다시 붙여넣으면 암호문만 다시 쓰고 확인 기록은 그대로예요(저장한 키를 읽을 수 없을 때 살리는 길).
                </p>
              </div>

              <SecretField id={`${id}-api-key`} registration={register("apiKey")} error={errors.apiKey?.message} />

              {rootMessage !== undefined && <FailureAlert message={rootMessage} />}
            </DialogBody>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                autoFocus
                data-initial-focus
                disabled={isSubmitting}
                onClick={close}
              >
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "바꾸는 중…" : "키 바꾸기"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
