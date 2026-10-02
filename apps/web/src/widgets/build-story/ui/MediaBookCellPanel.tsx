import { Button, buttonVariants } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { Switch } from "@ai-character-chat/ui/components/switch";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Camera, ChevronRight, Copy, ImageOff, Images, Loader2, X } from "lucide-react";
import { useId, useState, type ChangeEvent } from "react";
import { toast } from "sonner";

import { toMediaNameTag } from "@/entities/media-book";
import {
  cellImageRefusalMessage,
  countCharacters,
  findCell,
  findNextIncompleteCell,
  isIncompleteCell,
  MAX_MEDIA_BOOK_SITUATION_LENGTH,
  MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH,
  removeCell,
  setCellImage,
  toUsedAssetLabels,
  updateCell,
  type MediaBookCellImage,
  type MediaBookCellTextPatch,
  type MediaBookCellValues,
} from "@/features/build-story";
import { MediaBookConfirmModal } from "@/features/edit-media-book";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";
import { FOCUS_WITHIN_RING_CLASSNAME } from "@/shared/ui/focusWithinRing";

import { toCellKey, type MediaBookPosition } from "./MediaBookGrid";
import { clampCharacters } from "../lib/clampCharacters";
import { copyMediaTag } from "../lib/copyMediaTag";
import { useMediaBookEditor } from "../model/useMediaBookEditor";
import { useMediaBookThumbnails } from "../model/useMediaBookThumbnails";

type MediaBookCellPanelProps = {
  id: string;
  position: MediaBookPosition;
  onClose: () => void;
  /** 누른 버튼이 사라질 때(비우기 뒤) 포커스를 표의 그 칸으로 돌려준다. */
  onReturnFocus: () => void;
  /** "다음 미완성 칸" 으로 고른 칸을 연다. */
  onSelectNext: (position: MediaBookPosition) => void;
  /** 더 갈 미완성 칸이 없을 때 그 이유를 말하는 진척 한 줄의 id. */
  progressId: string;
};

// 미리보기 상자의 긴 변 상한(px). 세로로 긴 그림이 패널을 길게 늘이지 않게 폭을 비율로 줄인다.
const PREVIEW_MAX_HEIGHT_PX = 256;
const PREVIEW_MAX_WIDTH_PX = 192;

/** 칸 이미지를 바꾼 뒤 띄우는 되돌리기 토스트. id 가 하나라 연달아 바꾸면 쌓이지 않고 마지막 교체만 되돌린다. */
export const MEDIA_BOOK_IMAGE_UNDO_TOAST_ID = "media-book-image-undo";
/** 상세 본문의 첫 행동 줄(이미지 넣기·바꾸기 버튼 묶음)을 찾는 선택자. 칸을 고른 뒤 스크롤이 이 줄까지 화면에 둔다. */
export const MEDIA_BOOK_FIRST_ACTION_SELECTOR = "[data-media-book-first-action]";
// 기본 4초는 바뀐 이미지를 확인하고 되돌리기를 누르기에 짧다.
const UNDO_TOAST_DURATION_MS = 8000;

/**
 * 배치표에서 고른 칸의 상세. 배치표 바로 아래에 펼친다(모달이 아니다 — 칸을 바꿔 가며 연달아 채우는 작업이라 표가
 * 계속 보여야 한다). 머리(썸네일·이름·표기)는 칸을 바꿔도 그대로 두고 본문만 칸마다 새로 그린다 — 업로드 중 표시 같은
 * 칸별 상태가 다른 칸으로 넘어가지 않게 하면서, 머리의 버튼에 있던 포커스가 칸을 바꿀 때 사라지지 않게 한다.
 * 빈 칸이면 이미지 넣기만, 채운 칸이면 이미지 바꾸기·상황 설명·해금 힌트·노출 제외·비우기.
 */
