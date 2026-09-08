import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { createCallable } from "react-call";
import { useMutationFlow, type MutationFn } from "react-call/mutation-flow";
import { Controller, useForm } from "react-hook-form";

import type { ReportReasonCategory } from "@/entities/content";

import {
  REPORT_REASON_OPTIONS,
  reportContentSchema,
  type ReportContentFormValues,
} from "../model/schema";

type ReportContentModalProps = {
  mutationFn: MutationFn<void, ReportReasonCategory>;
};

/** techspec-content-detail.md §5, techspec-overview.md §9 — 이 프로젝트 첫 react-call 액션형 모달.
 * 실제 신고 API 호출/토스트/성공 판단은 호출부가 넘기는 mutationFn이 담당하고, 이 컴포넌트는
 * 사유 단일 선택 UI + 제출 상태 표시만 책임진다.
 *
 * Radix 단일선택 토글은 선택된 항목을 다시 누르면 **빈 문자열**을 흘려보내고 `ToggleGroupItem`의
 * value도 `string`이라 폼에 그대로 넣을 수 없다 — `Controller`가 되받아 목록에 있는 값만 통과시키고,
 * 미선택 제출은 `as` 단언이나 버튼 비활성이 아니라 zod가 막고 사유를 화면에 남긴다. */
export const ReportContentModal = createCallable<ReportContentModalProps, void>(({ call, mutationFn }) => {
  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<ReportContentFormValues>({
    resolver: zodResolver(reportContentSchema),
  });

  const submit = useMutationFlow(call, mutationFn);

  function onSubmit(values: ReportContentFormValues) {
    if (submit.pending) return;
    submit(values.reason);
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>신고하기</DialogTitle>
          <DialogDescription>신고 사유를 선택해주세요.</DialogDescription>
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
            <Controller
              control={control}
              name="reason"
              render={({ field }) => (
                <ToggleGroup
                  type="single"
                  variant="list"
                  orientation="vertical"
                  value={field.value ?? ""}
                  onValueChange={(value) => field.onChange(isReportReason(value) ? value : undefined)}
                  aria-label="신고 사유 선택"
                  aria-invalid={!!errors.reason}
                  aria-describedby={errors.reason ? "report-reason-error" : undefined}
                  className="w-full"
                >
                  {REPORT_REASON_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value} className="h-11 w-full justify-start px-3">
                      {option.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              )}
            />
            {errors.reason && (
              <p id="report-reason-error" role="alert" className="text-xs text-destructive-text">
                {errors.reason.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button
              type="submit"
              className="w-full aria-disabled:pointer-events-none aria-disabled:opacity-65"
              aria-disabled={submit.pending}
            >
              {submit.pending ? "접수 중..." : "신고하기"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});

/** `ToggleGroupItem`의 value가 `string`이라 좁힘이 필요하다. `as` 단언 대신 술어를 쓴다(TS-03). */
function isReportReason(value: string): value is ReportReasonCategory {
  return REPORT_REASON_OPTIONS.some((option) => option.value === value);
}
