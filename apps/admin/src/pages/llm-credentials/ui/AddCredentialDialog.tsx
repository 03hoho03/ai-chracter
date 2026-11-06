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

import { useCreateCredentialMutation } from "../api/useCreateCredentialMutation";
import type { AdminLlmCredential } from "../model/credential";
import { classifyCredentialFailure } from "../model/failure";
import { planFormFailure } from "../model/formFailure";
import {
  ADD_CREDENTIAL_DEFAULT_VALUES,
  addCredentialSchema,
  addFormToServer,
  type AddCredentialFormValues,
} from "../model/schema";
import { FailureAlert } from "./FailureAlert";
import { FormTextField } from "./FormTextField";
import { SecretField } from "./SecretField";

type AddCredentialDialogProps = {
  /** 허용 목록 밖 키 거절에 "운영 알림이 갔어요"를 붙일지 — 웹훅이 없으면 서버가 경고 로그만 남긴다. */
  notificationsConfigured: boolean;
};

export type AddCredentialOutcome = { status: "added"; credential: AdminLlmCredential } | { status: "cancelled" };

const ADD_FIELDS = ["apiKey", "label", "creditUsd", "alertPct"] as const;

/**
 * 자격 추가. 공급자는 고르는 칸이 아니라 고정 줄이다 — 지금 서버가 Anthropic 만 받는다. 새 항목은 꺼진 채 목록 끝에 들어간다.
 *
 * 붙여넣은 키는 폼 값과 뮤테이션의 요청 변수 두 곳에 산다. 성공하면 폼을 비우고, 제출 처리가 끝날 때마다(성공·실패 모두) 뮤테이션을
 * 비워 관찰자를 뗀다 — 열린 채 실패하면 이 대화상자가 관찰자로 남아 키를 담은 요청 변수가 지워지지 않는다. 대화상자가 닫히면 폼이
 * 통째로 언마운트되어 입력값이 남지 않는다.
 *
 * 보내는 동안은 Esc·바깥 누르기·닫기·취소로 닫지 않는다 — 닫은 뒤 거절되면 그 이유를 보일 자리가 없고, 운영자는 저장된 줄 안다.
 */
export const AddCredentialDialog = createCallable<AddCredentialDialogProps, AddCredentialOutcome>(
  ({ call, notificationsConfigured }) => {
    const id = useId();
    const createMutation = useCreateCredentialMutation();
    const {
      register,
      handleSubmit,
      reset,
      resetField,
      setError,
      formState: { errors, isSubmitting },
    } = useForm<AddCredentialFormValues>({
      resolver: zodResolver(addCredentialSchema),
      defaultValues: ADD_CREDENTIAL_DEFAULT_VALUES,
    });

    const onSubmit = async (values: AddCredentialFormValues) => {
      try {
        const credential = await createMutation.mutateAsync(addFormToServer(values));
        reset(ADD_CREDENTIAL_DEFAULT_VALUES);
        call.end({ status: "added", credential });
      } catch (error) {
        const plan = planFormFailure(classifyCredentialFailure(error, { notificationsConfigured }), ADD_FIELDS);
        if (plan.clearsSecret) resetField("apiKey");
        plan.fieldErrors.forEach(({ field, message }, index) =>
          setError(field, { type: "server", message }, { shouldFocus: index === 0 }),
        );
        if (plan.rootMessage !== undefined) setError("root.server", { type: "server", message: plan.rootMessage });
      } finally {
        createMutation.reset();
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
            <DialogTitle>Claude 자격 추가</DialogTitle>
            <DialogDescription>
              새 항목은 꺼진 채 목록 끝에 들어가요. 확인 호출이 통과한 뒤 켤 수 있어요.
            </DialogDescription>
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
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-0.5">
                <p className="text-sm">
                  <span className="text-muted-foreground">공급자</span>{" "}
                  <span className="font-medium text-foreground">Anthropic</span>
                </p>
                <p className="text-xs break-keep text-muted-foreground">Bedrock 은 아직 받지 않아요.</p>
              </div>

              <SecretField id={fieldId("api-key")} registration={register("apiKey")} error={errors.apiKey?.message} />

              <FormTextField
                id={fieldId("label")}
                label="이름"
                hint="목록·알림·감사 기록에 이 이름으로 나와요. 40자까지예요."
                isRequired
                registration={register("label")}
                error={errors.label?.message}
              />

              <FormTextField
                id={fieldId("credit")}
                label="충전액(달러, 선택)"
                hint="콘솔에 충전한 금액이에요. 넣으면 지금부터 추정 사용액을 세고, 비우면 세지 않아요."
                inputMode="decimal"
                registration={register("creditUsd")}
                error={errors.creditUsd?.message}
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
                {isSubmitting ? "추가하는 중…" : "추가"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
