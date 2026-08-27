import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Camera, ImageOff, Images, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { uploadAsset, type AssetPurpose } from "../../../shared/lib/asset/uploadAsset";
import { uploadAssetErrorMessage } from "../../../shared/lib/asset/uploadAssetErrorMessage";
import { GeneratedImagePickerModal } from "./GeneratedImagePickerModal";

export type SelectedImageValue = { assetId: string } | null;

/**
 * techspec-builder-story.md §2 — 캐릭터/스토리 빌더가 공유하는 이미지 필드. 업로드/갤러리선택/삭제
 * 세 경로 모두 `{assetId}`(또는 삭제 시 null) 하나로 수렴하므로, 이 컴포넌트를 쓰는 zod 폼 필드는
 * 항상 `z.object({ assetId: z.string() }).nullable()` 모양이면 된다(situationalImageSchema/
 * profile.image와 동일 shape). `previewUrl`은 이미 서버에 저장된 값을 편집할 때 소비자가 알고 있는
 * 경우에만 넘기는 표시 전용 prop — assetId만으로는 렌더링 가능한 URL을 만들 수 없다(apps/api
 * CLAUDE.md의 "thumbnailAssetId만 주고 URL을 안 준다" 갭과 동일한 이유). 이번 세션에 직접 업로드/
 * 선택한 이미지는 로컬 상태의 미리보기 URL이 항상 우선한다.
 */
export function GeneratedImageField({
  value,
  onChange,
  purpose,
  previewUrl = null,
  label = "이미지",
}: {
  value: SelectedImageValue;
  onChange: (value: SelectedImageValue) => void;
  purpose: AssetPurpose;
  previewUrl?: string | null;
  label?: string;
}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pickedPreviewUrl, setPickedPreviewUrl] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  const objectPreviewUrl = useMemo(
    () => (selectedFile ? URL.createObjectURL(selectedFile) : null),
    [selectedFile],
  );
  useEffect(() => {
    if (!objectPreviewUrl) return;
    return () => URL.revokeObjectURL(objectPreviewUrl);
  }, [objectPreviewUrl]);

  const displayUrl = objectPreviewUrl ?? pickedPreviewUrl ?? previewUrl;
  const inputId = `generated-image-field-${label}`;

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setSelectedFile(file);
    setPickedPreviewUrl(null);
    setIsUploading(true);
    try {
      const assetId = await uploadAsset(file, purpose);
      onChange({ assetId });
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
      setSelectedFile(null);
    } finally {
      setIsUploading(false);
    }
  }

  async function handlePickFromGallery() {
    const picked = await GeneratedImagePickerModal.call();
    if (!picked) return;
    setSelectedFile(null);
    setPickedPreviewUrl(picked.imageUrl);
    onChange({ assetId: picked.assetId });
  }

  function handleDelete() {
    setSelectedFile(null);
    setPickedPreviewUrl(null);
    onChange(null);
  }

  return (
    <div className="flex items-start gap-4">
      <div className="relative size-28 shrink-0 overflow-hidden rounded-lg bg-muted">
        {displayUrl ? (
          <img
            src={displayUrl}
            alt=""
            loading="lazy"
            decoding="async"
            className="size-full object-cover"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden />
          </div>
        )}

        {isUploading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/70">
            <Loader2 aria-hidden className="size-5 animate-spin text-foreground" />
          </div>
        )}

        {value !== null && !isUploading && (
          <button
            type="button"
            onClick={handleDelete}
            aria-label="이미지 삭제"
            className="absolute -top-2 -right-2 inline-flex size-6 items-center justify-center rounded-full border border-input bg-background text-muted-foreground shadow-sm hover:text-destructive-text focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label
          htmlFor={inputId}
          className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-input bg-background px-2.5 text-sm font-medium hover:bg-muted has-disabled:pointer-events-none has-disabled:opacity-50"
        >
          <Camera aria-hidden className="size-4" />
          {isUploading ? "업로드 중..." : "파일 업로드"}
          <input
            id={inputId}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            disabled={isUploading}
            onChange={(event) => void handleFileChange(event)}
          />
        </Label>

        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isUploading}
          onClick={() => void handlePickFromGallery()}
        >
          <Images aria-hidden />
          생성한 이미지에서 선택
        </Button>
      </div>
    </div>
  );
}
