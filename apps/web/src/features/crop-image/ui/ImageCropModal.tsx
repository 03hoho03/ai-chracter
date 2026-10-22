import { Loader2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import Cropper from "react-easy-crop";
import type { Area, Point } from "react-easy-crop";
import { toast } from "sonner";

import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Slider } from "@ai-character-chat/ui/components/slider";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";

import type { PreparedUpload } from "@/shared/api/asset/uploadAsset";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { cropToFile } from "../lib/cropToFile";
import { toCropAspect, type CropAspectChoice } from "../model/cropAspect";

export type ImageCropModalProps = {
  file: File;
  /** 고정 비율 하나, 또는 고를 수 있는 비율 칩 목록(첫 칩이 기본). 칩 목록은 그림 크기에 맞춰 쓰는 자리(소설 삽화)만 넘긴다. */
  aspect: number | readonly CropAspectChoice[];
  shape?: "rect" | "round";
  /** GIF 를 움직이는 채로 둔다 — canvas 로 자르면 첫 프레임만 남으므로, 원본 파일과 크롭 영역을 그대로 돌려줘 서버가
   * 모든 프레임을 자르게 한다. 그 영역을 서버에 넘기는 업로드(대표 이미지)에서만 켠다. */
  keepAnimation?: boolean;
};

// 확대는 원본 크기와 무관하게 항상 1~3배다.
// 처음엔 "결과가 목표 해상도 밑으로 안 내려가는 배율"로 상한을 계산했는데, AI 생성 이미지가
// 정확히 목표 해상도(1024)라 1:1 크롭에서 상한이 1.00으로 떨어져 **확대가 아예 안 됐다**.
// 화질보다 창작자의 구도 통제를 택했다(2026-09-15 실사용 확인 후 결정).
// 하한이 1인 이유: `getCropSize`가 zoom=1에서 크롭 박스를 미디어 안에 맞춰 넣고
// `restrictPosition`(기본 true)이 그 상태를 유지해 결과물에 여백이 생길 수 없다.
const MIN_ZOOM = 1;
const MAX_ZOOM = 3;

