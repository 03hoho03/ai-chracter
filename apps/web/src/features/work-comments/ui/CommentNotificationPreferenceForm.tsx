import { useEffect, useId, useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import type { CommentPreferences } from "@/entities/comment";

import { notificationPreferenceServerToForm } from "../api/notificationPreferenceMappers";
import { useSaveCommentPreferencesMutation } from "../api/useSaveCommentPreferencesMutation";
import { notificationPreferenceErrors } from "../model/notificationPreferenceErrors";
import { notificationPreferenceSchema, type NotificationPreferenceFormValues } from "../model/notificationPreferenceSchema";

const NOTIFICATION_LABELS: Record<keyof NotificationPreferenceFormValues, string> = {
  isNewCommentEnabled: "내 작품의 새 원댓글", isReplyEnabled: "내 댓글에 대한 답글", isMentionEnabled: "나를 선택한 멘션",
};

export function CommentNotificationPreferenceForm({ viewerId, preferences }: { viewerId: string; preferences: CommentPreferences }) {
  const id = useId();
  const isSubmittingRef = useRef(false);
  const form = useForm<NotificationPreferenceFormValues>({ resolver: zodResolver(notificationPreferenceSchema), defaultValues: notificationPreferenceServerToForm(preferences) });
  const save = useSaveCommentPreferencesMutation(viewerId);
  const { errors, isSubmitting, isDirty } = form.formState;

  useEffect(() => { if (!isDirty) form.reset(notificationPreferenceServerToForm(preferences)); }, [form, preferences, isDirty]);

  async function handleSubmit(values: NotificationPreferenceFormValues) {
    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    form.clearErrors("root");
    try {
      const updated = await save.mutateAsync(values);
      if (JSON.stringify(form.getValues()) === JSON.stringify(values)) form.reset(notificationPreferenceServerToForm(updated));
      toast.success("댓글 알림 설정을 저장했어요.");
    } catch (error) {
      for (const failure of notificationPreferenceErrors(error)) form.setError(failure.field, { type: "server", message: failure.message });
    }
    finally { isSubmittingRef.current = false; }
  }

  return <form noValidate className="flex flex-col gap-3" onSubmit={(event) => {
    event.preventDefault();
    if (isSubmitting || isSubmittingRef.current) return;
    void form.handleSubmit(handleSubmit)(event);
  }}>
    {notificationPreferenceSchema.keyof().options.map((name) => <div key={name} className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor={id + name} className="break-keep text-sm">{NOTIFICATION_LABELS[name]}</Label>
        <Controller name={name} control={form.control} render={({ field }) => <Switch id={id + name} checked={field.value} onCheckedChange={field.onChange}
          aria-invalid={!!errors[name]} aria-describedby={errors[name] ? id + name + "-error" : undefined} />} />
      </div>
      {!!errors[name] && <p id={id + name + "-error"} role="alert" className="text-xs text-destructive-text">{errors[name]?.message}</p>}
    </div>)}
    {!!errors.root && <p role="alert" className="break-keep text-sm text-destructive-text">{errors.root.message}</p>}
    <Button type="submit" variant="outline" size="sm" className="w-fit aria-disabled:opacity-65" aria-disabled={isSubmitting}>
      {isSubmitting ? "저장 중…" : "댓글 알림 설정 저장"}</Button>
  </form>;
}
