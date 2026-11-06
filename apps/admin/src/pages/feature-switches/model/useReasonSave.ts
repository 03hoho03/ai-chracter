import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { reasonSchema, type ReasonFormValues } from "./reasonSchema";
import { toSaveFailure } from "./saveFailure";

type ReasonSaveOptions = {
  /** 저장하고 성공 처리(토스트·모달 닫기)까지 한다. 실패하면 던진다. */
  save: (reason: string) => Promise<void>;
  /** 화면이 본 값이 낡아 모달을 닫아야 하는 실패에서 부른다. */
  onStale: () => void;
};

/** 사유를 받는 저장 모달 둘(바꾸기·덮어쓰기 지우기)이 함께 쓰는 폼과 실패 처리. 실패는 사유를 살린 채 모달 안에 두거나
 * 칸 오류로 보이고, 낡은 값 때문의 거절만 닫는다. */
export function useReasonSave({ save, onStale }: ReasonSaveOptions) {
  const [failureMessage, setFailureMessage] = useState<string | null>(null);
  const form = useForm<ReasonFormValues>({ resolver: zodResolver(reasonSchema), defaultValues: { reason: "" } });
  const reason = useWatch({ control: form.control, name: "reason" });

  const submit = form.handleSubmit(async (values) => {
    setFailureMessage(null);
    try {
      await save(values.reason);
    } catch (error) {
      const failure = toSaveFailure(error);
      if (failure.kind === "field") {
        form.setError("reason", { type: "server", message: failure.message });
        return;
      }
      if (failure.kind === "close") {
        toast.error(failure.message);
        onStale();
        return;
      }
      setFailureMessage(failure.message);
    }
  });

  return {
    form,
    submit,
    failureMessage,
    // 빈칸·공백뿐이면 확정할 수 없다 — 서버도 같은 사유를 거절한다.
    isReasonBlank: reason.trim() === "",
  };
}
