import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@ai-character-chat/ui/components/select";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { Camera, Loader2, X } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import { INQUIRY_CATEGORIES, INQUIRY_CATEGORY_LABEL } from "@/entities/inquiry";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";

import { useCreateInquiryMutation } from "../api/useCreateInquiryMutation";
import { formToServer } from "../model/formToServer";
import {
  submitInquiryDefaultValues,
  submitInquirySchema,
  type SubmitInquiryFormValues,
} from "../model/schema";

const GENERIC_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.";

export function SubmitInquiryForm() {
  const navigate = useNavigate();
  const [isAttachmentUploading, setIsAttachmentUploading] = useState(false);

  const {
    register,
    handleSubmit,
    control,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<SubmitInquiryFormValues>({
    resolver: zodResolver(submitInquirySchema),
    defaultValues: submitInquiryDefaultValues,
  });

  const createInquiryMutation = useCreateInquiryMutation();

  async function handleValidSubmit(values: SubmitInquiryFormValues) {
    clearErrors("root");
    try {
      const created = await createInquiryMutation.mutateAsync(formToServer(values));
      toast.success("문의가 접수되었어요.");
      void navigate({ to: "/inquiries/$inquiryId", params: { inquiryId: created.id } });
    } catch {
      setError("root", { message: GENERIC_ERROR_MESSAGE });
    }
  }

  const isBusy = isSubmitting || isAttachmentUploading;

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void handleSubmit(handleValidSubmit)(event);
      }}
    >
      {errors.root && (
        <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive-text">
          {errors.root.message}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="submit-inquiry-category">문의 유형</Label>
        <Controller
          control={control}
          name="category"
          render={({ field }) => (
            <Select value={field.value} onValueChange={field.onChange}>
              <SelectTrigger
                id="submit-inquiry-category"
                className="w-full"
                aria-invalid={!!errors.category}
                aria-describedby={errors.category ? "submit-inquiry-category-error" : undefined}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {INQUIRY_CATEGORIES.map((category) => (
                  <SelectItem key={category} value={category}>
                    {INQUIRY_CATEGORY_LABEL[category]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        />
        {errors.category && (
          <p id="submit-inquiry-category-error" role="alert" className="text-xs text-destructive-text">
            {errors.category.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="submit-inquiry-title">제목</Label>
        <Input
          id="submit-inquiry-title"
          aria-invalid={!!errors.title}
          aria-describedby={errors.title ? "submit-inquiry-title-error" : undefined}
          {...register("title")}
        />
        {errors.title && (
          <p id="submit-inquiry-title-error" role="alert" className="text-xs text-destructive-text">
            {errors.title.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="submit-inquiry-body">내용</Label>
        <Textarea
          id="submit-inquiry-body"
          rows={8}
          aria-invalid={!!errors.body}
          aria-describedby={errors.body ? "submit-inquiry-body-error" : undefined}
          {...register("body")}
        />
        {errors.body && (
          <p id="submit-inquiry-body-error" role="alert" className="text-xs text-destructive-text">
            {errors.body.message}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>스크린샷 첨부 (선택)</Label>
        <Controller
          control={control}
          name="attachmentAssetId"
          render={({ field }) => (
            <InquiryAttachmentField
              value={field.value}
              onChange={field.onChange}
              onUploadingChange={setIsAttachmentUploading}
            />
          )}
        />
      </div>

      <Button type="submit" size="lg" className="self-start" disabled={isBusy}>
        {isSubmitting ? "접수 중..." : "문의 접수하기"}
      </Button>
    </form>
  );
}

type InquiryAttachmentFieldProps = {
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  onUploadingChange: (isUploading: boolean) => void;
};

/** `select-generated-image/ui/GeneratedImageField.tsx`에서 갈래질 선례 — 여기는 생성한 이미지
 * 갤러리 선택이 필요 없으므로 파일 업로드+미리보기+제거만 가져왔다. `value`/`onChange`가
 * `attachmentAssetId?: string`을 그대로 다뤄 RHF `field`에 바로 꽂힌다. */
function InquiryAttachmentField({
  value,
  onChange,
  onUploadingChange,
}: InquiryAttachmentFieldProps) {
  const [selectedFile, setSelectedFile] = useState<File | undefined>(undefined);
  const [isUploading, setIsUploading] = useState(false);

  const previewUrl = useMemo(() => (selectedFile ? URL.createObjectURL(selectedFile) : null), [selectedFile]);
  useEffect(() => {
    if (!previewUrl) return;
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setSelectedFile(file);
    setIsUploading(true);
    onUploadingChange(true);
    try {
      const assetId = await uploadAsset(file, "inquiry-attachment");
      onChange(assetId);
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
      setSelectedFile(undefined);
    } finally {
      setIsUploading(false);
      onUploadingChange(false);
    }
  }

  function handleRemove() {
    setSelectedFile(undefined);
    onChange(undefined);
  }

  return (
    <div className="flex flex-col items-start gap-2">
      {previewUrl && (
        <div className="relative size-28 shrink-0 overflow-hidden rounded-lg bg-muted">
          <img src={previewUrl} alt="" className="size-full object-cover" />

          {isUploading && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/70">
              <Loader2 aria-hidden className="size-5 animate-spin text-foreground" />
            </div>
          )}

          {value !== undefined && !isUploading && (
            <button
              type="button"
              onClick={handleRemove}
              aria-label="첨부 삭제"
              className="absolute -top-2 -right-2 inline-flex size-6 items-center justify-center rounded-full border border-input bg-background text-muted-foreground hover:text-destructive-text focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          )}
        </div>
      )}

      {/* 직접 비교 대상이 없어 같은 폼의 SelectTrigger(default=36px)에 맞춘다.
          숫자를 손코딩하지 않고 buttonVariants로 치수를 위임해 다음 변경에 자동으로 따라가게 한다
          (design-system-progress.md P-2-9). */}
      <Label
        htmlFor="submit-inquiry-attachment"
        className={cn(
          buttonVariants({ variant: "outline", size: "default" }),
          "cursor-pointer has-disabled:pointer-events-none has-disabled:opacity-50"
        )}
      >
        <Camera aria-hidden className="size-4" />
        {isUploading ? "업로드 중..." : "파일 업로드"}
        <input
          id="submit-inquiry-attachment"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          disabled={isUploading}
          onChange={(event) => void handleFileChange(event)}
        />
      </Label>
    </div>
  );
}
