import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { createCallable } from "react-call";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { adminContentKeys, type ContentActionReasonCategory } from "@/entities/admin-content";
import { useSuspendUserMutation, useUnsuspendUserMutation, useWarnUserMutation } from "@/entities/admin-user";
import { isReportReasonCategory, REPORT_REASON_OPTIONS, REPORT_REASON_VALUES } from "@/entities/report";

type UserActionType = "warn" | "suspend" | "unsuspend";

const ACTION_TITLE: Record<UserActionType, string> = {
  warn: "경고",
  suspend: "정지",
  unsuspend: "정지 해제",
};

const ERROR_MESSAGE = "처리에 실패했어요. 잠시 후 다시 시도해주세요.";

const userActionSchema = z.object({
  reasonCategory: z.enum(REPORT_REASON_VALUES).optional(),
  adminComment: z.string(),
});

type UserActionFormValues = z.infer<typeof userActionSchema>;

type UserActionConfirmModalProps = {
  userId: string;
  action: UserActionType;
  restrictableContentCount: number;
};

/** ContentActionConfirmModal과 같은 결 — `warn`/`suspend`는 사유 카테고리가 필수다. `unsuspend`는
 * `Notification`을 만들지 않아 사유 카테고리를 고를 근거가 없다 — 대신 관리자 코멘트가 필수다
 * (비어 있으면 API가 422). 콘텐츠명 정확 입력 같은 강한 확인은 넣지 않는다 — 정지·해제는 멱등이고
 * 가역이다(2단계가 그 확인을 되돌릴 수 없는 삭제에만 썼다). `suspend`는 실제로 이용제한으로 전환될
 * 작품 개수(상세 응답의 `restrictableContentCount` — 이미 restricted/deleted인 작품은 제외한 값)를
 * 미리 보여주고, 성공 시 응답의 `restrictedContentCount`로 실제 내려간 개수를 toast에 담는다.
 * 두 값은 항상 일치해야 정지 확인의 예고가 사실과 맞는다. */
export const UserActionConfirmModal = createCallable<UserActionConfirmModalProps, void>(
  ({ call, userId, action, restrictableContentCount }) => {
    const queryClient = useQueryClient();
    const warnMutation = useWarnUserMutation(userId);
    const suspendMutation = useSuspendUserMutation(userId);
    const unsuspendMutation = useUnsuspendUserMutation(userId);
    const {
      control,
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<UserActionFormValues>({
      resolver: zodResolver(createUserActionSchema(action)),
      defaultValues: { reasonCategory: undefined, adminComment: "" },
    });

    const isReasonCategoryRequired = action !== "unsuspend";

    const onSubmit = async (values: UserActionFormValues) => {
      try {
        if (action === "warn") {
          if (!values.reasonCategory) return;
          await warnMutation.mutateAsync(formToReasonedRequest(values, values.reasonCategory));
          toast.success("경고를 부과했어요.");
        } else if (action === "suspend") {
          if (!values.reasonCategory) return;
          const result = await suspendMutation.mutateAsync(formToReasonedRequest(values, values.reasonCategory));
          toast.success(`정지했어요. 작품 ${result.restrictedContentCount}건이 이용제한으로 전환됐어요.`);
        } else if (action === "unsuspend") {
          await unsuspendMutation.mutateAsync(formToUnsuspendRequest(values));
          toast.success("정지를 해제했어요.");
        } else {
          assertNever(action);
        }
        // 세 조치 모두 작품 상태를 바꿀 수 있다 — 유저 쿼리는 각 뮤테이션이 끊고, 작품 쿼리는
        // entity끼리 물리지 않도록 여기서 끊는다.
        void queryClient.invalidateQueries({ queryKey: adminContentKeys.all });
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
              {action === "warn" && "이 유저에게 경고를 부과합니다."}
              {action === "suspend" &&
                (restrictableContentCount > 0
                  ? `이 유저를 정지합니다. 작품 ${restrictableContentCount}건이 함께 이용제한으로 전환됩니다.`
                  : "이 유저를 정지합니다.")}
              {action === "unsuspend" && "이 유저의 정지를 해제합니다. 작품은 이용제한 상태로 남습니다."}
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
                        aria-describedby={errors.reasonCategory ? "user-action-reason-error" : undefined}
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
                  <p id="user-action-reason-error" role="alert" className="text-xs text-destructive-text">
                    {errors.reasonCategory.message}
                  </p>
                )}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="user-action-comment">
                관리자 코멘트 {isReasonCategoryRequired ? "(선택)" : "(필수)"}
              </Label>
              <Textarea
                id="user-action-comment"
                placeholder={isReasonCategoryRequired ? "유저에게 전달할 코멘트" : "해제 사유를 입력하세요"}
                rows={3}
                aria-invalid={!!errors.adminComment}
                aria-describedby={errors.adminComment ? "user-action-comment-error" : undefined}
                {...register("adminComment")}
              />
              {errors.adminComment && (
                <p id="user-action-comment-error" role="alert" className="text-xs text-destructive-text">
                  {errors.adminComment.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : "조치 확정"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);

/** warn·suspend는 사유 카테고리가 필수다 — 스키마가 그걸 보장한 뒤에만 호출된다. */
function formToReasonedRequest(values: UserActionFormValues, reasonCategory: ContentActionReasonCategory) {
  return { reasonCategory, adminComment: values.adminComment.trim() || undefined };
}

/** unsuspend는 사유 카테고리를 받지 않고 코멘트가 필수다(빈 값이면 BE가 422). */
function formToUnsuspendRequest(values: UserActionFormValues) {
  return { adminComment: values.adminComment.trim() };
}

/** 조치별로 필수 필드가 갈린다 — 그 규칙을 컴포넌트가 아니라 스키마 한 곳에 둔다. */
function createUserActionSchema(action: UserActionType) {
  return userActionSchema.superRefine((values, ctx) => {
    if (action === "unsuspend") {
      if (values.adminComment.trim().length === 0) {
        ctx.addIssue({ code: "custom", path: ["adminComment"], message: "해제 사유를 입력해주세요." });
      }
    } else if (!values.reasonCategory) {
      ctx.addIssue({ code: "custom", path: ["reasonCategory"], message: "사유 카테고리를 선택해주세요." });
    }
  });
}

function assertNever(value: never): never {
  throw new Error(`Unexpected: ${String(value)}`);
}