// react-call 자체 호출형. 성공 후 동작이 호출부마다 갈리지 않고
// 잘라낸 File(움직이는 GIF 는 원본과 크롭 영역)을 그대로 돌려주는 순수 입력 모달이라 mutationFn 주입형이 아니다. 취소·ESC·바깥클릭·✕는
// 전부 onOpenChange 한 지점으로 모여 call.end(undefined)로 수렴한다(GeneratedImagePickerModal과 동일 패턴).
export const ImageCropModal = createCallable<ImageCropModalProps, PreparedUpload | undefined>(
  ({ call, file, aspect, shape = "rect", keepAnimation = false }) => {
    const isOpen = !call.ended;
    const labelId = useId();

    const [imageUrl, setImageUrl] = useState<string>();
    const [crop, setCrop] = useState<Point>({ x: 0, y: 0 });
    const [zoom, setZoom] = useState(1);
    const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area>();
    const [isApplying, setIsApplying] = useState(false);
    const choices = typeof aspect === "number" ? undefined : aspect;
    const [choiceIndex, setChoiceIndex] = useState(0);
    const [mediaSize, setMediaSize] = useState<{ width: number; height: number }>();
    const choice = choices?.[choiceIndex];
    // 원본 칩은 그림이 오기 전에는 비율이 없다 — 그동안은 그림이 그려지지 않으므로 아무 값이나 같다.
    const resolvedAspect = typeof aspect === "number" ? aspect : choice && (toCropAspect(choice, mediaSize) ?? 1);

    // 이 컴포넌트 인스턴스는 호출 1회당 하나다(react-call이 call마다 새 key로 마운트한다) — 그래서
    // isOpen이 아니라 마운트 시점 1회만 objectURL을 만들고, 언마운트에서 해제하면 누수가 없다.
    useEffect(() => {
      const url = URL.createObjectURL(file);
      setImageUrl(url);
      return () => URL.revokeObjectURL(url);
    }, [file]);

    const handleApply = async () => {
      if (!croppedAreaPixels) return;
      if (keepAnimation && file.type === "image/gif") {
        // 라이브러리가 주는 영역은 소수 픽셀이라 반올림한다. 경계를 1px 넘는 것은 서버가 그림 안으로 자른다.
        const { x, y, width, height } = croppedAreaPixels;
        call.end({ file, crop: { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) } });
        return;
      }
      setIsApplying(true);
      try {
        call.end({ file: await cropToFile(file, croppedAreaPixels) });
      } catch {
        toast.error("이미지를 자르지 못했어요. 다시 시도해주세요.");
        setIsApplying(false);
      }
    };

    return (
      <Dialog open={isOpen} onOpenChange={(next) => !next && call.end(undefined)}>
        <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>이미지 자르기</DialogTitle>
            <DialogDescription>사용할 영역을 조절한 뒤 적용을 눌러주세요.</DialogDescription>
          </DialogHeader>

          {/* 정지 상태 그림자 없음(shadow-* 금지), 마스크는 무채색. `relative` + `min-h-64`
              (명시적 높이)가 필요하다: Cropper는 `position:absolute`로 부모를 채우는데, `flex-1`만으로는
              부모(auto-height flex column)가 실제로 자라지 않아 0높이로 접힌다 — `min-h-64`가 hypothetical
              main size에 반영돼야 DialogContent 자체가 그만큼 자란다. */}
          <div className="relative min-h-64 flex-1 overflow-hidden rounded-md bg-secondary">
            {imageUrl === undefined ? (
              <div className="flex size-full items-center justify-center">
                <Loader2 aria-hidden className="size-6 animate-spin text-muted-foreground" />
                <span className="sr-only">이미지를 불러오는 중</span>
              </div>
            ) : (
              <Cropper
                image={imageUrl}
                crop={crop}
                zoom={zoom}
                aspect={resolvedAspect}
                minZoom={MIN_ZOOM}
                maxZoom={MAX_ZOOM}
                cropShape={shape}
                // 다크에서 순백 금지. 라이브러리 기본 격자선(showGrid
                // 기본값 true)도 같은 흰색이고 이 제품은 조용한 인터페이스를 지향해 끈다. 방향키 step은
                // 아래 keyboardStep 참고.
                showGrid={false}
                // 기본 keyboardStep은 1px라 방향키로 크롭 프레임을 가로지르려면 수백 번 눌러야
                // 한다. 키보드만으로도 실사용 가능한 속도가 되도록 10px 단위로 올린다.
                keyboardStep={10}
                onCropChange={setCrop}
                onZoomChange={setZoom}
                onCropComplete={(_, areaPixels) => setCroppedAreaPixels(areaPixels)}
                onMediaLoaded={({ naturalWidth, naturalHeight }) =>
                  setMediaSize({ width: naturalWidth, height: naturalHeight })
                }
                // 라이브러리가 크롭 영역에 칠하는 기본 테두리(rgba(255,255,255,0.5))를 순백 금지
                // 규칙에 맞게 primary 한 겹으로 덮어쓴다. 라이브러리 CSS는 런타임에 <head>로 주입돼
                // Tailwind 유틸리티보다 뒤에 올 수 있어 캐스케이드 순서로는 이길 수 없다 — border-color
                // longhand에 Tailwind v4 important 접미사(`!`)를 써 값의 중요도로 이긴다. 그 외
                // border-width/style은 라이브러리 규칙(1px solid)을 그대로 물려받으므로 겹선이 아니라
                // 한 겹으로 남는다(ring-2를 함께 쓰지 않는 이유).
                classes={{ cropAreaClassName: "border-primary!" }}
              />
            )}
          </div>

          {choices !== undefined && (
            <div className="flex flex-wrap items-center gap-3">
              <span id={labelId} className="shrink-0 text-sm text-muted-foreground">
                비율
              </span>
              {/* 모달에는 이미 솔리드 채움(적용)이 있어 고른 칩은 무채 표면 + 윤곽이다 — 한 화면의 솔리드 채움은 하나다. */}
              <ToggleGroup
                type="single"
                variant="neutral"
                size="sm"
                aria-labelledby={labelId}
                value={String(choiceIndex)}
                onValueChange={(value) => {
                  // 단일 토글 그룹은 고른 칩을 다시 누르면 빈 값을 보낸다 — 비율은 늘 하나라 해제를 받지 않는다.
                  if (value === "") return;
                  setChoiceIndex(Number(value));
                  setCrop({ x: 0, y: 0 });
                  setZoom(1);
                }}
              >
                {choices.map((item, index) => (
                  <ToggleGroupItem key={item.label} value={String(index)}>
                    {item.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          )}

          <div className="flex items-center gap-3">
            <span className="shrink-0 text-sm text-muted-foreground">확대/축소</span>
            <Slider
              value={[zoom]}
              min={MIN_ZOOM}
              max={MAX_ZOOM}
              step={0.01}
              onValueChange={([next]) => next !== undefined && setZoom(next)}
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => call.end(undefined)}>
              취소
            </Button>
            <Button onClick={() => void handleApply()} disabled={!croppedAreaPixels || isApplying}>
              적용
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
