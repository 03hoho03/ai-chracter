import { Label } from "@ai-character-chat/ui/components/label";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Controller, useFormContext, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import {
  IMAGE_ASPECT_RATIO_LABEL,
  IMAGE_ASPECT_RATIOS,
  IMAGE_COUNT_OPTIONS,
  isImageAspectRatio,
  type GenerateImagesFormValues,
} from "../model/schema";

// 비율 칩의 도형 치수 — 비율 문자열("16:9")을 그때그때 나눠 계산한다. IMAGE_ASPECT_RATIOS별로
// 임의값 클래스(w-[18px]/h-[14px] 등)를 6종 만드는 것보다 순수 함수 하나가 더 단순하고, 배열이
// 늘어도 여기 손댈 곳이 없다 — 그래서 style={{width, height}} 인라인이 맞는 자리다.
function getAspectRatioShapeSize(ratio: string): { width: number; height: number } {
  const LONG_SIDE_PX = 18;
  // noUncheckedIndexedAccess — split 결과의 각 자리는 string | undefined다.
  const [widthPart, heightPart] = ratio.split(":");
  const w = Number(widthPart ?? "");
  const h = Number(heightPart ?? "");
  if (w >= h) {
    return { width: LONG_SIDE_PX, height: Math.round((LONG_SIDE_PX * h) / w) };
  }
  return { width: Math.round((LONG_SIDE_PX * w) / h), height: LONG_SIDE_PX };
}

// 비율·개수는 Select가 아니라 ToggleGroup(칩)이다. 모델 Select는
// 2026-09-14 브라우저 피드백으로 제거했다 — 값이 v1 하나뿐이라 고를 게 없다. model 값 자체는
// 여전히 GenerateImagesFormProvider가 목록 로드 후 reset()으로 채운다(그 로직은 그대로 둔다).
export function GenerateImagesOptionsFields() {
  const { control } = useFormContext<GenerateImagesFormValues>();
  const { data: models } = useImageModelsQuery();
  const selectedModelId = useWatch({ control, name: "model" });
  const selectedModel = models?.find((model) => model.id === selectedModelId);
  const supportedRatios = new Set<string>(
    selectedModel?.supportedAspectRatios ?? IMAGE_ASPECT_RATIOS,
  );
  const isRatioRestricted =
    selectedModel != null && selectedModel.supportedAspectRatios.length < IMAGE_ASPECT_RATIOS.length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label>비율</Label>
        <Controller
          control={control}
          name="aspectRatio"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={field.value}
              onValueChange={(value) => {
                // radix 단일 토글은 선택된 항목을 다시 누르면 ""를 흘려보낸다(ContentTypeToggle.tsx:13-18).
                if (!isImageAspectRatio(value)) return;
                field.onChange(value);
              }}
              aria-label="비율"
              // w-full — 프리미티브 기본값 w-fit이 그리드를 콘텐츠 폭(176px)으로 수축시켜 칩이
              // 53px로 쪼그라든다(브라우저 실측). 우열 가용폭 287px를 다 쓰게 덮는다.
              // items-stretch — 기본값 items-center면 도형 높이가 비율마다 달라 같은 행 칩 높이가
              // 들쭉날쭉해진다(실측 59/55/59). stretch로 같은 행 칩 높이를 맞춘다.
              className="grid grid-cols-3 w-full items-stretch"
            >
              {IMAGE_ASPECT_RATIOS.map((ratio) => {
                const shapeSize = getAspectRatioShapeSize(ratio);
                return (
                  <ToggleGroupItem
                    key={ratio}
                    value={ratio}
                    disabled={!supportedRatios.has(ratio)}
                    aria-label={IMAGE_ASPECT_RATIO_LABEL[ratio]}
                    // DESIGN.md:262 variant="list" 레시피 — 화면당 primary 솔리드 채움은 CTA 하나뿐이어야
                    // 하는데 이 칩과 아래 개수 칩까지 솔리드면 셋이 된다. 틴트로 내려 예산을 CTA에 남긴다.
                    // h-auto + py-2 — 도형+라벨 2단은 size="sm"의 h-8에 안 들어간다. px-3/text-xs 등
                    // sm의 나머지 값은 그대로 상속한다.
                    // rounded-lg — 프리미티브 기본 pill을 덮는다. ~90×59 도형 타일에 pill을 주면 원으로
                    // 보인다(DESIGN.md:262가 신고 모달 352×44 행에 쓴 것과 같은 근거: 키 큰 항목엔 pill이
                    // 아니라 lg). 아래 개수 칩도 같은 반경으로 맞춘다 — 이 패널은 필터 바가 아니라
                    // 옵션 패널이라 칩 어휘(pill)를 쓰지 않는다.
                    className="h-auto flex-col gap-1 rounded-lg py-2 data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15"
                  >
                    {/* 도형을 18×18 고정 박스로 감싼다 — 도형 높이가 비율마다 다르면(18/14/10)
                        아래 라벨의 세로 위치가 칩마다 달라진다(2026-09-14 사용자 피드백).
                        박스가 긴 변(18px)만큼 자리를 늘 차지하므로 라벨은 어느 칩에서든 같은
                        높이에 선다. 박스는 중앙 정렬이라 도형 자체도 가로·세로 가운데에 온다. */}
                    <span aria-hidden className="flex size-4.5 shrink-0 items-center justify-center">
                      {/* border-current로 칩 텍스트 색(비선택 muted-foreground / 선택 primary)을
                          그대로 따라간다 — 별도 색 분기가 필요 없다. */}
                      <span
                        className="block border border-current"
                        style={{ width: shapeSize.width, height: shapeSize.height }}
                      />
                    </span>
                    {ratio}
                  </ToggleGroupItem>
                );
              })}
            </ToggleGroup>
          )}
        />
        {isRatioRestricted && (
          <p className="text-xs text-muted-foreground">이 모델이 지원하는 비율만 선택할 수 있어요</p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>개수</Label>
        <Controller
          control={control}
          name="count"
          render={({ field }) => (
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={String(field.value)}
              onValueChange={(value) => {
                // radix 단일 토글은 선택된 항목을 다시 누르면 ""를 흘려보낸다(ContentTypeToggle.tsx:13-18).
                if (value === "") return;
                field.onChange(Number(value));
              }}
              aria-label="개수"
            >
              {IMAGE_COUNT_OPTIONS.map((count) => (
                <ToggleGroupItem
                  key={count}
                  value={String(count)}
                  // DESIGN.md:262 variant="list" 레시피 — 위 비율 칩과 같은 이유.
                  // rounded-lg — 비율 칩과 반경을 맞춘다. 한때 "32px 텍스트 전용이라 기존 필터 칩
                  // 어휘(pill)를 유지한다"고 갈라 뒀는데, 나란히 놓고 보니 같은 패널의 두 칩 줄이
                  // 다른 반경을 갖는 쪽이 더 어색했다(2026-09-14 사용자 피드백). 필터 바의 칩은
                  // 여전히 pill이다 — 이건 그 어휘를 쓰지 않는 옵션 패널이라는 뜻이다.
                  className="rounded-lg data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15"
                >
                  {count}장
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      </div>
    </div>
  );
}
