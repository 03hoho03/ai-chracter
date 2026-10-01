import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Camera, Images, Loader2, X } from "lucide-react";
import { useId, useState, type ChangeEvent } from "react";
import { toast } from "sonner";

import { toMediaNameTag } from "@/entities/media-book";
import {
  cellImageRefusalMessage,
  countCharacters,
  findCell,
  MAX_MEDIA_BOOK_SITUATION_LENGTH,
  MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH,
  removeCell,
  setCellImage,
  updateCell,
  type MediaBookCellImage,
  type MediaBookCellTextPatch,
  type MediaBookCellValues,
} from "@/features/build-story";
import { MediaBookConfirmModal } from "@/features/edit-media-book";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";

import type { MediaBookPosition } from "./MediaBookGrid";
import { useMediaBookEditor } from "../model/useMediaBookEditor";
import { useMediaBookThumbnails } from "../model/useMediaBookThumbnails";

// 미리보기 상자의 긴 변 상한(px). 세로로 긴 그림이 패널을 길게 늘이지 않게 폭을 비율로 줄인다.
const PREVIEW_MAX_HEIGHT_PX = 256;
const PREVIEW_MAX_WIDTH_PX = 192;

type MediaBookCellPanelProps = {
  id: string;
  position: MediaBookPosition;
  onClose: () => void;
  /** 누른 버튼이 사라질 때(비우기 뒤) 포커스를 표의 그 칸으로 돌려준다. */
  onReturnFocus: () => void;
};

/**
 * 배치표에서 고른 칸의 상세. 배치표 바로 아래에 펼친다(모달이 아니다 — 칸을 바꿔 가며 연달아 채우는 작업이라 표가
 * 계속 보여야 한다). 빈 칸이면 그림 넣기만, 채운 칸이면 그림 바꾸기·상황 설명·해금 힌트·노출 제외·비우기.
 */
export function MediaBookCellPanel({ id, position, onClose, onReturnFocus }: MediaBookCellPanelProps) {
  const { mediaBook, getMediaBook, commit } = useMediaBookEditor();
  const person = mediaBook.people.find((item) => item.id === position.personId);
  const scene = mediaBook.scenes.find((item) => item.id === position.sceneId);
  const cell = findCell(mediaBook, position.personId, position.sceneId);
  if (!person || !scene) return null;

  function handleImageChange(image: MediaBookCellImage) {
    // 업로드를 기다리는 동안 다른 칸이 채워졌을 수 있다 — 그 순간의 값 위에 쓴다.
    // 업로드를 기다리는 사이 이 칸의 인물·장면이 지워졌으면 거절된다(없는 축을 가리키는 칸을 만들지 않는다).
    const result = setCellImage(getMediaBook(), position.personId, position.sceneId, image, () => crypto.randomUUID());
    if (!result.ok) {
      toast.error(`${cellImageRefusalMessage(result.reason)}.`);
      return;
    }
    commit(result.mediaBook);
  }

  function handlePatch(patch: MediaBookCellTextPatch) {
    if (cell) commit(updateCell(getMediaBook(), cell.id, patch));
  }

  async function handleClear() {
    if (!cell) return;
    const trigger = document.activeElement;
    const isConfirmed = await MediaBookConfirmModal.call({
      title: "이 칸을 비울까요?",
      description: "그림과 상황 설명·해금 힌트가 함께 지워져요. 글 속 표기는 그대로 남고 화면에는 빈칸이 돼요.",
      confirmLabel: "비우기",
      // 취소면 "이 칸 비우기" 버튼이 그대로라 그리로, 비웠으면 그 버튼이 빈 칸 화면으로 바뀌며 사라지므로 표의 칸으로.
      onRestoreFocus: () => {
        if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
        else onReturnFocus();
      },
    });
    if (isConfirmed) commit(removeCell(getMediaBook(), cell.id));
  }

  const tag = toMediaNameTag(person.name, scene.name);
  const headingId = `${id}-heading`;

  return (
    <section id={id} aria-labelledby={headingId} className="flex flex-col gap-4 rounded-xl border border-border p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          {/* 키보드로 칸을 열면 포커스가 여기로 온다(상세가 표 아래 화면 밖에 열려도 따라가게). */}
          <h3 id={headingId} tabIndex={-1} className="truncate text-lg font-semibold text-foreground focus-visible:outline-none">
            {person.name} · {scene.name}
          </h3>
          <p className="text-xs break-all text-muted-foreground">{tag}</p>
        </div>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="칸 상세 닫기" onClick={onClose}>
          <X aria-hidden />
        </Button>
      </div>

      {cell ? (
        <FilledCellFields
          cell={cell}
          onImageChange={handleImageChange}
          onPatch={handlePatch}
          onClear={() => void handleClear()}
        />
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm break-keep text-muted-foreground">
            아직 그림이 없는 칸이에요. 그림을 넣으면 상황 설명과 해금 힌트를 적을 수 있어요.
          </p>
          <CellImageButtons onImageChange={handleImageChange} />
        </div>
      )}
    </section>
  );
}

