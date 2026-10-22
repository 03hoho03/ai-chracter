import { useRef, type ReactNode } from "react";

import { ImageCropModal } from "@/features/crop-image";
import {
  ILLUSTRATION_CROP_ASPECTS,
  OriginalIllustrationPickerModal,
  type PickedIllustrationImage,
  type PickIllustrationImage,
} from "@/features/edit-novel-chapter";
import { GeneratedImagePickerModal } from "@/features/select-generated-image";

/** 삽화 업로드가 받는 형식. 그림은 올리기 전에 정지 그림 한 장으로 다시 그린다(움직이는 그림은 첫 장면만 남는다). */
const ILLUSTRATION_IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";

/**
 * 보드 화 본문의 붙이기·바꾸기가 쓰는 출처 창 셋 — 기기에서 고르기(숨긴 파일 입력 → 자르기 창, 비율 칩 기본 원본), 내 이미지,
 * 원작 그림. 자르기·내 이미지 창은 화 본문과 다른 기능이라 화 본문이 직접 열 수 없어 이 층이 연다. 파일 입력은 이 층에 하나 두고 돌려준
 * `fileInput` 을 화면에 그려야 한다 — 메뉴 항목에서 열면 메뉴가 닫히며 그 안의 입력도 사라진다.
 *
 * 파일 고르기 창을 닫으면 `cancel` 이 오는 브라우저에서는 `undefined` 로 끝난다. 오지 않는 브라우저에서는 그 약속이 끝나지
 * 않을 뿐 아무 진행도 걸려 있지 않다(본문은 파일을 받은 뒤에야 "올리는 중"이 된다).
 */
export function useIllustrationImagePicker(novelId: string): { pickImage: PickIllustrationImage; fileInput: ReactNode } {
  const inputRef = useRef<HTMLInputElement>(null);
  const resolveFileRef = useRef<((file: File | undefined) => void) | undefined>(undefined);

  function chooseFile(): Promise<File | undefined> {
    // 앞서 열었다가 끝나지 않은 고르기가 있으면 닫는다 — 새 고르기만 답을 받는다.
    resolveFileRef.current?.(undefined);
    return new Promise((resolve) => {
      resolveFileRef.current = resolve;
      const input = inputRef.current;
      if (input === null) {
        resolve(undefined);
        return;
      }
      // React 가 이 입력의 cancel 처리기를 받지 않아 요소에 직접 둔다(대입이라 열 때마다 쌓이지 않는다).
      input.oncancel = () => settleFile(undefined);
      input.click();
    });
  }

  function settleFile(file: File | undefined) {
    const resolve = resolveFileRef.current;
    resolveFileRef.current = undefined;
    resolve?.(file);
  }

  const pickImage: PickIllustrationImage = async (source, { currentAssetId }) => {
    if (source === "generated") {
      const picked = await GeneratedImagePickerModal.call({
        title: "내 이미지에서 고르기",
        description: "생성해 둔 이미지 중 하나를 삽화로 넣어요.",
        currentAssetId,
      });
      return picked === undefined ? undefined : { kind: "asset", assetId: picked.assetId, source: "generated" };
    }
    if (source === "original") {
      const picked = await OriginalIllustrationPickerModal.call({ novelId, currentAssetId });
      return picked === undefined ? undefined : { kind: "asset", assetId: picked.assetId, source: "original" };
    }
    const file = await chooseFile();
    if (file === undefined) return undefined;
    const upload = await ImageCropModal.call({ file, aspect: ILLUSTRATION_CROP_ASPECTS });
    return upload === undefined ? undefined : ({ kind: "file", upload } satisfies PickedIllustrationImage);
  };

  const fileInput = (
    <input
      ref={inputRef}
      type="file"
      accept={ILLUSTRATION_IMAGE_ACCEPT}
      className="sr-only"
      tabIndex={-1}
      aria-hidden
      onChange={(event) => {
        const file = event.target.files?.[0];
        // 같은 파일을 다시 골라도 바뀜이 오도록 비운다.
        event.target.value = "";
        settleFile(file);
      }}
    />
  );

  return { pickImage, fileInput };
}
