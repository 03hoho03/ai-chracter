import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { SlidersHorizontal } from "lucide-react";
import type { ComponentProps } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import type { GenerateImagesFormValues } from "../model/schema";
import { STYLE_SAMPLE_IMAGES } from "../model/styleSampleImages";

// 연 트리거 표식·`aria-expanded`·표시 조건(`lg:hidden`)·`onClick`은 시트를 가진 위젯이 넘기고 여기서는
// 그대로 펼친다 — 이 feature 가 위젯의 표식 이름이나 레이아웃을 몰라도 되게.
type GenerateImagesStyleSummaryButtonProps = Omit<
  ComponentProps<typeof Button>,
  "children" | "variant" | "size" | "aria-label" | "aria-haspopup" | "aria-expanded"
> & { "aria-expanded": boolean };

// 좁은 화면에서 스타일은 옵션 시트 안에 있다. 시트에 숨은 선택을 화면에 드러내지 않으면 사용자가 고른
// 사실을 잊으므로, 고른 스타일과 같은 시트의 비율·개수를 한 줄로 요약해 보이고 누르면 그 시트를 연다.
//
// `outline` 인 이유: 채움이 배경과 같아 `border-input` 한 줄이 컨트롤임을 알린다. 솔리드 채움은 이 화면의
// CTA(생성 버튼) 자리라 여기서 쓰지 않는다.
export function GenerateImagesStyleSummaryButton({
  className,
  ...props
}: GenerateImagesStyleSummaryButtonProps) {
  const { control } = useFormContext<GenerateImagesFormValues>();
  const { data: models } = useImageModelsQuery();
  const [selectedModelId, selectedStyleId, aspectRatio, count] = useWatch({
    control,
    name: ["model", "style", "aspectRatio", "count"],
  });

  const selectedModel = models?.find((model) => model.id === selectedModelId);
  // 고른 모델을 못 찾는 동안도 로딩으로 본다. 목록이 이미 캐시에 있는 재방문에서는 첫 렌더에 목록은
  // 있지만 모델 값은 아직 비어 있다(기본 모델은 프로바이더가 렌더 뒤 효과에서 채운다) — 그 프레임에
  // "스타일 없음"을 보이면 사실과 다르다. "스타일 없음"은 고른 모델에 쓸 수 있는 스타일이 정말 없을 때만이다.
  const isModelsLoading = selectedModel === undefined;
  const styles = selectedModel?.styles ?? [];
  const selectedStyle = styles.find((style) => style.id === selectedStyleId);
  const sample = selectedStyle ? STYLE_SAMPLE_IMAGES[selectedStyle.id] : undefined;
  const styleText =
    selectedStyle?.name ?? (isModelsLoading || styles.some((style) => style.available) ? "스타일" : "스타일 없음");
  // 화면 글자와 접근 이름을 이 문자열 하나에서 만든다 — 따로 조립하면 둘이 어긋날 수 있다.
  const summary = `${styleText} · ${aspectRatio} · ${count}장`;
  // 스타일 이름이 보일 때만 "스타일" 을 앞에 붙인다 — 이름 대신 "스타일"·"스타일 없음" 이 보이는
  // 상태에서 붙이면 같은 낱말을 두 번 읽는다.
  const accessibleName = `${selectedStyle ? "스타일 " : ""}${summary}, 생성 옵션 열기`;

  return (
    <Button
      type="button"
      variant="outline"
      aria-haspopup="dialog"
      aria-label={accessibleName}
      className={cn("h-14 w-full justify-start gap-3 px-2", className)}
      {...props}
    >
      {/* 썸네일 면이 `muted` 가 아니라 `secondary` 인 이유: outline 버튼의 hover 채움이 `bg-muted` 라
          `muted` 웰은 hover 때 버튼 면과 같아져 사라진다. 모델 목록을 기다리는 동안의 펄스는 진행
          표시라 모션 가드를 걸지 않는다. 샘플 아트가 없는 스타일은 빈 칸으로 둔다(서버가 스타일 목록의
          소스라 FE 가 모르는 id 는 정상 상태다). */}
      <span
        aria-hidden
        className={cn(
          "size-10 shrink-0 overflow-hidden rounded-md bg-secondary",
          isModelsLoading && "animate-pulse",
        )}
      >
        {sample ? (
          <img src={sample} alt="" decoding="async" className="size-full object-cover" />
        ) : null}
      </span>
      <span className="min-w-0 truncate">{summary}</span>
      <SlidersHorizontal aria-hidden className="ml-auto text-muted-foreground" />
    </Button>
  );
}