export function MediaBookCellPanel({
  id,
  position,
  onClose,
  onReturnFocus,
  onSelectNext,
  progressId,
}: MediaBookCellPanelProps) {
  const { mediaBook, getMediaBook, commit } = useMediaBookEditor();
  const thumbnails = useMediaBookThumbnails();
  const person = mediaBook.people.find((item) => item.id === position.personId);
  const scene = mediaBook.scenes.find((item) => item.id === position.sceneId);
  const cell = findCell(mediaBook, position.personId, position.sceneId);
  if (!person || !scene) return null;

  const cellName = `${person.name} · ${scene.name}`;
  const tag = toMediaNameTag(person.name, scene.name);
  const headingId = `${id}-heading`;
  const hasNextIncomplete = findNextIncompleteCell(mediaBook, position) !== undefined;
  // 비활성인데 지금 칸이 미완성이면 진척 줄만으로는 "미완성 칸이 남았는데 왜 못 가나" 로 들린다 — 이유를 덧붙인다.
  const isOnlyIncompleteHere = !hasNextIncomplete && isIncompleteCell(mediaBook, position);
  const onlyHereId = `${id}-only-incomplete`;
  const nextDescribedBy = isOnlyIncompleteHere ? `${progressId} ${onlyHereId}` : progressId;

  function focusHeading() {
    document.getElementById(headingId)?.focus({ preventScroll: true });
  }

  function handleNext() {
    // 비활성이어도 `disabled` 로 막지 않는다 — 누르는 순간 포커스가 body 로 떨어져, 키보드로 연달아 누르던 사람이
    // 처음부터 Tab 을 다시 시작해야 한다.
    const next = findNextIncompleteCell(getMediaBook(), position);
    if (next) onSelectNext(next);
  }

  function handleImageChange(image: MediaBookCellImage) {
    // 업로드를 기다리는 동안 다른 칸이 채워졌을 수 있다 — 그 순간의 값 위에 쓴다.
    const before = findCell(getMediaBook(), position.personId, position.sceneId);
    // 지금 이미지를 다시 골랐으면 바뀌는 것이 없다(저장도 되돌리기도 띄우지 않는다).
    if (before?.imageAssetId === image.assetId) return;
    // 업로드를 기다리는 사이 이 칸의 인물·장면이 지워졌으면 거절된다(없는 축을 가리키는 칸을 만들지 않는다).
    const result = setCellImage(getMediaBook(), position.personId, position.sceneId, image, () => crypto.randomUUID());
    if (!result.ok) {
      toast.error(`${cellImageRefusalMessage(result.reason)}.`);
      return;
    }
    commit(result.mediaBook);
    if (before) offerUndo(before, image.assetId);
  }

  /** 확인 없이 바꾸는 대신 직전 이미지 하나로 되돌릴 길을 둔다 — 반복해서 채우는 작업이 확인 창으로 느려지지 않게. */
  function offerUndo(previous: MediaBookCellValues, replacedWith: string) {
    toast(`${cellName} 칸의 이미지를 바꿨어요.`, {
      id: MEDIA_BOOK_IMAGE_UNDO_TOAST_ID,
      duration: UNDO_TOAST_DURATION_MS,
      // sonner 의 기본 동작 버튼은 밝은 면·작은 반경·다크에서 안 보이는 포커스라 이 앱의 버튼을 넘긴다. 토스트 면이
      // popover 라 outline 의 hover 채움(muted)이 사라지므로 secondary 로 올린다.
      action: (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto hover:bg-secondary"
          onClick={() => {
            // 포커스가 토스트를 떠나면 sonner 가 토스트에 들어오기 전 자리(대개 방금 누른 고르기 버튼)로 돌려준다 —
            // 마우스든 Alt+T 키보드든 같다. 그래서 아래에서 칸으로 옮겨도 그 자리가 있으면 곧바로 그리로 간다. 칸으로
            // 옮기는 것은 돌려줄 자리가 없을 때(포커스가 body 였을 때)를 위해서다 — 버튼이 토스트와 함께 사라지며
            // 포커스가 body 로 떨어지지 않게 표의 그 칸에 둔다(화면은 움직이지 않게).
            document
              .querySelector<HTMLElement>(`[data-media-book-cell="${toCellKey(position)}"]`)
              ?.focus({ preventScroll: true });
            toast.dismiss(MEDIA_BOOK_IMAGE_UNDO_TOAST_ID);
            undoImageChange(previous, replacedWith);
          }}
        >
          되돌리기
        </Button>
      ),
    });
  }

  function undoImageChange(previous: MediaBookCellValues, replacedWith: string) {
    // 그 사이 이 칸을 또 바꿨거나 비웠으면 지금 값을 덮지 않는다.
    const current = findCell(getMediaBook(), previous.personId, previous.sceneId);
    const result =
      current?.imageAssetId === replacedWith
        ? setCellImage(
            getMediaBook(),
            previous.personId,
            previous.sceneId,
            {
              assetId: previous.imageAssetId,
              imageUrl: previous.imageUrl,
              imageWidth: previous.imageWidth,
              imageHeight: previous.imageHeight,
            },
            () => crypto.randomUUID(),
          )
        : undefined;
    if (!result?.ok) {
      toast(`${cellName} 칸이 그 뒤에 바뀌어서 되돌리지 않았어요.`);
      return;
    }
    commit(result.mediaBook);
    toast.success(`${cellName} 칸을 원래 이미지로 되돌렸어요.`);
  }

  function handlePatch(patch: MediaBookCellTextPatch) {
    if (cell) commit(updateCell(getMediaBook(), cell.id, patch));
  }

  async function handleClear() {
    if (!cell) return;
    const trigger = document.activeElement;
    const isConfirmed = await MediaBookConfirmModal.call({
      title: "이 칸을 비울까요?",
      description: "이미지와 상황 설명·해금 힌트가 함께 지워져요. 글 속 표기는 그대로 남고 화면에는 빈칸이 돼요.",
      confirmLabel: "비우기",
      // 취소면 "이 칸 비우기" 버튼이 그대로라 그리로, 비웠으면 그 버튼이 빈 칸 화면으로 바뀌며 사라지므로 표의 칸으로.
      onRestoreFocus: () => {
        if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
        else onReturnFocus();
      },
    });
    if (isConfirmed) commit(removeCell(getMediaBook(), cell.id));
  }

  const imageButtonsProps = {
    cellName,
    currentAssetId: cell?.imageAssetId,
    getUsedAssetLabels: () => toUsedAssetLabels(getMediaBook(), position),
    // 빈 칸을 채우면 누른 버튼이 빈 칸 본문째 사라진다 — 포커스를 언제나 남는 상세 제목으로 보낸다. 입력칸으로 보내면
    // 폰에서 키보드가 예고 없이 올라온다.
    onTriggerGone: focusHeading,
    onImageChange: handleImageChange,
  };

  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className={cn(
        "flex flex-col gap-4 rounded-xl border border-border p-4",
        // 키보드로 칸을 열면 포커스가 제목으로 온다. 제목 자체에는 링을 그리지 않고 상세 윤곽에 하우스 포커스
        // 레시피를 건다 — 불투명 보더가 대비를 지고 링이 어디가 열렸는지 보여 준다.
        "has-[h3:focus-visible]:border-ring has-[h3:focus-visible]:ring-3 has-[h3:focus-visible]:ring-ring/50",
      )}
    >
      {/* 칸을 고르면 이 머리가 화면에 들어오게 스크롤한다. 위쪽 여유는 상세의 안쪽 여백(16px) + 숨 쉴 자리(8px)라
          상세 윤곽의 윗변까지 보인다. 좁은 화면은 페이지가 상단바(56px) 밑으로 스크롤되므로 그 높이를 더한다. */}
      <div id={`${id}-head`} className="flex scroll-mt-20 items-start gap-3 lg:scroll-mt-6">
        <CellThumbnail imageUrl={cell ? thumbnails.resolveUrl(cell.imageAssetId, cell.imageUrl) : undefined} hasImage={!!cell} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-start justify-between gap-2">
            {/* 키보드로 칸을 열면 포커스가 여기로 온다(상세가 표 아래 화면 밖에 열려도 따라가게). */}
            <h3 id={headingId} tabIndex={-1} className="truncate text-lg font-semibold text-foreground focus-visible:outline-none">
              {cellName}
            </h3>
            <Button type="button" variant="ghost" size="icon-sm" aria-label="칸 상세 닫기" onClick={onClose}>
              <X aria-hidden />
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <p className="text-xs break-all text-muted-foreground">{tag}</p>
            <Button type="button" variant="ghost" size="xs" aria-label={`${tag} 표기 복사`} onClick={() => void copyMediaTag(tag)}>
              <Copy aria-hidden />
              표기 복사
            </Button>
            {/* 머리는 칸을 바꿔도 그대로라 연달아 눌러도 포커스가 이 버튼에 남는다. */}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="ml-auto aria-disabled:opacity-65"
              aria-disabled={!hasNextIncomplete}
              aria-describedby={hasNextIncomplete ? undefined : nextDescribedBy}
              onClick={handleNext}
            >
              다음 미완성 칸
              <ChevronRight aria-hidden />
            </Button>
            {isOnlyIncompleteHere && (
              <span id={onlyHereId} className="sr-only">
                남은 미완성 칸은 이 칸뿐이에요
              </span>
            )}
          </div>
        </div>
      </div>

      <CellBody key={toCellKey(position)} cell={cell} imageButtonsProps={imageButtonsProps} onPatch={handlePatch} onClear={() => void handleClear()} />
    </section>
  );
}

