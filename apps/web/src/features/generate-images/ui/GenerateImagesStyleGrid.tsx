import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import { useId } from "react";
import { Controller, useFormContext, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import type { GenerateImagesFormValues } from "../model/schema";
import { STYLE_SAMPLE_IMAGES } from "../model/styleSampleImages";

type GenerateImagesStyleGridLayout = "rail" | "sheet";

// 그리드 클래스는 놓이는 자리가 고른다. 반응형 접두사는 뷰포트 기준이라, 고정폭 우열에 `sm:`을
// 걸면 lg 이상에서 언제나 그 값이 켜진다 — 그래서 우열은 3열 고정이고, 화면 폭을 그대로 쓰는
// 시트만 `sm:` 에서 4열로 늘린다(넓은 시트에서 3열이면 타일이 커져 시트가 화면을 넘는다).
// `gap-2`는 같은 열의 비율·개수 칩 간격(8px)과 맞춘 값이다 — 한 열 안에서 칩과 타일의 리듬이
// 다르면 두 무리로 읽힌다.
// 실제 타일(아래)과 스켈레톤(로딩 분기)은 반드시 같은 상수를 쓴다 — 그리드 클래스가 갈리면 목록
// 도착 시 레이아웃이 튄다(card-grid 런에서 실측한 문제).
const STYLE_GRID_CLASSNAME: Record<GenerateImagesStyleGridLayout, string> = {
  rail: "grid grid-cols-3 gap-2",
  sheet: "grid grid-cols-3 gap-2 sm:grid-cols-4",
};

// `listbox`/`option`/`aria-selected` 패턴(ColorPicker·IconPicker
// 선례). `radiogroup`이 아니다. 방향키 이동은 구현하지 않는다(두 선례 모두 없다).
//
// 선택은 `border`, 포커스는 `ring` — 둘이 다른 CSS 속성을 쓰므로 ColorPicker.tsx 스와치 className 주석이 기록한
// `--tw-ring-*` 충돌(같은 변수를 공유해 포커스 링이 선택 링을 덮어쓰는 함정)이 원천적으로 없다.
//
// 표면이 둘이다 — 우열은 `background`, 시트는 `SheetContent`(`popover`). 그래서 타일·스켈레톤
// 바탕은 두 표면 모두에서 보이는 `secondary`다(`muted`는 시트 표면과 값이 같아 1.0000:1로
// 사라진다). 이 파일에는 표면 표식이 없어 파일 단위 표면 가드가 못 잡는 자리라 손으로 지킨다.
export function GenerateImagesStyleGrid({ layout }: { layout: GenerateImagesStyleGridLayout }) {
  const { control } = useFormContext<GenerateImagesFormValues>();
  const { data: models } = useImageModelsQuery();
  const selectedModelId = useWatch({ control, name: "model" });
  const labelId = useId();
  const gridClassName = STYLE_GRID_CLASSNAME[layout];

  return (
    <div className="flex flex-col gap-1.5">
      <Label id={labelId}>스타일</Label>
      {/* 모델 목록이 아직 로딩 중이면(models === undefined) 스타일 자리가 통째로 빈 채로 렌더됐다 —
          실제 타일과 같은 셸(같은 그리드 클래스 · aspect-[3/4])의 스켈레톤으로 채운다
          (GeneratedImageLibraryPanel.tsx의 LibraryGridSkeleton 관용구를 따른다 — 바탕색도 같은
          이유로 `secondary`). 개수 7은 레지스트리 스타일 종수와 맞춘다. */}
      {models === undefined ? (
        <div className={gridClassName}>
          {[0, 1, 2, 3, 4, 5, 6].map((key) => (
            <div key={key} className="aspect-[3/4] animate-pulse rounded-lg bg-secondary" />
          ))}
        </div>
      ) : (
        <Controller
          control={control}
          name="style"
          render={({ field }) => (
            <div role="listbox" aria-labelledby={labelId} className={gridClassName}>
              {(models.find((model) => model.id === selectedModelId)?.styles ?? []).map((style) => {
                const isSelected = style.id === field.value;
                const sample = STYLE_SAMPLE_IMAGES[style.id];
                return (
                  <button
                    key={style.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    disabled={!style.available}
                    onClick={() => field.onChange(style.id)}
                    // rounded-lg — 90~190px 타일에 xl 반경은 모서리가 과하다. 같은 크기대의 보관함
                    // 타일과 같은 값이다.
                    className={cn(
                      "relative aspect-[3/4] overflow-hidden rounded-lg border-2 bg-secondary",
                      "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      "disabled:pointer-events-none disabled:opacity-50",
                      isSelected ? "border-primary" : "border-transparent",
                    )}
                  >
                    {/* 서버가 스타일 목록의 소스다 — FE가 모르는 id는 이미지 없이 렌더한다.
                        타일은 이미지가 없어도 이름만으로 온전해야 한다. */}
                    {sample ? (
                      <img
                        src={sample}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        className="size-full object-cover"
                      />
                    ) : null}
                    {/* 체크 원은 이 화면의 둘째 `primary` 솔리드다 — 작은 타일에서 늘리지 않도록
                        16px로 줄였다. 선택의 주 신호는 타일의 `border-primary`이고 원은 보조다. */}
                    {isSelected && (
                      <span className="absolute right-1.5 top-1.5 rounded-full bg-primary p-0.5">
                        <Check aria-hidden className="size-3 text-primary-foreground" />
                      </span>
                    )}
                    {/* 아트워크 위 캡션이라 색은 테마를 따라가지 않는다 — `scrim`/`scrim-foreground`는
                        globals.css에서 .dark에 덮이지 않는 유일한 쌍이다(근거는 그 토큰 주석). 옛 값
                        (`from-black/60` 그라데이션 + `text-foreground`)은 **두 테마 모두** AA 미달이었다:
                        그라데이션이 글자 윗단에서 알파 0.28까지 옅어져 아트워크가 그대로 비쳤고, 이 샘플
                        아트 하단 밴드는 휘도 중앙 0.42·p95 0.985라 밝은 픽셀과 어두운 픽셀이 같이 있다 —
                        다크는 밝은 쪽에서 1.65:1, 라이트는 어두운 쪽에서 1.67:1. 불투명 밴드로 바꿔
                        아트워크와 무관하게 최악(순백) 6.93:1을 보장한다. 그라데이션을 되살리지 말 것:
                        라벨이 두 줄이 되면(`반실사 · 준비 중` — 좁은 우열 타일에서는 더 자주 접힌다) %
                        기준 스톱이 글자를 다시 벗어난다.
                        밴드를 `text-xs py-1`로 줄인 것은 작은 타일에서 이름표가 그림을 너무 많이 덮지
                        않게 하려는 것이다. 대비는 글자 크기가 아니라 불투명 밴드가 보장하므로 줄여도
                        위 수치는 그대로다. */}
                    <span className="absolute inset-x-0 bottom-0 bg-scrim/70 px-2 py-1 text-xs font-semibold text-scrim-foreground">
                      {style.name}
                      {!style.available && " · 준비 중"}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        />
      )}
    </div>
  );
}
