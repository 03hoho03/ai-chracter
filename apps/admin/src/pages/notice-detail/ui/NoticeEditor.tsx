import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Markdown } from "@ai-character-chat/ui/components/markdown";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useState } from "react";
import { toast } from "sonner";

import {
  useCreateNoticeMutation,
  useUpdateNoticeMutation,
  usePublishNoticeMutation,
  useUnpublishNoticeMutation,
  type AdminNoticeDetailResponse,
} from "@/entities/notice";

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
 * 저장 버튼은 `hasUnsavedChanges`일 때만 활성화한다(`LegalEditor`의 버퍼 비교 패턴). 다만
 * 초안/게시본이 갈리지 않으므로 "저장해야 게시 가능" 잠금은 없다 — 게시/숨김 버튼은 저장
 * 여부와 무관하게 항상 눌릴 수 있다. */
export function NoticeEditor({ notice, onCreated }: NoticeEditorProps) {
  const [title, setTitle] = useState(notice?.title ?? "");
  const [body, setBody] = useState(notice?.bodyMarkdown ?? "");

  const createMutation = useCreateNoticeMutation();
  const updateMutation = useUpdateNoticeMutation(notice?.id ?? "");
  const publishMutation = usePublishNoticeMutation(notice?.id ?? "");
  const unpublishMutation = useUnpublishNoticeMutation(notice?.id ?? "");

  const hasUnsavedChanges = title !== (notice?.title ?? "") || body !== (notice?.bodyMarkdown ?? "");
  const isSaving = createMutation.isPending || updateMutation.isPending;

  const handleSave = async () => {
    try {
      if (notice === null) {
        const created = await createMutation.mutateAsync({ title, bodyMarkdown: body });
        toast.success("공지를 만들었어요.");
        onCreated?.(created.id);
      } else {
        await updateMutation.mutateAsync({ title, bodyMarkdown: body });
        toast.success("공지를 저장했어요.");
      }
    } catch {
      toast.error(ERROR_MESSAGE);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="notice-title">제목</Label>
        <Input id="notice-title" value={title} onChange={(event) => setTitle(event.target.value)} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="notice-body">본문</Label>
        <Textarea
          id="notice-body"
          value={body}
          onChange={(event) => setBody(event.target.value)}
          placeholder="마크다운으로 본문을 작성하세요."
          className="min-h-64 resize-none"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>미리보기</Label>
        <div className="max-w-2xl rounded-lg border border-border bg-card p-4">
          {body.trim() ? (
            <Markdown content={body} />
          ) : (
            <p className="text-sm text-muted-foreground">미리볼 내용이 없어요.</p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" disabled={!hasUnsavedChanges || isSaving} onClick={() => void handleSave()}>
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
    </div>
  );
}