type CellBodyProps = {
  cell: MediaBookCellValues | undefined;
  imageButtonsProps: CellImageButtonsProps;
  onPatch: (patch: MediaBookCellTextPatch) => void;
  onClear: () => void;
};

/** 칸마다 새로 그리는 본문. 부모가 칸 자리로 `key` 를 줘 칸별 상태(업로드 중 표시)가 다른 칸으로 넘어가지 않는다. */
function CellBody({ cell, imageButtonsProps, onPatch, onClear }: CellBodyProps) {
  if (cell) return <FilledCellFields cell={cell} imageButtonsProps={imageButtonsProps} onPatch={onPatch} onClear={onClear} />;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm break-keep text-muted-foreground">
        아직 이미지가 없는 칸이에요. 이미지를 넣으면 상황 설명과 해금 힌트를 적을 수 있어요.
      </p>
      {/* 버튼 묶음이 상세 폭으로 늘어나지 않게 — 채운 칸의 같은 버튼과 폭을 맞춘다. */}
      <div className="self-start">
        <CellImageButtons {...imageButtonsProps} />
      </div>
    </div>
  );
}

type CellThumbnailProps = { imageUrl: string | undefined; hasImage: boolean };

/** 머리의 48px 썸네일 — 상세를 화면 위로 올려 표가 안 보여도 어느 칸인지 이름과 함께 알려 준다. 이름은 옆 제목이 진다. */
function CellThumbnail({ imageUrl, hasImage }: CellThumbnailProps) {
  if (!hasImage) {
    return (
      <div className="flex size-12 shrink-0 items-center justify-center rounded-md border border-dashed border-input">
        <ImageOff aria-hidden className="size-4 text-muted-foreground" />
      </div>
    );
  }
  return (
    <div className="size-12 shrink-0 overflow-hidden rounded-md border border-foreground/10 bg-muted">
      {!!imageUrl && <img src={imageUrl} alt="" decoding="async" className="size-full object-contain" />}
    </div>
  );
}

