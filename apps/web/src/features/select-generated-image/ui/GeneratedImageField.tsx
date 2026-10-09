import { useEffect, useMemo, useState, type ChangeEvent, type Ref } from "react";
import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Camera, ImageOff, Images, Loader2, X } from "lucide-react";
import { toast } from "sonner";

import { toThumbnailAspectClass, type ThumbnailAspect } from "@/entities/content";
import { uploadAsset, type AssetPurpose } from "@/shared/api/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";
import { FOCUS_WITHIN_RING_CLASSNAME } from "@/shared/ui/focusWithinRing";

import { GeneratedImagePickerModal } from "./GeneratedImagePickerModal";

export type SelectedImageValue = { assetId: string } | null;

type GeneratedImageFieldProps = {
  value: SelectedImageValue;
  onChange: (value: SelectedImageValue) => void;
  purpose: AssetPurpose;
  /** 지금 보여 줄 그림의 주소. 업로드 중이 아닐 때 칸에 그려지는 것은 이 값뿐이다. */
  previewUrl?: string;
  /** 업로드가 끝나 자산 ID 가 생겼을 때 그 자산 ID 와 올린(가공을 거친) 파일을 알린다. `onChange` 와 같은
   * 핸들러에서 불린다. */
  onUploadComplete: (assetId: string, file: File) => void;
  /** 갤러리에서 그림을 골랐을 때 그 자산 ID 와 피커가 준 표시 주소를 알린다. `onChange` 와 같은 핸들러에서 불린다. */
  onPick: (assetId: string, imageUrl: string) => void;
  label?: string;
  /** 미리보기 웰의 비율. 카드에서 실제로 보일 모양과 같게 둔다 — 스토리는 세로 2:3이라
   * 정사각 미리보기로는 잘려나갈 위아래를 판단할 수 없다. 폭(`w-28`)을 고정하고 높이가 비율을
   * 따라가므로 스토리 빌더에서만 이 줄이 56px 높아진다. */
  previewAspect?: ThumbnailAspect;
  /** 슬라이스끼리는 직접 import 하지 않는 관례라(eslint 가 강제하지는 않는다) `features/crop-image`를
   * 여기서 부르지 않고 콜백 주입으로 뒤집는다. 파일 선택 직후 원본을 가로채 가공한 File을 돌려주고,
   * undefined를 돌려주면 취소로 간주해 업로드하지 않는다. 갤러리 선택 경로(`handlePickFromGallery`)는
   * 거치지 않는다. */
  beforeUpload?: (file: File) => Promise<File | undefined>;
  /** 파일 고르기 입력에 붙일 ref. 폼이 발행 실패 때 이 칸으로 포커스를 보낼 수 있게 RHF `Controller` 의 `field.ref` 를 넘긴다 —
   * 그림이 없을 때(필수 오류가 나는 때) 이 칸에서 키보드로 닿는 첫 컨트롤이 파일 업로드다. 키보드로 발행했으면 그 라벨에 포커스 링이
   * 보인다(마우스로 눌렀으면 링 없이 포커스만 온다). */
  inputRef?: Ref<HTMLInputElement>;
};

/**
 * 캐릭터/스토리 빌더가 공유하는 이미지 필드. 업로드/갤러리선택/삭제
 * 세 경로 모두 `{assetId}`(또는 삭제 시 null) 하나로 수렴하므로, 이 컴포넌트를 쓰는 zod 폼 필드는
 * 항상 `z.object({ assetId: z.string() }).nullable()` 모양이면 된다(situationalImageSchema/
 * profile.image와 동일 shape).
 *
 * 표시 주소는 소비자가 `previewUrl`로 준다 — assetId만으로는 렌더링 가능한 URL을 만들 수 없다. 업로드가 끝나면
 * `onUploadComplete`, 갤러리에서 고르면 `onPick`으로 그 그림을 소비자에게 알리고, 소비자가 그 그림의 주소를
 * `previewUrl`로 돌려준다. 주소를 이 필드 안에 쥐지 않는 이유: 탭을 옮기면 이 필드가 언마운트돼 주소를 잃고,
 * 같은 그림을 보여야 하는 다른 화면(빌더 미리보기 카드)이 읽을 수 없다. 이 필드가 스스로 그리는 것은 업로드
 * 중인 파일 하나뿐이다 — 크롭 확정 즉시 그 파일을 그리고(그동안은 `previewUrl`보다 우선해야 업로드 중에 옛
 * 그림이 비치지 않는다), 업로드가 끝나거나 실패하면 내려서 `previewUrl`로 돌아간다. 실패면 콜백을 부르지
 * 않으므로 이전 그림이 그대로 돌아온다.
 */