type FilledCellFieldsProps = {
  cell: MediaBookCellValues;
  onImageChange: (image: MediaBookCellImage) => void;
  onPatch: (patch: MediaBookCellTextPatch) => void;
  onClear: () => void;
};

function FilledCellFields({ cell, onImageChange, onPatch, onClear }: FilledCellFieldsProps) {
  const thumbnails = useMediaBookThumbnails();
  const imageUrl = thumbnails.resolveUrl(cell.imageAssetId, cell.imageUrl);
  const fieldId = `media-book-cell-${cell.id}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-4">
        <CellPreview imageUrl={imageUrl} width={cell.imageWidth} height={cell.imageHeight} />
        <CellImageButtons onImageChange={onImageChange} isReplacing />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${fieldId}-situation`}>상황 설명</Label>
        <Textarea
          id={`${fieldId}-situation`}
          rows={2}
          placeholder="예) 에리가 선물을 받고 환하게 웃는 순간"
          value={cell.situationDescription}
          aria-describedby={`${fieldId}-situation-help`}
          onChange={(event) =>
            onPatch({ situationDescription: clampCharacters(event.target.value, MAX_MEDIA_BOOK_SITUATION_LENGTH) })
          }
        />
        <p id={`${fieldId}-situation-help`} className="flex justify-between gap-2 text-xs text-muted-foreground">
          <span className="break-keep">대화 중 어떤 그림을 띄울지 AI 가 고를 때 이름과 함께 읽어요.</span>
          <span className="shrink-0 tabular-nums">
            {countCharacters(cell.situationDescription)}/{MAX_MEDIA_BOOK_SITUATION_LENGTH}
          </span>
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${fieldId}-hint`}>해금 힌트</Label>
        <Input
          id={`${fieldId}-hint`}
          placeholder="예) 에리와 친해지면 볼 수 있어요"
          value={cell.unlockHint}
          aria-describedby={`${fieldId}-hint-help`}
          onChange={(event) =>
            onPatch({ unlockHint: clampCharacters(event.target.value, MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH) })
          }
        />
        <p id={`${fieldId}-hint-help`} className="flex justify-between gap-2 text-xs text-muted-foreground">
          <span className="break-keep">아직 못 본 사람의 이미지 보관함에 흐린 그림과 함께 보여요. 비우면 자물쇠만 보여요.</span>
          <span className="shrink-0 tabular-nums">
            {countCharacters(cell.unlockHint)}/{MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH}
          </span>
        </p>
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor={`${fieldId}-exclude`}>대화 중에는 띄우지 않기</Label>
          <p className="text-sm break-keep text-muted-foreground">
            켜면 AI 가 대화 중에 이 그림을 고르지 않아요. 글 속 표기로 넣은 자리에는 그대로 보여요.
          </p>
        </div>
        <Switch
          id={`${fieldId}-exclude`}
          checked={cell.excludeFromChat}
          onCheckedChange={(checked) => onPatch({ excludeFromChat: checked })}
        />
      </div>

      <Button type="button" variant="destructive" size="sm" className="w-fit" onClick={onClear}>
        이 칸 비우기
      </Button>
    </div>
  );
}

/** 글자 수를 서버와 같은 코드 포인트로 잘라, 입력이 상한을 넘는 값을 폼에 만들지 않는다. */
function clampCharacters(value: string, max: number): string {
  return countCharacters(value) <= max ? value : [...value].slice(0, max).join("");
}

type CellPreviewProps = { imageUrl: string | undefined; width: number | undefined; height: number | undefined };

/**
 * 칸 그림 미리보기. 크기를 알면 상자를 그림 비율로 잡아 여백 없이 보이고, 모르면(막 올렸거나 크기를 기록하기 전
 * 자산) 3:4 상자 안에 원래 비율대로 맞춘다. 어느 쪽이든 상자 크기가 그림 도착 전에 정해져 아래 입력칸이 밀리지 않는다.
 */
function CellPreview({ imageUrl, width, height }: CellPreviewProps) {
  const hasSize = width !== undefined && height !== undefined && width > 0 && height > 0;
  const ratio = hasSize ? width / height : 3 / 4;
  const boxWidth = Math.min(PREVIEW_MAX_WIDTH_PX, PREVIEW_MAX_HEIGHT_PX * ratio);

  return (
    <div
      className="flex shrink-0 items-center justify-center overflow-hidden rounded-lg border border-foreground/10 bg-muted"
      style={{ width: boxWidth, aspectRatio: ratio }}
    >
      {imageUrl && <img src={imageUrl} alt="" decoding="async" className="size-full object-contain" />}
    </div>
  );
}

type CellImageButtonsProps = {
  onImageChange: (image: MediaBookCellImage) => void;
  isReplacing?: boolean;
};

/** 칸 그림을 올리거나 생성한 이미지에서 고른다. 채운 칸이면 같은 칸에 그림만 바꾼다. */
function CellImageButtons({ onImageChange, isReplacing = false }: CellImageButtonsProps) {
  const thumbnails = useMediaBookThumbnails();
  const [isUploading, setIsUploading] = useState(false);
  const inputId = useId();
  const uploadLabel = isReplacing ? "다른 파일로 바꾸기" : "파일 올리기";

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || isUploading) return;
    setIsUploading(true);
    try {
      const assetId = await uploadAsset(file, "situational-image");
      onImageChange({ assetId, imageUrl: thumbnails.rememberUploadedFile(assetId, file) });
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
    } finally {
      setIsUploading(false);
    }
  }

  async function handlePick() {
    const picked = await GeneratedImagePickerModal.call({
      description: "이전에 생성해 둔 이미지 중 하나를 골라 이 칸에 넣어요.",
    });
    if (!picked) return;
    thumbnails.rememberPickedUrl(picked.assetId, picked.imageUrl);
    onImageChange({ assetId: picked.assetId, imageUrl: picked.imageUrl });
  }

  return (
    <div className="flex flex-col gap-2">
      <Label
        htmlFor={inputId}
        aria-disabled={isUploading}
        className={cn(
          buttonVariants({ variant: "outline", size: "sm" }),
          "cursor-pointer aria-disabled:pointer-events-none aria-disabled:opacity-65 has-[input:focus-visible]:border-ring has-[input:focus-visible]:ring-3 has-[input:focus-visible]:ring-ring/50",
        )}
      >
        {isUploading ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Camera aria-hidden className="size-4" />}
        {isUploading ? "올리는 중..." : uploadLabel}
        <input
          id={inputId}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          aria-disabled={isUploading}
          // 업로드 중에는 파일 창을 열지 않는다. `disabled` 를 주면 키보드로 이 입력에 있던 포커스가 body 로 떨어진다.
          onClick={(event) => {
            if (isUploading) event.preventDefault();
          }}
          onChange={(event) => void handleFileChange(event)}
        />
      </Label>
      <Button type="button" variant="outline" size="sm" onClick={() => void handlePick()}>
        <Images aria-hidden />
        생성한 이미지에서 고르기
      </Button>
    </div>
  );
}
