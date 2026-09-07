import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { zodResolver } from "@hookform/resolvers/zod";
import { createCallable } from "react-call";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { isApiError } from "@/shared/lib/api/client";

import { LEGAL_KIND_LABELS, type LegalKind } from "../model/legalKind";
import { usePublishMutation } from "../api/usePublishMutation";

// 서버(`AdminLegalPublishRequest.version`)와 같은 포맷 제약 — zero-padded ISO 날짜가
// 아니면 `_reconsent_required`(auth/router.py)의 문자열 비교가 시간순과 어긋난다.
// 422 응답을 받고서야 알리는 대신, 여기서 미리 막는다.
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const publishSchema = z.object({
  version: z.string().trim().regex(ISO_DATE_PATTERN, "YYYY-MM-DD 형식으로 입력해 주세요."),
  requiresReconsent: z.boolean(),
});

type PublishFormValues = z.infer<typeof publishSchema>;

type PublishDialogProps = {
  kind: LegalKind;
};

/** UserActionConfirmModal과 같은 결 — 입력 실패는 조용히 삼키지 않는다. 다만 이 다이얼로그는
 * 409(버전 중복)만 특별 취급한다: 폼을 닫지 않고 `setError`로 버전 필드에 서버 문구를 그대로
 * 붙여 admin이 버전만 고쳐 바로 재시도할 수 있게 한다(그 외 실패는 toast만 띄우고 역시 닫지
 * 않는다 — call.end()는 성공 분기에만 있다). */
export const PublishDialog = createCallable<PublishDialogProps, void>(({ call, kind }) => {
  const publishMutation = usePublishMutation(kind);
  const {
    control,
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<PublishFormValues>({
    resolver: zodResolver(publishSchema),
    defaultValues: { version: todayIsoDate(), requiresReconsent: false },
  });

  const onSubmit = async (values: PublishFormValues) => {
    try {
      await publishMutation.mutateAsync(values);
      toast.success(`${LEGAL_KIND_LABELS[kind]} v${values.version}을 게시했어요.`);
      call.end();
    } catch (error) {
      if (isApiError(error) && error.status === 409 && typeof error.detail === "string") {
        setError("version", { message: error.detail });
      } else {
        toast.error("게시에 실패했어요. 잠시 후 다시 시도해주세요.");
      }
    }
  };

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{LEGAL_KIND_LABELS[kind]} 게시</DialogTitle>
          <DialogDescription className="break-keep">
            현재 저장된 초안을 새 버전으로 게시해요. 초안은 게시 후에도 그대로 남아요.
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
            <Label htmlFor="legal-publish-version">버전</Label>
            <Input
              id="legal-publish-version"
              placeholder="예: 2026-09-06"
              aria-invalid={!!errors.version}
              aria-describedby={errors.version ? "legal-publish-version-error" : undefined}
              {...register("version")}
            />
            {errors.version && (
              <p id="legal-publish-version-error" role="alert" className="text-xs text-destructive-text">
                {errors.version.message}
              </p>
            )}
          </div>

          <Controller
            name="requiresReconsent"
            control={control}
            render={({ field }) => (
              <div className="flex items-center gap-2">
                <Checkbox
                  id="legal-publish-reconsent"
                  checked={field.value}
                  onCheckedChange={(checked) => field.onChange(checked === true)}
                />
                <Label htmlFor="legal-publish-reconsent" className="font-normal">
                  중요한 변경 — 전원 재동의 필요
                </Label>
              </div>
            )}
          />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end()}>
              취소
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "게시 중..." : "게시"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
});

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}