export function GeneratedImageField({
  value,
  onChange,
  purpose,
  previewUrl,
  onUploadComplete,
  onPick,
  label = "이미지",
  previewAspect = "square",
  beforeUpload,
  inputRef,
}: GeneratedImageFieldProps) {
  const [selectedFile, setSelectedFile] = useState<File>();
  const [isUploading, setIsUploading] = useState(false);

  const objectPreviewUrl = useMemo(
    () => (selectedFile ? URL.createObjectURL(selectedFile) : undefined),
    [selectedFile],
  );
  useEffect(() => {
    if (!objectPreviewUrl) return;
    return () => URL.revokeObjectURL(objectPreviewUrl);
  }, [objectPreviewUrl]);

  const displayUrl = objectPreviewUrl ?? previewUrl;
  const inputId = `generated-image-field-${label}`;

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    const prepared = beforeUpload ? await beforeUpload(file) : file;
    if (!prepared) return; // 크롭 취소 — 기존 이미지를 그대로 둔다

    setSelectedFile(prepared);
    setIsUploading(true);
    try {
      const assetId = await uploadAsset(prepared, purpose);
      onUploadComplete(assetId, prepared);
      onChange({ assetId });
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
    } finally {
      // 성공이면 소비자가 같은 그림을 `previewUrl`로 돌려주고, 실패면 이전 그림으로 돌아간다 — 어느 쪽이든
      // 업로드 중 사본은 더 그리지 않는다.
      setSelectedFile(undefined);
      setIsUploading(false);
    }
  }

  async function handlePickFromGallery() {
    const picked = await GeneratedImagePickerModal.call({});
    if (!picked) return;
    setSelectedFile(undefined);
    onPick(picked.assetId, picked.imageUrl);
    onChange({ assetId: picked.assetId });
  }

  function handleDelete() {
    setSelectedFile(undefined);
    onChange(null);
  }

  return (
    <div className="flex items-start gap-4">
      {/* `overflow-hidden`은 이미지 웰(안쪽)에만 건다. 바깥 상자에 걸면 `-top-2 -right-2`로 밖으로
          나가려는 삭제 버튼이 잘려 "박스 안에 갇힌" 모양이 된다(2026-09-15 실사용 제보). */}
      <div className="relative w-28 shrink-0">
        <div
          className={cn(
            "relative w-full overflow-hidden rounded-lg bg-muted",
            toThumbnailAspectClass(previewAspect),
          )}
        >
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
        </div>

        {/* 보이는 크기(24px)는 그대로 두고 손가락 포인터에서만 투명한 의사 요소로 누르는 면을 40px 로 넓힌다 — 이 칸을 쓰는
            다른 화면(프로필 편집·문의·이미지 생성 참조)의 모양을 바꾸지 않기 위해서다. 보더 안쪽 22px 에서 사방 9px 이다. */}
        {value !== null && !isUploading && (
          <button
            type="button"
            onClick={handleDelete}
            aria-label="이미지 삭제"
            className="absolute -top-2 -right-2 inline-flex size-6 items-center justify-center rounded-full border border-input bg-background text-muted-foreground hover:text-destructive-text focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:after:absolute pointer-coarse:after:-inset-[9px]"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2">
        {/* 바로 아래 "생성한 이미지에서 선택" Button과 같은 variant="outline" size="sm"으로 맞춘다.
            숫자를 손코딩하지 않고 buttonVariants로 치수를 위임해 다음 변경에 자동으로 따라가게 한다. */}
        <Label
          htmlFor={inputId}
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "cursor-pointer has-disabled:pointer-events-none has-disabled:opacity-50",
            FOCUS_WITHIN_RING_CLASSNAME
          )}
        >
          <Camera aria-hidden className="size-4" />
          {isUploading ? "업로드 중..." : "파일 업로드"}
          <input
            ref={inputRef}
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
