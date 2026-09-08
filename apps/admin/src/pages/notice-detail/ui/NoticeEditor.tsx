import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import {
  useCreateNoticeMutation,
  useUpdateNoticeMutation,
  usePublishNoticeMutation,
  useUnpublishNoticeMutation,
  type AdminNoticeDetailResponse,
} from "@/entities/notice";

import { noticeEditorSchema, type NoticeEditorFormValues } from "../model/schema";
import { PublishNoticeDialog } from "./PublishNoticeDialog";

type NoticeEditorProps = {
  /** `null`이면 아직 생성되지 않은 새 공지(`/notices/new`)다. */
  notice: AdminNoticeDetailResponse | null;
  onCreated?: (id: string) => void;
};

const ERROR_MESSAGE = "저장에 실패했어요. 잠시 후 다시 시도해주세요.";

/** 상하 분할 에디터(techspec.md §6-2, D-15) — `LegalEditor`의 좌우 분할이 아니다. 공지 본문은
 * 약관(6천~1만2천 자)과 달리 수백~수천 자라 좌우로 나누면 양쪽이 다 빈다. 미리보기 폭을
 * `max-w-2xl`로 고정하는 것이 상하를 고른 이유다 — 유저 화면(`/notices/$id`)의 본문 컬럼과
 * 같은 값이라 줄바꿈이 실제와 같게 보인다.
 *
 * 폼 상태는 `LegalEditor`의 useState 버퍼가 아니라 RHF+zod다(`apps/web/CLAUDE.md` 폼 규약).
 * "저장할 게 있나"는 손으로 비교하지 않고 `formState.isDirty`가 지며, 저장 성공 시 `reset(values)`로
 * 새 기준선을 세운다. 다만 초안/게시본이 갈리지 않으므로 "저장해야 게시 가능" 잠금은 없다 —
 * 게시/숨김 버튼은 저장 여부와 무관하게 항상 눌릴 수 있다.
 *
 * 저장 버튼의 비활성은 `disabled`가 아니라 `aria-disabled`다 — `disabled`면 누르는 즉시 브라우저가
 * blur해 키보드 사용자의 포커스가 `<body>`로 떨어진다(`apps/web/CLAUDE.md`, `ContentListLoadMore` 선례).
 * `pointer-events`가 못 막는 키보드 Enter는 `onSubmit` 첫 줄 early return이 막는다. */
export function NoticeEditor({ notice, onCreated }: NoticeEditorProps) {
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<NoticeEditorFormValues>({
    resolver: zodResolver(noticeEditorSchema),
    defaultValues: {
      title: notice?.title ?? "",
      bodyMarkdown: notice?.bodyMarkdown ?? "",
    },
  });

  const createMutation = useCreateNoticeMutation();
  const updateMutation = useUpdateNoticeMutation(notice?.id ?? "");
  const publishMutation = usePublishNoticeMutation(notice?.id ?? "");
  const unpublishMutation = useUnpublishNoticeMutation(notice?.id ?? "");

  const bodyMarkdown = useWatch({ control, name: "bodyMarkdown" });
  const isSaving = createMutation.isPending || updateMutation.isPending;
  const isSaveBlocked = !isDirty || isSaving;

  async function onSubmit(values: NoticeEditorFormValues) {
    if (isSaveBlocked) return;

    try {
      if (notice === null) {
        const created = await createMutation.mutateAsync(values);
        reset(values);
        toast.success("공지를 만들었어요.");
        onCreated?.(created.id);
      } else {
        await updateMutation.mutateAsync(values);
        reset(values);
        toast.success("공지를 저장했어요.");
      }
    } catch {
      toast.error(ERROR_MESSAGE);
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(onSubmit)(event);
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="notice-title">제목</Label>
        <Input
          id="notice-title"
          aria-invalid={!!errors.title}
          aria-describedby={errors.title ? "notice-title-error" : undefined}
          {...register("title")}
        />
        {errors.title && (
          <p id="notice-title-error" role="alert" className="text-xs text-destructive-text">
            {errors.title.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="notice-body">본문</Label>
        <Textarea
          id="notice-body"
          placeholder="마크다운으로 본문을 작성하세요."
          className="min-h-64 resize-none"
          aria-invalid={!!errors.bodyMarkdown}
          aria-describedby={errors.bodyMarkdown ? "notice-body-error" : undefined}
          {...register("bodyMarkdown")}
        />
        {errors.bodyMarkdown && (
          <p id="notice-body-error" role="alert" className="text-xs text-destructive-text">
            {errors.bodyMarkdown.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>미리보기</Label>
        <div className="max-w-2xl rounded-lg border border-border bg-card p-4">
          {bodyMarkdown.trim() ? (
            <Markdown content={bodyMarkdown} />
          ) : (
            <p className="text-sm text-muted-foreground">미리볼 내용이 없어요.</p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          size="sm"
          aria-disabled={isSaveBlocked}
          className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
        >
          {isSaving ? "저장 중..." : "저장"}
        </Button>

        {notice !== null &&
          (notice.published ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                void PublishNoticeDialog.call({
                  title: notice.title,
                  action: "unpublish",
                  mutationFn: async (call) => {
                    try {
                      await unpublishMutation.mutateAsync();
                      toast.success("공지를 숨겼어요.");
                      call.end();
                    } catch {
                      toast.error(ERROR_MESSAGE);
                    }
                  },
                })
              }
            >
              숨김
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                void PublishNoticeDialog.call({
                  title: notice.title,
                  action: "publish",
                  mutationFn: async (call) => {
                    try {
                      await publishMutation.mutateAsync();
                      toast.success("공지를 게시했어요.");
                      call.end();
                    } catch {
                      toast.error(ERROR_MESSAGE);
                    }
                  },
                })
              }
            >
              게시
            </Button>
          ))}
      </div>
    </form>
  );
}
