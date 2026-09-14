import { cn } from "@ai-character-chat/ui/lib/utils";
import { Check } from "lucide-react";
import { Controller, useFormContext, useWatch } from "react-hook-form";

import { useImageModelsQuery } from "@/entities/image-model";

import type { GenerateImagesFormValues } from "../model/schema";
import { STYLE_SAMPLE_IMAGES } from "../model/styleSampleImages";

// 실제 타일(아래)과 스켈레톤(로딩 분기)이 반드시 같은 셸을 쓰게 상수 하나로 묶는다 — 그리드
// 클래스가 갈리면 목록 도착 시 레이아웃이 튄다(card-grid 런에서 실측한 문제).
const STYLE_GRID_CLASSNAME =
  "grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-[repeat(auto-fill,minmax(11rem,1fr))]";

// image-refact-techspec.md IT-12 — `listbox`/`option`/`aria-selected` 패턴(ColorPicker·IconPicker
// 선례, §0-13). `radiogroup`이 아니다. 방향키 이동은 구현하지 않는다(두 선례 모두 없다).
//
// 선택은 `border`, 포커스는 `ring` — 둘이 다른 CSS 속성을 쓰므로 ColorPicker.tsx:60-64가 기록한
// `--tw-ring-*` 충돌(같은 변수를 공유해 포커스 링이 선택 링을 덮어쓰는 함정)이 원천적으로 없다
// (image-refact-goal-prompt.md IR-9 정정).
export function GenerateImagesStyleGrid() {
  const { control } = useFormContext<GenerateImagesFormValues>();
  const { data: models } = useImageModelsQuery();
  const selectedModelId = useWatch({ control, name: "model" });

  // 모델 목록이 아직 로딩 중이면(models === undefined) 스타일 자리가 통째로 빈 채로 렌더됐다 —
  // 실제 타일과 같은 셸(같은 그리드 클래스 · aspect-[3/4])의 스켈레톤으로 채운다
  // (GeneratedImageLibraryPanel.tsx의 LibraryGridSkeleton 관용구를 따른다). 개수 4는 레지스트리
  // 스타일 종수(IR-13)와 맞춘다.
  if (models === undefined) {
    return (
      <div className={STYLE_GRID_CLASSNAME}>
        {[0, 1, 2, 3].map((key) => (
          <div key={key} className="aspect-[3/4] animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    );
  }

  const styleOptions = models.find((model) => model.id === selectedModelId)?.styles ?? [];

  return (
    <Controller
      control={control}
      name="style"
      render={({ field }) => (
        <div role="listbox" aria-label="이미지 스타일" className={STYLE_GRID_CLASSNAME}>
          {styleOptions.map((style) => {
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
                className={cn(
                  "relative aspect-[3/4] overflow-hidden rounded-xl border-2 bg-muted",
                  "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  "disabled:pointer-events-none disabled:opacity-50",
                  isSelected ? "border-primary" : "border-transparent",
                )}
              >
                {/* 서버가 스타일 목록의 소스다(IR-10) — FE가 모르는 id는 이미지 없이 렌더한다.
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
                {isSelected && (
                  <span className="absolute right-3 top-3 rounded-full bg-primary p-1">
                    <Check aria-hidden className="size-4 text-primary-foreground" />
                  </span>
                )}
                {/* 아트워크 위 캡션이라 색은 테마를 따라가지 않는다 — `scrim`/`scrim-foreground`는
                    globals.css에서 .dark에 덮이지 않는 유일한 쌍이다(근거는 그 토큰 주석). 옛 값
                    (`from-black/60` 그라데이션 + `text-foreground`)은 **두 테마 모두** AA 미달이었다:
                    그라데이션이 글자 윗단에서 알파 0.28까지 옅어져 아트워크가 그대로 비쳤고, 이 샘플
                    아트 하단 밴드는 휘도 중앙 0.42·p95 0.985라 밝은 픽셀과 어두운 픽셀이 같이 있다 —
                    다크는 밝은 쪽에서 1.65:1, 라이트는 어두운 쪽에서 1.67:1. 불투명 밴드로 바꿔
                    아트워크와 무관하게 최악(순백) 6.93:1을 보장한다. 그라데이션을 되살리지 말 것:
                    라벨이 두 줄이 되면(`반실사 · 준비 중`) % 기준 스톱이 글자를 다시 벗어난다. */}
                <span className="absolute inset-x-0 bottom-0 bg-scrim/70 px-3 py-2 text-sm font-semibold text-scrim-foreground">
                  {style.name}
                  {!style.available && " · 준비 중"}
                </span>
              </button>
            );
          })}
        </div>
      )}
    />
  );
}
