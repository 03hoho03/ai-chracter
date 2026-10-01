import { Button } from "@ai-character-chat/ui/components/button";
import { ImagePlus } from "lucide-react";
import type { RefObject } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { toMediaNameTag } from "@/entities/media-book";
import { insertMediaTag, type MediaTagFieldPath, type StoryBuilderFormValues } from "@/features/build-story";
import { MediaTagPickerModal, type MediaTagPickerGroup } from "@/features/edit-media-book";

import { useMediaBookThumbnails } from "./MediaBookThumbnailsProvider";

type MediaTagInsertButtonProps = {
  name: MediaTagFieldPath;
  /** 어느 입력칸의 버튼인지 스크린리더가 가를 이름(예: "프롤로그"). 한 화면에 이 버튼이 여럿이다. */
  fieldLabel: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
};

/**
 * 태그가 그림이 되는 글 옆의 "이미지 넣기". 미디어 북에서 칸을 고르면 입력창의 커서 자리에 그 칸의 이름 형태
 * 태그를 넣는다. 입력창은 `register` 로 묶여 있어 `setValue` 가 화면 값과 자동저장을 함께 움직인다.
 */
export function MediaTagInsertButton({ name, fieldLabel, textareaRef }: MediaTagInsertButtonProps) {
  const { control, getValues, setValue } = useFormContext<StoryBuilderFormValues>();
  const mediaBook = useWatch({ control, name: "mediaBook" });
  const thumbnails = useMediaBookThumbnails();

  async function handleClick() {
    // 모달이 열리면 입력창이 흐려지지만 선택 범위는 남는다 — 여는 순간의 값을 기준으로 삼는다.
    const textarea = textareaRef.current;
    const text = textarea?.value ?? getValues(name) ?? "";
    const selection = {
      text,
      selectionStart: textarea?.selectionStart ?? text.length,
      selectionEnd: textarea?.selectionEnd ?? text.length,
    };
    const picked = await MediaTagPickerModal.call({ groups: toPickerGroups(mediaBook, thumbnails.resolveUrl) });
    if (!picked) return;
    const next = insertMediaTag(selection, toMediaNameTag(picked.personName, picked.sceneName));
    setValue(name, next.text, { shouldDirty: true });
    requestAnimationFrame(() => {
      textarea?.focus();
      textarea?.setSelectionRange(next.selectionStart, next.selectionEnd);
    });
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-label={`${fieldLabel}에 이미지 넣기`}
      onClick={() => void handleClick()}
      className="text-muted-foreground"
    >
      <ImagePlus aria-hidden />
      이미지 넣기
    </Button>
  );
}

function toPickerGroups(
  mediaBook: StoryBuilderFormValues["mediaBook"],
  resolveUrl: (assetId: string, fallbackUrl?: string) => string | undefined,
): MediaTagPickerGroup[] {
  return mediaBook.people
    .map((person) => ({
      personName: person.name,
      cells: mediaBook.scenes.flatMap((scene) => {
        const cell = mediaBook.cells.find((item) => item.personId === person.id && item.sceneId === scene.id);
        if (!cell) return [];
        return [{ cellId: cell.id, sceneName: scene.name, imageUrl: resolveUrl(cell.imageAssetId, cell.imageUrl) }];
      }),
    }))
    .filter((group) => group.cells.length > 0);
}
