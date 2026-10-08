import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { novelKeys, toNovelActionError, type NovelDetailResponse } from "@/entities/novel";

import { useUpdateNovelInfoMutation } from "../api/useUpdateNovelInfoMutation";

type NovelCoverActionsProps = {
  novel: NovelDetailResponse;
  /** 내가 생성해 둔 이미지 중 하나를 고르게 하고 고른 이미지 id 를 돌려준다(닫으면 `undefined`). 이미지 피커는 다른
   * 기능의 모달이라 화면이 넣어 준다(기능끼리 서로 가져다 쓰지 않는다). */
  pickImage: (currentAssetId: string | undefined) => Promise<string | undefined>;
};

/** 표지 바꾸기 — 내가 생성해 둔 이미지 중 하나를 고른다. 생성 이미지 표지일 때만 원작 썸네일로 되돌리는 버튼이 옆에
 * 있다. 되돌리면 그 버튼이 사라지므로 포커스를 먼저 "표지 바꾸기"로 옮긴다. */
export function NovelCoverActions({ novel, pickImage }: NovelCoverActionsProps) {
  const queryClient = useQueryClient();
  const mutation = useUpdateNovelInfoMutation();
  const [errorMessage, setErrorMessage] = useState<string | undefined>(undefined);
  const changeButtonRef = useRef<HTMLButtonElement>(null);
  const isSaving = mutation.isPending;

  async function saveCover(coverAssetId: string | null) {
    setErrorMessage(undefined);
    try {
      await mutation.mutateAsync({ novelId: novel.id, body: { coverAssetId } });
    } catch (error) {
      const notice = toNovelActionError(error, "cover");
      if (notice === null) return;
      setErrorMessage(notice.message);
      if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novel.id) });
    }
  }

  async function handleChange() {
    if (isSaving) return;
    const pickedAssetId = await pickImage(novel.cover.assetId ?? undefined);
    if (pickedAssetId === undefined || pickedAssetId === novel.cover.assetId) return;
    await saveCover(pickedAssetId);
  }

  function handleReset() {
    if (isSaving) return;
    changeButtonRef.current?.focus();
    void saveCover(null);
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-1">
        <Button
          ref={changeButtonRef}
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={isSaving}
          className="aria-disabled:opacity-65"
          onClick={() => void handleChange()}
        >
          표지 바꾸기
        </Button>
        {novel.cover.source === "generated" && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-disabled={isSaving}
            className="aria-disabled:opacity-65"
            onClick={handleReset}
          >
            기본 표지로
          </Button>
        )}
      </div>
      {errorMessage !== undefined && (
        <p role="alert" className="text-sm break-keep text-destructive-text">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
