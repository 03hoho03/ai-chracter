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
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useNovelReviewMutation, type NovelReviewAction } from "@/entities/admin-novel";
import { apiErrorCode } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

/** 두 처리의 문구. 글이 누구에게 보이는지가 갈리는 핵심이라 안내 줄에 늘 적는다 — 반려 사유는 게시자 화면에 그대로 실린다. */
const COPY: Record<
  NovelReviewAction,
  { title: string; effect: string; label: string; hint: string; placeholder: string; confirm: string; done: string }
> = {
  approve: {
    title: "첫 공개 승인",
    effect: "의 첫 공개를 승인합니다. 바로 노벨에 열려 독자가 1화를 읽을 수 있고, 게시자는 다음 화부터 승인 없이 공개할 수 있어요.",
    label: "메모 (선택)",
    hint: "감사 로그에만 남고 게시자에게는 보이지 않아요.",
    placeholder: "운영 메모",
    confirm: "승인 확정",
    done: "첫 공개를 승인했어요.",
  },
  reject: {
    title: "첫 공개 반려",
    effect: "의 첫 공개를 반려합니다. 신청한 1화 공개본이 지워지고, 게시자는 고친 뒤 다시 신청할 수 있어요.",
    label: "반려 사유 (필수)",
    hint: "게시자 화면에 이 사유가 그대로 보여요. 무엇을 고치면 다시 신청할 수 있는지 적어주세요.",
    placeholder: "게시자에게 보일 반려 사유",
    confirm: "반려 확정",
    done: "첫 공개를 반려했어요.",
  },
};

/** 고칠 입력이 없는 409·404 — 다른 운영자가 먼저 처리했거나, 게시자가 신청을 취소했거나, 승인할 수 없는 상태가 됐다.
 * 토스트를 띄우고 모달을 닫으며, 상세는 무효화로 새로 읽힌다. */
const REJECTION_MESSAGES: Record<string, string> = {
  NOVEL_REVIEW_NOT_PENDING: "이미 처리됐거나 게시자가 신청을 취소했어요. 화면을 새로 불러왔어요.",
  NOVEL_REVIEW_NO_FIRST_CHAPTER: "1화 공개본이 없어 승인할 수 없어요. 반려로 정리해 주세요.",
  NOVEL_SOURCE_NOT_PUBLISHABLE: "원작이 지금 공개할 수 없는 상태라 승인할 수 없어요. 반려로 정리해 주세요.",
  NOVEL_NOT_FOUND: "노벨을 찾을 수 없어요. 게시자가 지웠을 수 있어요.",
};

const ERROR_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

// 서버도 반려 사유가 공백뿐이면 422 로 거부한다 — 같은 규칙을 먼저 건다. 승인 메모는 비워도 된다.
const rejectSchema = z.object({ comment: z.string().trim().min(1, "반려 사유를 입력해주세요.") });
const approveSchema = z.object({ comment: z.string().trim() });

type ReviewFormValues = z.infer<typeof rejectSchema>;

type NovelReviewConfirmModalProps = {
  novelId: string;
  novelTitle: string;
  action: NovelReviewAction;
  /** 처리가 성공해 모달이 닫힌 뒤 부른다 — 상세 레이아웃이 하단 시트를 닫는다. */
  onSuccess?: () => void;
};

/** 첫 공개 승인·반려 확인. 한 번짜리 처리라 한 모달이 문구만 바꿔 맡는다.
 *
 * 요청 중에는 Esc·바깥 누르기·닫기(X)·취소로 닫지 않는다 — 닫은 뒤 실패하면 그 오류를 보일 자리가 없고, 닫힌 모달을 보고
 * 처리가 안 됐다고 여겨 다시 누르게 된다. */
export const NovelReviewConfirmModal = createCallable<NovelReviewConfirmModalProps, void>(
  ({ call, novelId, novelTitle, action, onSuccess }) => {
    const reviewMutation = useNovelReviewMutation(novelId);
    const [failureMessage, setFailureMessage] = useState<string | null>(null);
    const copy = COPY[action];
    const {
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<ReviewFormValues>({
      resolver: zodResolver(action === "reject" ? rejectSchema : approveSchema),
      defaultValues: { comment: "" },
    });

    const onSubmit = async (values: ReviewFormValues) => {
      setFailureMessage(null);
      try {
        await reviewMutation.mutateAsync({ action, adminComment: values.comment });
        toast.success(copy.done);
        call.end();
        onSuccess?.();
      } catch (error) {
        const code = apiErrorCode(error);
        const rejection = code === null ? undefined : REJECTION_MESSAGES[code];
        if (rejection) {
          toast.error(rejection);
          call.end();
          return;
        }
        setFailureMessage(ERROR_MESSAGE);
      }
    };

    const commentDescribedBy = ["novel-review-hint", errors.comment && "novel-review-error"].filter(Boolean).join(" ");

    return (
      <Dialog open={!call.ended} onOpenChange={(open) => !open && !isSubmitting && call.end()}>
        <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusInitialElement}>
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription className="break-keep">
              <span className="font-medium text-foreground">{novelTitle}</span>
              {copy.effect}
            </DialogDescription>
          </DialogHeader>

          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex min-h-0 flex-1 flex-col gap-4"
          >
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="novel-review-comment">{copy.label}</Label>
                <p id="novel-review-hint" className="text-xs break-keep text-muted-foreground">
                  {copy.hint}
                </p>
                <Textarea
                  id="novel-review-comment"
                  rows={4}
                  placeholder={copy.placeholder}
                  aria-invalid={!!errors.comment}
                  aria-describedby={commentDescribedBy}
                  {...register("comment")}
                />
                {errors.comment && (
                  <p id="novel-review-error" role="alert" className="text-xs text-destructive-text">
                    {errors.comment.message}
                  </p>
                )}
              </div>

              {failureMessage && (
                <p role="alert" className="text-sm break-keep text-destructive-text">
                  {failureMessage}
                </p>
              )}
            </DialogBody>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                autoFocus
                data-initial-focus
                disabled={isSubmitting}
                onClick={() => call.end()}
              >
                취소
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : copy.confirm}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
