import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { createCallable } from "react-call";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useContentActionMutation, type AdminContentActionType } from "@/entities/admin-content";
import { isReportReasonCategory, REPORT_REASON_OPTIONS, REPORT_REASON_VALUES } from "@/entities/report";

const ACTION_TITLE: Record<AdminContentActionType, string> = {
  restrict: "이용제한 부과",
  delete: "삭제",
  "lift-restriction": "이용제한 해제",
  reject: "반려",
};

const ACTION_EFFECT: Record<AdminContentActionType, string> = {
  restrict: "이용제한을 부과합니다. 작품이 즉시 비공개로 전환되고 제작자에게 알림이 갑니다.",
  delete: "삭제합니다. 이 작업은 되돌릴 수 없으며 제작자에게 알림이 갑니다.",
  "lift-restriction": "이용제한을 해제합니다. 작품이 원래 공개범위로 되돌아갑니다.",
  reject: "",
};

const SUCCESS_MESSAGE: Record<AdminContentActionType, string> = {
  restrict: "이용제한을 부과했어요.",
  delete: "삭제 처리했어요.",
  "lift-restriction": "이용제한을 해제했어요.",
  reject: "",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

type ContentConfirmAction = Extract<AdminContentActionType, "restrict" | "delete" | "lift-restriction">;

const contentActionSchema = z.object({
  reasonCategory: z.enum(REPORT_REASON_VALUES).optional(),
  adminComment: z.string(),
  confirmText: z.string(),
});

type ContentActionFormValues = z.infer<typeof contentActionSchema>;

type ContentActionConfirmModalProps = {
  contentId: string;
  contentName: string;
  action: ContentConfirmAction;
};

/** goal-prompt.md 2단계 T-10 — 조치 확인 다이얼로그. `restrict`/`delete`는 사유 카테고리가
 * 필수다(API도 `reasonCategory` 누락 시 422를 낸다). `lift-restriction`은 `Notification`을 만들지
 * 않아 사유 카테고리를 고를 근거가 없다 — 대신 관리자 코멘트가 필수다(비어 있으면 API가 422).
 * 삭제는 기존 `DeleteConfirmModal`(features/act-on-report)의 콘텐츠명 정확 입력 패턴을 그대로
 * 재사용해 이 다이얼로그 안에 인라인으로 뒀다 — 사유 선택까지 한 다이얼로그에서 끝내려면 별도
 * 모달을 이어붙이는 것보다 패턴만 재사용하는 쪽이 사용자에게 확인 단계가 하나로 보인다.
 * 조치별로 갈리는 이 세 규칙의 단일 소스는 `createContentActionSchema`다. */
export const ContentActionConfirmModal = createCallable<ContentActionConfirmModalProps, void>(
  ({ call, contentId, contentName, action }) => {
    const actionMutation = useContentActionMutation(contentId);
    const {
      control,
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<ContentActionFormValues>({
      resolver: zodResolver(createContentActionSchema(action, contentName)),
      defaultValues: { reasonCategory: undefined, adminComment: "", confirmText: "" },
    });

    const isReasonCategoryRequired = action !== "lift-restriction";
    const isNameMatchRequired = action === "delete";

    const onSubmit = async (values: ContentActionFormValues) => {
      try {
        await actionMutation.mutateAsync(formToServer(values, action));
        toast.success(SUCCESS_MESSAGE[action]);
        call.end();
      } catch {
        toast.error(ERROR_MESSAGE);
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{ACTION_TITLE[action]}</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{contentName}</span>에 대해 {ACTION_EFFECT[action]}
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex flex-col gap-3"
          >
            {isReasonCategoryRequired && (
              <div className="flex flex-col gap-1.5">
                <Label>사유 카테고리</Label>
                <Controller
                  name="reasonCategory"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value ?? ""}
                      onValueChange={(value) => field.onChange(isReportReasonCategory(value) ? value : undefined)}
                    >
                      <SelectTrigger
                        className="w-full"
                        aria-label="사유 카테고리"
                        aria-invalid={!!errors.reasonCategory}
                        aria-describedby={errors.reasonCategory ? "content-action-reason-error" : undefined}
                      >
                        <SelectValue placeholder="사유를 선택하세요" />
                      </SelectTrigger>
                      <SelectContent>
                        {REPORT_REASON_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
                {errors.reasonCategory && (
                  <p id="content-action-reason-error" role="alert" className="text-xs text-destructive-text">
                    {errors.reasonCategory.message}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="content-action-comment">
                관리자 코멘트 {isReasonCategoryRequired ? "(선택)" : "(필수)"}
              </Label>
              <Textarea
                id="content-action-comment"
                placeholder={isReasonCategoryRequired ? "제작자에게 전달할 코멘트" : "해제 사유를 입력하세요"}
                rows={3}
                aria-invalid={!!errors.adminComment}
                aria-describedby={errors.adminComment ? "content-action-comment-error" : undefined}
                {...register("adminComment")}
              />
              {errors.adminComment && (
                <p id="content-action-comment-error" role="alert" className="text-xs text-destructive-text">
                  {errors.adminComment.message}
                </p>
              )}
            </div>

            {isNameMatchRequired && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="content-action-confirm-text">
                  삭제를 확정하려면 작품명 <span className="font-medium text-foreground">{contentName}</span>을(를)
                  정확히 입력하세요
                </Label>
                <Input
                  id="content-action-confirm-text"
                  placeholder={contentName}
                  autoFocus
                  aria-invalid={!!errors.confirmText}
                  aria-describedby={errors.confirmText ? "content-action-confirm-text-error" : undefined}
                  {...register("confirmText")}
                />
                {errors.confirmText && (
                  <p id="content-action-confirm-text-error" role="alert" className="text-xs text-destructive-text">
                    {errors.confirmText.message}
                  </p>
                )}
              </div>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" variant={action === "delete" ? "destructive" : "default"} disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : "조치 확정"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

/** `confirmText`는 확인 전용 폼 필드라 서버로 넘어가지 않는다. `lift-restriction`은 사유 카테고리를
 * 받지 않는다(알림을 만들지 않아 고를 근거가 없다). */
function formToServer(values: ContentActionFormValues, action: ContentConfirmAction) {
  return {
    action,
    reasonCategory: action === "lift-restriction" ? undefined : values.reasonCategory,
    adminComment: values.adminComment.trim() || undefined,
  };
}

/** 조치별로 필수 필드가 갈린다 — 그 규칙을 컴포넌트가 아니라 스키마 한 곳에 둔다. */
function createContentActionSchema(action: ContentConfirmAction, contentName: string) {
  return contentActionSchema.superRefine((values, ctx) => {
    if (action === "lift-restriction") {
      if (values.adminComment.trim().length === 0) {
        ctx.addIssue({ code: "custom", path: ["adminComment"], message: "해제 사유를 입력해주세요." });
      }
    } else if (!values.reasonCategory) {
      ctx.addIssue({ code: "custom", path: ["reasonCategory"], message: "사유 카테고리를 선택해주세요." });
    }

    if (action === "delete" && values.confirmText.trim() !== contentName) {
      ctx.addIssue({ code: "custom", path: ["confirmText"], message: "작품명을 정확히 입력해주세요." });
    }
  });
}