type FilledCellFieldsProps = {
  cell: MediaBookCellValues;
  imageButtonsProps: CellImageButtonsProps;
  onPatch: (patch: MediaBookCellTextPatch) => void;
  onClear: () => void;
};

function FilledCellFields({ cell, imageButtonsProps, onPatch, onClear }: FilledCellFieldsProps) {
  const thumbnails = useMediaBookThumbnails();
  // 방금 입력이 상한에서 잘렸는가 — 그 순간에만 도움말 자리에 알린다. 칸마다 본문을 새로 그려 다른 칸으로 넘어가지 않는다.
  const [truncatedField, setTruncatedField] = useState<"situation" | "hint">();
  const imageUrl = thumbnails.resolveUrl(cell.imageAssetId, cell.imageUrl);
  const fieldId = `media-book-cell-${cell.id}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-4">
        <CellPreview imageUrl={imageUrl} width={cell.imageWidth} height={cell.imageHeight} />
        <CellImageButtons {...imageButtonsProps} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${fieldId}-situation`}>상황 설명</Label>
        <Textarea
          id={`${fieldId}-situation`}
          rows={2}
          placeholder="예) 리딩 중 웃음이 터져 대본으로 얼굴을 가린 유나"
          value={cell.situationDescription}
          aria-describedby={`${fieldId}-situation-help`}
          onChange={(event) => {
            const clamped = clampCharacters(event.target.value, MAX_MEDIA_BOOK_SITUATION_LENGTH);
            setTruncatedField(clamped.isTruncated ? "situation" : undefined);
            onPatch({ situationDescription: clamped.value });
          }}
        />
        <LimitedFieldHelp
          id={`${fieldId}-situation-help`}
          help="대화 중 어떤 이미지를 띄울지 AI가 고를 때 이름과 함께 읽어요."
          count={countCharacters(cell.situationDescription)}
          max={MAX_MEDIA_BOOK_SITUATION_LENGTH}
          isTruncated={truncatedField === "situation"}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${fieldId}-hint`}>해금 힌트</Label>
        <Input
          id={`${fieldId}-hint`}
          placeholder="예) 첫 리딩을 끝까지 지켜본 뒤"
          value={cell.unlockHint}
          aria-describedby={`${fieldId}-hint-help`}
          onChange={(event) => {
            const clamped = clampCharacters(event.target.value, MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH);
            setTruncatedField(clamped.isTruncated ? "hint" : undefined);
            onPatch({ unlockHint: clamped.value });
          }}
        />
        <LimitedFieldHelp
          id={`${fieldId}-hint-help`}
          help="아직 못 본 사람의 이미지 보관함에 흐린 이미지와 함께 보여요. 비우면 자물쇠만 보여요."
          count={countCharacters(cell.unlockHint)}
          max={MAX_MEDIA_BOOK_UNLOCK_HINT_LENGTH}
          isTruncated={truncatedField === "hint"}
        />
      </div>

      <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <Label htmlFor={`${fieldId}-exclude`}>대화 중에는 띄우지 않기</Label>
          <p className="text-sm break-keep text-muted-foreground">
            켜면 AI가 대화 중에 이 이미지를 고르지 않아요. 글 속 표기로 넣은 자리에는 그대로 보여요.
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

type LimitedFieldHelpProps = { id: string; help: string; count: number; max: number; isTruncated: boolean };

/**
 * 글자 상한이 있는 입력칸 아래 줄 — 도움말과 글자 수. 상한에 닿으면 글자 수를 굵게 올리고(오류가 아니라 꽉 찬
 * 상태라 경고색을 쓰지 않는다), 입력이 잘린 그 순간에는 도움말 자리에 잘렸다고 알린다. 알림 자리는 늘 있어야
 * 스크린리더가 바뀐 글을 읽으므로 비워 둔 채 둔다.
 */
function LimitedFieldHelp({ id, help, count, max, isTruncated }: LimitedFieldHelpProps) {
  return (
    <p id={id} className="flex justify-between gap-2 text-xs text-muted-foreground">
      <span className="break-keep">
        <span hidden={isTruncated}>{help}</span>
        <span role="status" className="text-foreground">
          {isTruncated ? `${max}자까지 들어가요. 넘친 글자는 넣지 않았어요.` : ""}
        </span>
      </span>
      <span className={cn("shrink-0 tabular-nums", count >= max && "font-medium text-foreground")}>
        {count}/{max}
      </span>
    </p>
  );
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
      {!!imageUrl && <img src={imageUrl} alt="" decoding="async" className="size-full object-contain" />}
    </div>
  );
}

type CellImageButtonsProps = {
  /** 고르기 모달 설명에 넣는 칸 이름(`세빈 · 굳은 순간`). */
  cellName: string;
  /** 칸에 지금 들어 있는 이미지. 없으면 빈 칸이다. */
  currentAssetId: string | undefined;
  /** 다른 칸에서 쓰는 이미지 표식. 고르기를 여는 순간의 폼으로 만든다. */
  getUsedAssetLabels: () => ReadonlyMap<string, string>;
  /** 누른 버튼이 결과로 사라졌을 때(빈 칸을 채운 뒤) 포커스를 둘 곳으로 옮긴다. */
  onTriggerGone: () => void;
  onImageChange: (image: MediaBookCellImage) => void;
};

/** 칸 이미지를 올리거나 생성한 이미지에서 고른다. 채운 칸이면 같은 칸에 이미지만 바꾼다. */
function CellImageButtons({
  cellName,
  currentAssetId,
  getUsedAssetLabels,
  onTriggerGone,
  onImageChange,
}: CellImageButtonsProps) {
  const thumbnails = useMediaBookThumbnails();
  const [isUploading, setIsUploading] = useState(false);
  const inputId = useId();
  const isReplacing = currentAssetId !== undefined;
  const uploadLabel = isReplacing ? "다른 파일로 바꾸기" : "파일 올리기";

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target;
    const file = input.files?.[0];
    input.value = "";
    if (!file || isUploading) return;
    setIsUploading(true);
    try {
      const assetId = await uploadAsset(file, "situational-image");
      // 빈 칸이었다면 이 입력은 채운 뒤 사라진다. 올리는 동안 사용자가 다른 곳으로 옮겨 가지 않았을 때만, 사라지기
      // 전에 포커스를 남는 자리로 옮긴다.
      const shouldMoveFocus = !isReplacing && document.activeElement === input;
      onImageChange({ assetId, imageUrl: thumbnails.rememberUploadedFile(assetId, file) });
      if (shouldMoveFocus) onTriggerGone();
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
    } finally {
      setIsUploading(false);
    }
  }

  async function handlePick() {
    const trigger = document.activeElement;
    const picked = await GeneratedImagePickerModal.call({
      title: "생성한 이미지에서 고르기",
      description: isReplacing
        ? `고른 이미지로 ${cellName} 칸의 이미지를 바꿔요.`
        : `${cellName} 칸에 넣을 이미지를 골라요.`,
      currentAssetId,
      usedAssetLabels: getUsedAssetLabels(),
      // 모달이 완전히 닫힌 뒤에 옮긴다(결과를 받은 직후에는 닫히는 중인 모달이 포커스를 도로 가둔다). 채운 칸이면 이
      // 버튼이 남아 그리로, 빈 칸을 채웠으면 버튼이 사라져 상세 제목으로.
      onRestoreFocus: () => {
        if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
        else onTriggerGone();
      },
    });
    if (!picked) return;
    thumbnails.rememberPickedUrl(picked.assetId, picked.imageUrl);
    onImageChange({ assetId: picked.assetId, imageUrl: picked.imageUrl });
  }

  return (
    // 칸을 고른 뒤 스크롤이 이 묶음의 아래 끝을 화면 바닥에 맞출 때 남기는 숨 쉴 자리(8px).
    <div data-media-book-first-action className="flex scroll-mb-2 flex-col gap-2">
      <Label
        htmlFor={inputId}
        aria-disabled={isUploading}
        className={cn(
          buttonVariants({ variant: "outline", size: "sm" }),
          "cursor-pointer aria-disabled:pointer-events-none aria-disabled:opacity-65",
          FOCUS_WITHIN_RING_CLASSNAME,
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
