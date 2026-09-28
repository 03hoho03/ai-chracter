import { useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { ImageOff, Images, X } from "lucide-react";
import { Controller, useFormContext } from "react-hook-form";

import type { GenerateImagesFormValues } from "../model/schema";
import { useGenerateImagesSubmit, type PickedReferenceImage } from "../model/useGenerateImagesSubmit";

const LABEL_ID = "generate-images-reference-label";
const NOTICE_ID = "generate-images-reference-notice";
const CROP_HINT_ID = "generate-images-reference-crop-hint";
const ERROR_ID = "generate-images-reference-error";

// 프롬프트 박스 **밖**, 바로 아래의 별도 행이다. 박스 안 하단 줄은 이미 클로버 잔량과 생성 버튼이라
// 넣을 자리가 없고, 옵션 열(우열)에 두면 lg 미만에서 바텀시트 뒤로 숨어 참조가 붙어 있다는 사실을
// 잊은 채 생성하게 된다. 이 자리는 모든 폭에서 프롬프트와 함께 보인다.
//
// 참조를 쓸 수 없으면(고른 모델이 참조를 안 받으면) 행과 안내 문장을 통째로 숨긴다 — 보내지 않는
// 이미지에 대한 고지는 필요 없다. 그 사이 폼에 남은 참조는 `formToServer`가 싣지 않는다.
export function GenerateImagesReferenceField() {
  const { control } = useFormContext<GenerateImagesFormValues>();
  const { isReferenceEnabled, onPickReference } = useGenerateImagesSubmit();
  // 피커가 준 presigned URL은 만료되는 표시 전용 값이라 폼이 아니라 여기 둔다. 어느 이미지의
  // 미리보기인지 id를 함께 들고 있다가 폼 값과 같을 때만 보인다 — 서버 오류로 참조가 비워지거나
  // 다른 이미지로 바뀌면 옛 미리보기가 저절로 떨어진다.
  const [preview, setPreview] = useState<PickedReferenceImage>();
  const pickButtonRef = useRef<HTMLButtonElement>(null);

  if (!isReferenceEnabled) return null;

  return (
    <Controller
      control={control}
      name="reference"
      render={({ field, fieldState }) => {
        const reference = field.value;
        const errorMessage = fieldState.error?.message;
        const describedByIds = [
          errorMessage !== undefined && ERROR_ID,
          NOTICE_ID,
          reference !== null && CROP_HINT_ID,
        ]
          .filter(Boolean)
          .join(" ");
        const previewUrl =
          reference !== null && preview?.assetId === reference.assetId ? preview.imageUrl : undefined;

        async function handlePick() {
          const picked = await onPickReference();
          if (picked === undefined) return;
          setPreview(picked);
          field.onChange({ assetId: picked.assetId });
        }

        function handleRemove() {
          // 빼기 버튼은 이 조작으로 사라진다 — 상태를 바꾸기 **전에** 남는 버튼으로 포커스를 옮겨야
          // 키보드 사용자가 <body>로 떨어지지 않는다.
          pickButtonRef.current?.focus();
          field.onChange(null);
        }

        return (
          <div role="group" aria-labelledby={LABEL_ID} className="flex flex-col gap-1.5">
            <span id={LABEL_ID} className="text-sm leading-none font-medium">
              참조 이미지
            </span>
            <div className="flex items-center gap-3">
              {reference !== null && (
                // 빼기 버튼이 모서리 밖으로 나가므로 `overflow-hidden`은 안쪽 웰에만 건다
                // (`GeneratedImageField`와 같은 구조).
                <div className="relative size-16 shrink-0">
                  {/* 정사각 `object-cover` — 서버도 가운데 정사각형 위주로 반영한다. 다만 그 한 변을
                      계약이 정의하지 않으므로 옆 보조 문구도 이 네모가 정확히 반영 영역이라고 말하지
                      않는다. */}
                  <div className="size-full overflow-hidden rounded-lg border border-foreground/10 bg-muted motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-150">
                    {previewUrl ? (
                      <img
                        src={previewUrl}
                        alt="고른 참조 이미지"
                        decoding="async"
                        className="size-full object-cover"
                      />
                    ) : (
                      <div className="flex size-full items-center justify-center text-muted-foreground">
                        <ImageOff aria-hidden className="size-5" />
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={handleRemove}
                    aria-label="참조 이미지 빼기"
                    className="absolute -top-2 -right-2 inline-flex size-6 items-center justify-center rounded-full border border-input bg-background text-muted-foreground hover:text-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <X aria-hidden className="size-3.5" />
                  </button>
                </div>
              )}
              {/* 버튼과 보조 문구를 한 열로 묶어 미리보기 오른쪽에 둔다 — 좁은 폭에서도 행이 가로로
                  넘치지 않고 문구만 열 안에서 접힌다(`min-w-0`). */}
              <div className="flex min-w-0 flex-col items-start gap-1.5">
                {/* 솔리드 채움은 생성 버튼 하나뿐이라 outline이다. 라벨만 바꾸고 같은 엘리먼트를
                    유지해 빼기 뒤 포커스가 돌아올 자리가 사라지지 않게 한다. */}
                <Button
                  ref={pickButtonRef}
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-invalid={errorMessage !== undefined}
                  aria-describedby={describedByIds}
                  onClick={() => void handlePick()}
                >
                  <Images aria-hidden />
                  {reference === null ? "내 이미지에서 고르기" : "다른 이미지로 바꾸기"}
                </Button>
                {/* 반영 영역은 고른 이미지를 봐야 뜻이 서므로 고른 뒤에만 미리보기 옆에 둔다. */}
                {reference !== null && (
                  <p id={CROP_HINT_ID} className="break-keep text-xs text-muted-foreground">
                    가운데 부분 위주로 반영돼요.
                  </p>
                )}
                {/* 서버가 고른 참조를 찾지 못했을 때만 생긴다(그 사이 보관함에서 지워진 경우 등). 고칠
                    행동이 이 버튼이라 고지 문장 아래가 아니라 버튼 바로 밑에 둔다. 따로 지우지 않는다 —
                    이 오류는 제출 뒤에만 생기고, 제출을 한 번 마친 폼은 값이 바뀔 때마다 리졸버로 그
                    필드를 다시 검증해 통과하면 오류를 지운다(react-hook-form 기본 `reValidateMode: "onChange"`).
                    다음 제출도 검증 결과로 오류 전체를 갈아 끼우므로 남지 않는다. */}
                {errorMessage !== undefined && (
                  <p id={ERROR_ID} role="alert" className="break-keep text-xs text-destructive-text">
                    {errorMessage}
                  </p>
                )}
              </div>
            </div>
            {/* 전송·보관 고지는 전송 **전**에 보이는 유일한 자리라 고른 뒤가 아니라 행과 함께 늘
                보인다. 보존 기한은 정해지지 않았으므로 약속하지 않는다. */}
            <p id={NOTICE_ID} className="break-keep text-xs text-muted-foreground">
              참조 이미지는 이미지 생성 서버로 보내져요. 운영 정책에 맞지 않는 참조 이미지는 검토를 위해
              보관될 수 있어요.
            </p>
          </div>
        );
      }}
    />
  );
}
