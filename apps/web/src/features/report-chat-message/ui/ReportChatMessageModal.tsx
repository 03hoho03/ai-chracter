import { useId } from "react";
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
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { zodResolver } from "@hookform/resolvers/zod";
import { createCallable } from "react-call";
import { Controller, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import { useReportChatMessageMutation } from "../api/useReportChatMessageMutation";
import { formToServer } from "../model/formToServer";
import { reportErrorMessage } from "../model/reportErrorMessage";
import {
  CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH,
  CHAT_MESSAGE_REPORT_REASON_LABELS,
  CHAT_MESSAGE_REPORT_REASONS,
  chatMessageReportSchema,
  countNoteLength,
  isChatMessageReportReason,
  type ChatMessageReportFormValues,
} from "../model/schema";

type ReportChatMessageModalProps = {
  roomId: string;
  messageId: string;
  /** 루트에 마운트된 모달이라 닫힌 뒤 포커스를 스스로 돌려주지 못한다 — 호출부가 "⋯" 트리거로 돌려준다. */
  returnFocus: () => void;
};

/** 채팅 AI 응답 신고. 호출부가 채팅방 하나뿐이고 성공 뒤 할 일(접수 안내 후 닫기)이 늘 같아 자체 호출형이다.
 *
 * 실패하면 안내만 띄우고 모달은 열어 둔다 — 고른 사유와 메모를 그대로 두고 다시 보낼 수 있게.
 * 같은 응답을 다시 신고해도 서버가 같은 결과를 돌려주므로 첫 신고와 같은 접수 안내가 뜬다.
 *
 * 사유 토글은 Radix 단일선택이라 선택한 항목을 다시 누르면 빈 문자열이 온다 — `Controller` 가 목록에
 * 있는 값만 통과시키고 나머지는 미선택으로 접는다. 미선택 제출은 버튼 비활성이 아니라 zod 오류로 막는다. */
export const ReportChatMessageModal = createCallable<ReportChatMessageModalProps, void>(
  ({ call, roomId, messageId, returnFocus }) => {
    const fieldId = useId();
    const reasonErrorId = `${fieldId}-reason-error`;
    const noteId = `${fieldId}-note`;
    const noteCountId = `${fieldId}-note-count`;
    const noteErrorId = `${fieldId}-note-error`;

    const form = useForm<ChatMessageReportFormValues>({
      resolver: zodResolver(chatMessageReportSchema),
      defaultValues: { note: "" },
    });
    const { errors, isSubmitting } = form.formState;
    const noteLength = countNoteLength(useWatch({ control: form.control, name: "note" }));
    const reportMutation = useReportChatMessageMutation(roomId, messageId);

    async function handleValidSubmit(values: ChatMessageReportFormValues) {
      try {
        await reportMutation.mutateAsync(formToServer(values));
        toast.success("신고가 접수됐어요.");
        call.end();
      } catch (error) {
        toast.error(reportErrorMessage(error));
      }
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
        <DialogContent
          className="max-h-dialog overflow-y-auto sm:max-w-sm"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            requestAnimationFrame(returnFocus);
          }}
        >
          <DialogHeader>
            <DialogTitle>응답 신고</DialogTitle>
            <DialogDescription className="break-keep">
              이 응답의 문제를 골라주세요. 검토를 위해 이 응답과 바로 앞 내 메시지가 최대 90일 동안 보관돼요.
            </DialogDescription>
          </DialogHeader>

          <form
            className="flex flex-col gap-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              // 접수 중 `disabled` 는 누른 버튼의 포커스를 날린다 — `aria-disabled` 로 두고 여기서 막는다.
              if (isSubmitting) return;
              void form.handleSubmit(handleValidSubmit)(event);
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Controller
                control={form.control}
                name="reason"
                render={({ field }) => (
                  // `hover:bg-secondary` — 프리미티브의 `hover:bg-muted` 는 모달(popover) 표면과 같은 값이라 사라진다.
                  <ToggleGroup
                    type="single"
                    variant="list"
                    orientation="vertical"
                    value={field.value ?? ""}
                    onValueChange={(value) => field.onChange(isChatMessageReportReason(value) ? value : undefined)}
                    aria-label="신고 사유"
                    aria-invalid={!!errors.reason}
                    aria-describedby={errors.reason ? reasonErrorId : undefined}
                    className="w-full"
                  >
                    {CHAT_MESSAGE_REPORT_REASONS.map((reason) => (
                      <ToggleGroupItem key={reason} value={reason} className="h-11 w-full justify-start px-3 hover:bg-secondary">
                        {CHAT_MESSAGE_REPORT_REASON_LABELS[reason]}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                )}
              />
              {errors.reason && (
                <p id={reasonErrorId} role="alert" className="text-xs text-destructive-text">
                  {errors.reason.message}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <Label htmlFor={noteId}>
                  메모 <span className="font-normal text-muted-foreground">(선택)</span>
                </Label>
                <span id={noteCountId} className="text-xs text-muted-foreground tabular-nums">
                  {noteLength}/{CHAT_MESSAGE_REPORT_NOTE_MAX_LENGTH}
                </span>
              </div>
              <Textarea
                id={noteId}
                rows={3}
                placeholder="어떤 점이 문제였는지 적어주세요"
                aria-invalid={!!errors.note}
                aria-describedby={errors.note ? `${noteErrorId} ${noteCountId}` : noteCountId}
                {...form.register("note")}
              />
              {errors.note && (
                <p id={noteErrorId} role="alert" className="text-xs text-destructive-text">
                  {errors.note.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end()}>
                취소
              </Button>
              <Button type="submit" aria-disabled={isSubmitting} className="aria-disabled:opacity-65">
                {isSubmitting ? "접수 중…" : "신고하기"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  },
);
