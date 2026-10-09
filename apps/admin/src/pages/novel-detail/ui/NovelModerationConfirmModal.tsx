import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useNovelModerationMutation, type NovelModerationAction } from "@/entities/admin-novel";
import { isReportReasonCategory, REPORT_REASON_OPTIONS, REPORT_REASON_VALUES } from "@/entities/report";
import { apiErrorCode } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

const ACTION_TITLE: Record<NovelModerationAction, string> = {
  restrict: "노벨 이용제한",
  lift: "노벨 이용제한 해제",
};

const ACTION_EFFECT: Record<NovelModerationAction, string> = {
  restrict:
    "을(를) 이용제한합니다. 노벨 목록·홈에서 바로 빠지고, 구매한 독자도 열람이 끝나요. 해제하면 소장한 화가 다시 열려요. 게시자에게 알림은 가지 않아요.",
  lift: "의 이용제한을 해제합니다. 다른 이유(공개 거둠·원작 숨김 등)가 없으면 독자에게 다시 보이고, 구매한 독자의 소장도 다시 열려요.",
};

const SUCCESS_MESSAGE: Record<NovelModerationAction, string> = {
  restrict: "노벨을 이용제한했어요.",
  lift: "노벨 이용제한을 해제했어요.",
};

/** 이미 그 상태라는 409 — 다른 운영자가 먼저 바꿨다. 고칠 입력이 없어 모달을 닫고, 상세는 새로 읽힌다. */
const REJECTION_MESSAGES: Record<string, string> = {
  NOVEL_ALREADY_RESTRICTED: "이미 이용제한된 노벨이에요. 화면을 새로 불러왔어요.",
  NOVEL_NOT_RESTRICTED: "이미 이용제한이 풀린 노벨이에요. 화면을 새로 불러왔어요.",
  NOVEL_NOT_FOUND: "노벨을 찾을 수 없어요. 게시자가 지웠을 수 있어요.",
};

const ERROR_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

/** 사유 분류는 고를 때만 감사 로그에 남는다(서버 선택 값). 해제에는 분류를 받지 않는다. */
const moderationSchema = z.object({
  reasonCategory: z.enum(REPORT_REASON_VALUES).optional(),
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});

type ModerationFormValues = z.infer<typeof moderationSchema>;

type NovelModerationConfirmModalProps = {
  novelId: string;
  novelTitle: string;
  action: NovelModerationAction;
  /** 조치가 성공해 모달이 닫힌 뒤 부른다 — 상세 레이아웃이 하단 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 노벨 이용제한·해제 확인. 사유는 감사 로그에 남아 둘 다 필수다(서버도 공백뿐이면 422). */
export const NovelModerationConfirmModal = createCallable<NovelModerationConfirmModalProps, void>(
  ({ call, novelId, novelTitle, action, onSuccess }) => {
    const moderationMutation = useNovelModerationMutation(novelId);
    const {
      control,
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<ModerationFormValues>({
      resolver: zodResolver(moderationSchema),
      defaultValues: { reasonCategory: undefined, adminComment: "" },
    });
    const isRestrict = action === "restrict";

    const onSubmit = async (values: ModerationFormValues) => {
      try {
        await moderationMutation.mutateAsync({
          action,
          adminComment: values.adminComment,
          reasonCategory: isRestrict ? values.reasonCategory : undefined,
        });
        toast.success(SUCCESS_MESSAGE[action]);
        call.end();
        onSuccess?.();
      } catch (error) {
        const code = apiErrorCode(error);
        const rejection = code === null ? undefined : REJECTION_MESSAGES[code];
        toast.error(rejection ?? ERROR_MESSAGE);
        if (rejection) call.end();
      }
    };

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>{ACTION_TITLE[action]}</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{novelTitle}</span>
              {ACTION_EFFECT[action]}
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
            {isRestrict && (
              <div className="flex flex-col gap-1.5">
                <Label id="novel-moderation-reason-category-label">사유 분류 (선택)</Label>
                <Controller
                  name="reasonCategory"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value ?? ""}
                      onValueChange={(value) => field.onChange(isReportReasonCategory(value) ? value : undefined)}
                    >
                      <SelectTrigger className="w-full" aria-labelledby="novel-moderation-reason-category-label">
                        <SelectValue placeholder="분류를 고르세요" />
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
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="novel-moderation-comment">조치 사유 (필수)</Label>
              <Textarea
                id="novel-moderation-comment"
                placeholder={isRestrict ? "이용제한 사유 — 감사 로그에 남아요" : "해제 사유 — 감사 로그에 남아요"}
                rows={3}
                aria-invalid={!!errors.adminComment}
                aria-describedby={errors.adminComment ? "novel-moderation-comment-error" : undefined}
                {...register("adminComment")}
              />
              {errors.adminComment && (
                <p id="novel-moderation-comment-error" role="alert" className="text-xs text-destructive-text">
                  {errors.adminComment.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
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
