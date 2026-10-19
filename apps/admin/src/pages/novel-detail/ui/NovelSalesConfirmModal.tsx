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
import { useQueryClient } from "@tanstack/react-query";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  isNovelSalesStopDisabled,
  NOVEL_SALES_STOP_DISABLED_MESSAGE,
  useNovelSalesMutation,
  type NovelSalesAction,
} from "@/entities/admin-novel";
import { isReportReasonCategory, REPORT_REASON_OPTIONS, REPORT_REASON_VALUES } from "@/entities/report";
import { sessionKeys } from "@/entities/session";
import { apiErrorCode } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

const ACTION_TITLE: Record<NovelSalesAction, string> = {
  stop: "노벨 판매 중단",
  resume: "노벨 판매 재개",
};

/** 판매 중단은 정책 스위치가 켜져 있을 때만 걸고 풀 수 있어 켜짐 문장 하나뿐이다. 이용제한과 따로 걸리고 따로 풀린다. */
const ACTION_EFFECT: Record<NovelSalesAction, string> = {
  stop: "의 판매를 멈춥니다. 노벨 목록·홈에서 빠지고 새로 팔지 않아요. 산 회원은 계속 읽고 환급은 없어요. 게시자는 새 화·다시 공개를 낼 수 없어요. 게시자에게 알림은 가지 않아요.",
  resume:
    "의 판매를 다시 엽니다. 다른 이유(이용제한·공개 거둠·원작 숨김 등)가 없으면 독자 목록에 다시 보이고, 게시자도 새 화·다시 공개를 낼 수 있어요.",
};

const SUCCESS_MESSAGE: Record<NovelSalesAction, string> = {
  stop: "노벨 판매를 멈췄어요.",
  resume: "노벨 판매를 다시 열었어요.",
};

/** 이미 그 상태라는 409 — 다른 운영자가 먼저 바꿨다. 고칠 입력이 없어 모달을 닫고, 상세는 새로 읽힌다. */
const REJECTION_MESSAGES: Record<string, string> = {
  NOVEL_SALES_ALREADY_STOPPED: "이미 판매가 멈춘 노벨이에요. 화면을 새로 불러왔어요.",
  NOVEL_SALES_NOT_STOPPED: "이미 판매 중인 노벨이에요. 화면을 새로 불러왔어요.",
  NOVEL_NOT_FOUND: "노벨을 찾을 수 없어요. 게시자가 지웠을 수 있어요.",
};

const ERROR_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

/** 사유 분류는 고를 때만 감사 로그에 남는다(서버 선택 값). 재개에는 분류를 받지 않는다. */
const salesSchema = z.object({
  reasonCategory: z.enum(REPORT_REASON_VALUES).optional(),
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});

type SalesFormValues = z.infer<typeof salesSchema>;

type NovelSalesConfirmModalProps = {
  novelId: string;
  novelTitle: string;
  action: NovelSalesAction;
  /** 조치가 성공해 모달이 닫힌 뒤 부른다 — 상세 레이아웃이 하단 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 노벨 판매 중단·재개 확인. 사유는 감사 로그에 남아 둘 다 필수다(서버도 공백뿐이면 422). */
export const NovelSalesConfirmModal = createCallable<NovelSalesConfirmModalProps, void>(
  ({ call, novelId, novelTitle, action, onSuccess }) => {
    const salesMutation = useNovelSalesMutation(novelId);
    const queryClient = useQueryClient();
    const {
      control,
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<SalesFormValues>({
      resolver: zodResolver(salesSchema),
      defaultValues: { reasonCategory: undefined, adminComment: "" },
    });
    const isStop = action === "stop";

    const onSubmit = async (values: SalesFormValues) => {
      try {
        await salesMutation.mutateAsync({
          action,
          adminComment: values.adminComment,
          reasonCategory: isStop ? values.reasonCategory : undefined,
        });
        toast.success(SUCCESS_MESSAGE[action]);
        call.end();
        onSuccess?.();
      } catch (error) {
        // 그사이 정책 스위치가 꺼졌다 — 세션은 한 번 받으면 다시 받지 않아, 새로 받아야 조치 열이 꺼짐 화면으로 바뀐다.
        if (isNovelSalesStopDisabled(error)) {
          toast.error(NOVEL_SALES_STOP_DISABLED_MESSAGE.novel);
          call.end();
          void queryClient.invalidateQueries({ queryKey: sessionKeys.all });
          return;
        }
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
            {isStop && (
              <div className="flex flex-col gap-1.5">
                <Label id="novel-sales-reason-category-label">사유 분류 (선택)</Label>
                <Controller
                  name="reasonCategory"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value ?? ""}
                      onValueChange={(value) => field.onChange(isReportReasonCategory(value) ? value : undefined)}
                    >
                      <SelectTrigger className="w-full" aria-labelledby="novel-sales-reason-category-label">
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
              <Label htmlFor="novel-sales-comment">조치 사유 (필수)</Label>
              <Textarea
                id="novel-sales-comment"
                placeholder={isStop ? "판매 중단 사유 — 감사 로그에 남아요" : "재개 사유 — 감사 로그에 남아요"}
                rows={3}
                aria-invalid={!!errors.adminComment}
                aria-describedby={errors.adminComment ? "novel-sales-comment-error" : undefined}
                {...register("adminComment")}
              />
              {errors.adminComment && (
                <p id="novel-sales-comment-error" role="alert" className="text-xs text-destructive-text">
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
