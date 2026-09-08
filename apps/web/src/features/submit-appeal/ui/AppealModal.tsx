import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { createCallable } from "react-call";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useSubmitAppealMutation, type AppealTarget } from "../api/useSubmitAppealMutation";
import { submitAppealSchema, type SubmitAppealFormValues } from "../model/schema";

type AppealModalProps = {
  target: AppealTarget;
};

/** techspec-builder-common.md §5.1 — 발행 거부 화면의 "이의제기" 버튼(US-098)과 조치 통지(US-055)
 * 두 진입점이 target만 다르게 넘겨 공유하는 react-call 모달. UpdateInfoModal과 동일하게 자체
 * mutation을 직접 호출하는 완결형 컴포넌트다(호출부마다 달라질 후속 동작이 없어 ReportContentModal의
 * caller-supplied mutationFn 패턴은 불필요).
 *
 * 빈 사유는 버튼 비활성이 아니라 zod가 막고 사유를 화면에 남긴다(`apps/web/CLAUDE.md` 폼 규약).
 * 접수 중 비활성은 `disabled`가 아니라 `aria-disabled`다 — `disabled`면 누르는 즉시 브라우저가
 * blur해 키보드 사용자의 포커스가 `<body>`로 떨어진다(`ContentListLoadMore` 선례). */
export const AppealModal = createCallable<AppealModalProps, void>(({ call, target }) => {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SubmitAppealFormValues>({
    resolver: zodResolver(submitAppealSchema),
    defaultValues: { reasonText: "" },
  });

  const submitAppeal = useSubmitAppealMutation();

  async function onSubmit(values: SubmitAppealFormValues) {
    if (isSubmitting) return;

    try {
      await submitAppeal.mutateAsync({ target, reasonText: values.reasonText });
      toast.success("이의제기가 접수되었어요. 검토 후 결과를 안내해드릴게요.");
      call.end();
    } catch {
      toast.error("이의제기 접수에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>이의제기</DialogTitle>
          <DialogDescription>이의제기 사유를 자유롭게 작성해주세요.</DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit(onSubmit)(event);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Textarea
              placeholder="이의제기 사유를 입력해주세요."
              rows={5}
              aria-label="이의제기 사유"
              aria-invalid={!!errors.reasonText}
              aria-describedby={errors.reasonText ? "appeal-reason-error" : undefined}
              {...register("reasonText")}
            />
            {errors.reasonText && (
              <p id="appeal-reason-error" role="alert" className="text-xs text-destructive-text">
                {errors.reasonText.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="submit"
              className="w-full aria-disabled:pointer-events-none aria-disabled:opacity-65"
              aria-disabled={isSubmitting}
            >
              {isSubmitting ? "접수 중..." : "이의제기 접수"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});
