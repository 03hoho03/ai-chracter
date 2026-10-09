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
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { useNovelCommentActionMutation, type AdminNovelComment, type NovelCommentAction } from "@/entities/admin-novel";
import { apiErrorCode } from "@/shared/lib/api/client";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { focusInitialElement } from "@/shared/lib/callable/focusInitialElement";

const ACTION_TITLE: Record<NovelCommentAction, string> = {
  hide: "댓글 숨김",
  restore: "댓글 숨김 해제",
  delete: "댓글 삭제",
};

const ACTION_EFFECT: Record<NovelCommentAction, string> = {
  hide: "독자 댓글 목록에서 빠져요. 본문은 남아 있어 나중에 숨김을 풀 수 있어요.",
  restore: "독자 댓글 목록에 다시 보여요.",
  delete: "지워져요. 본문이 비워지고 되돌릴 수 없어요.",
};

const SUCCESS_MESSAGE: Record<NovelCommentAction, string> = {
  hide: "댓글을 숨겼어요.",
  restore: "댓글 숨김을 풀었어요.",
  delete: "댓글을 지웠어요.",
};

/** 고칠 입력이 없는 거부 — 그사이 댓글 상태가 바뀌었다. 모달을 닫고 목록은 새로 읽힌다. */
const REJECTION_MESSAGES: Record<string, string> = {
  NOVEL_COMMENT_DELETED: "이미 지워진 댓글이라 바꿀 수 없어요.",
  NOVEL_COMMENT_NOT_FOUND: "댓글이 사라졌어요. 작성자가 탈퇴했거나 소설이 지워졌을 수 있어요.",
};

const ERROR_MESSAGE = "처리하지 못했어요. 잠시 후 다시 시도해주세요.";

const commentActionSchema = z.object({
  adminComment: z.string().trim().min(1, "조치 사유를 입력해주세요."),
});

type CommentActionFormValues = z.infer<typeof commentActionSchema>;

type NovelCommentActionConfirmModalProps = {
  comment: AdminNovelComment;
  action: NovelCommentAction;
};

/** 노벨 상세 댓글 목록의 숨김·숨김 해제·삭제 확인. 사유는 감사 로그에 남아 셋 다 필수다(서버도 공백뿐이면 422). */
export const NovelCommentActionConfirmModal = createCallable<NovelCommentActionConfirmModalProps, void>(
  ({ call, comment, action }) => {
    const actionMutation = useNovelCommentActionMutation(comment.id);
    const {
      register,
      handleSubmit,
      formState: { errors, isSubmitting },
    } = useForm<CommentActionFormValues>({
      resolver: zodResolver(commentActionSchema),
      defaultValues: { adminComment: "" },
    });
    const isDelete = action === "delete";

    const onSubmit = async ({ adminComment }: CommentActionFormValues) => {
      try {
        await actionMutation.mutateAsync({ action, adminComment });
        toast.success(SUCCESS_MESSAGE[action]);
        call.end();
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
              <span className="font-medium text-foreground">{comment.authorNickname ?? "탈퇴한 회원"}</span>의{" "}
              {comment.chapterOrdinal}화 댓글이 {ACTION_EFFECT[action]}
            </DialogDescription>
          </DialogHeader>

          {!!comment.body && (
            <p className="max-h-32 overflow-y-auto whitespace-pre-wrap break-keep rounded-lg bg-secondary p-3 text-sm text-foreground wrap-anywhere">
              {comment.body}
            </p>
          )}

          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit(onSubmit)(event);
            }}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="novel-comment-action-reason">조치 사유 (필수)</Label>
              <Textarea
                id="novel-comment-action-reason"
                placeholder="감사 로그에 남길 사유"
                rows={3}
                aria-invalid={!!errors.adminComment}
                aria-describedby={errors.adminComment ? "novel-comment-action-reason-error" : undefined}
                {...register("adminComment")}
              />
              {errors.adminComment && (
                <p id="novel-comment-action-reason-error" role="alert" className="text-xs text-destructive-text">
                  {errors.adminComment.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" autoFocus data-initial-focus onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" variant={isDelete ? "destructive" : "default"} disabled={isSubmitting}>
                {isSubmitting ? "처리 중..." : ACTION_TITLE[action]}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
