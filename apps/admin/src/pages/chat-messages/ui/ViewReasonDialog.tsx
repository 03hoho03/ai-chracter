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

import {
  CHAT_VIEW_REASON_CATEGORY_OPTIONS,
  CHAT_VIEW_REASON_CATEGORY_VALUES,
  isChatViewReasonCategory,
  type ChatViewReasonCategory,
} from "@/entities/admin-user";
import { isApiError } from "@/shared/lib/api/client";

import { useViewChatMutation, type AdminChatMessagesResponse } from "../api/useViewChatMutation";

/** 카테고리 필수·사유 텍스트 trim 후 비어있으면 안 됨 — 이 규칙은 컴포넌트가 아니라 여기 한 곳에
 * 둔다(UserActionConfirmModal의 스키마와 동형). 비면 서버로 요청이 나가기 전에 필드 에러로 잡는다
 * (BE도 422로 막지만 FE에서 먼저). */
const viewReasonSchema = z
  .object({
    reasonCategory: z.enum(CHAT_VIEW_REASON_CATEGORY_VALUES).optional(),
    reasonText: z.string(),
  })
  .superRefine((values, ctx) => {
    if (!values.reasonCategory) {
      ctx.addIssue({ code: "custom", path: ["reasonCategory"], message: "사유 카테고리를 선택해주세요." });
    }
    if (values.reasonText.trim().length === 0) {
      ctx.addIssue({ code: "custom", path: ["reasonText"], message: "열람이 필요한 이유를 입력해주세요." });
    }
  });

type ViewReasonFormValues = z.infer<typeof viewReasonSchema>;

type ViewReasonDialogProps = {
  roomId: string;
  onCancel: () => void;
  onConfirmed: (data: AdminChatMessagesResponse) => void;
};

/** 이 화면의 진입 게이트 다이얼로그 — `__root.tsx`에 콜러블로 마운트하지 않고 페이지 안에
 * 직접 둔다(techspec §5-6). 사유를 라우터 state나 전역 콜러블로 넘기면 새로고침 시 사라져
 * 빈 화면이 되지만, 이 컴포넌트는 `ChatMessagesPage`가 `viewResult`를 아직 못 받은 동안 항상
 * 그 자리에서 다시 렌더되므로 새로고침해도 다이얼로그가 다시 뜬다. */
export function ViewReasonDialog({ roomId, onCancel, onConfirmed }: ViewReasonDialogProps) {
  const viewMutation = useViewChatMutation(roomId);
  const {
    control,
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ViewReasonFormValues>({
    resolver: zodResolver(viewReasonSchema),
    defaultValues: { reasonCategory: undefined, reasonText: "" },
  });

  const onSubmit = async (values: ViewReasonFormValues) => {
    if (!values.reasonCategory) return;

    try {
      const data = await viewMutation.mutateAsync(formToViewRequest(values, values.reasonCategory));
      onConfirmed(data);
    } catch (error) {
      if (isApiError(error) && error.status === 404) {
        toast.error("존재하지 않는 채팅방이에요.");
        onCancel();
        return;
      }
      toast.error("열람 처리에 실패했어요. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>채팅 열람 사유</DialogTitle>
          <DialogDescription className="break-keep">
            이 대화를 보려면 사유가 필요해요. 열람 기록이 남습니다.
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
          <div className="flex flex-col gap-1.5">
            <Label>사유 카테고리</Label>
            <Controller
              name="reasonCategory"
              control={control}
              render={({ field }) => (
                <Select
                  value={field.value ?? ""}
                  onValueChange={(value) => field.onChange(isChatViewReasonCategory(value) ? value : undefined)}
                >
                  <SelectTrigger
                    className="w-full"
                    aria-label="사유 카테고리"
                    aria-invalid={!!errors.reasonCategory}
                    aria-describedby={errors.reasonCategory ? "view-reason-category-error" : undefined}
                  >
                    <SelectValue placeholder="사유를 선택하세요" />
                  </SelectTrigger>
                  <SelectContent>
                    {CHAT_VIEW_REASON_CATEGORY_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.reasonCategory && (
              <p id="view-reason-category-error" role="alert" className="text-xs text-destructive-text">
                {errors.reasonCategory.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="view-reason-text">사유 상세 (필수)</Label>
            <Textarea
              id="view-reason-text"
              placeholder="열람이 필요한 이유를 입력하세요"
              rows={3}
              aria-invalid={!!errors.reasonText}
              aria-describedby={errors.reasonText ? "view-reason-text-error" : undefined}
              {...register("reasonText")}
            />
            {errors.reasonText && (
              <p id="view-reason-text-error" role="alert" className="text-xs text-destructive-text">
                {errors.reasonText.message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCancel}>
              취소
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "처리 중..." : "확인"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** 카테고리 존재는 스키마가 보장한 뒤에만 호출된다(UserActionConfirmModal의 formToReasonedRequest와
 * 동형). trim은 검증(superRefine)과 요청 본문 양쪽에 같은 규칙으로 적용된다. */
function formToViewRequest(values: ViewReasonFormValues, reasonCategory: ChatViewReasonCategory) {
  return { reasonCategory, reasonText: values.reasonText.trim() };
}
