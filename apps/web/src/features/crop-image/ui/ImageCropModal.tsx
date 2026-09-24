import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import Cropper from "react-easy-crop";
import type { Area, Point } from "react-easy-crop";
import { createCallable } from "react-call";
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

import { cropToFile } from "../lib/cropToFile";

export type ImageCropModalProps = { file: File; aspect: number; shape?: "rect" | "round" };

// image-crop-goal-prompt.md IC-7 — 확대는 원본 크기와 무관하게 항상 1~3배다.
// 처음엔 "결과가 목표 해상도 밑으로 안 내려가는 배율"로 상한을 계산했는데, AI 생성 이미지가
// 정확히 목표 해상도(1024)라 1:1 크롭에서 상한이 1.00으로 떨어져 **확대가 아예 안 됐다**.
// 화질보다 창작자의 구도 통제를 택했다(2026-09-15 실사용 확인 후 결정).
// 하한이 1인 이유: `getCropSize`가 zoom=1에서 크롭 박스를 미디어 안에 맞춰 넣고
// `restrictPosition`(기본 true)이 그 상태를 유지해 결과물에 여백이 생길 수 없다.
const MIN_ZOOM = 1;
const MAX_ZOOM = 3;

// image-crop-goal-prompt.md IC-8 — react-call 자체 호출형. 성공 후 동작이 호출부마다 갈리지 않고
// 잘라낸 File을 그대로 돌려주는 순수 입력 모달이라 mutationFn 주입형이 아니다. 취소·ESC·바깥클릭·✕는
// 전부 onOpenChange 한 지점으로 모여 call.end(undefined)로 수렴한다(GeneratedImagePickerModal과 동일 패턴).
export const ImageCropModal = createCallable<ImageCropModalProps, File | undefined>(
  ({ call, file, aspect, shape = "rect" }) => {
    const isOpen = !call.ended;

    const [imageUrl, setImageUrl] = useState<string>();
    const [crop, setCrop] = useState<Point>({ x: 0, y: 0 });
    const [zoom, setZoom] = useState(1);
    const [croppedAreaPixels, setCroppedAreaPixels] = useState<Area>();
    const [isApplying, setIsApplying] = useState(false);

    // 이 컴포넌트 인스턴스는 호출 1회당 하나다(react-call이 call마다 새 key로 마운트한다) — 그래서
    // isOpen이 아니라 마운트 시점 1회만 objectURL을 만들고, 언마운트에서 해제하면 누수가 없다.
    useEffect(() => {
      const url = URL.createObjectURL(file);
      setImageUrl(url);
      return () => URL.revokeObjectURL(url);
    }, [file]);

    const handleApply = async () => {
      if (!croppedAreaPixels) return;
      setIsApplying(true);
      try {
        call.end(await cropToFile(file, croppedAreaPixels));
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

          {/* IC-9 — 정지 상태 그림자 없음(shadow-* 금지), 마스크는 무채색. `relative` + `min-h-64`
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
                aspect={aspect}
                minZoom={MIN_ZOOM}
                maxZoom={MAX_ZOOM}
                cropShape={shape}
                // image-crop-goal-prompt.md IC-9 — 다크에서 순백 금지. 라이브러리 기본 격자선(showGrid
                // 기본값 true)도 같은 흰색이고 이 제품은 조용한 인터페이스를 지향해 끈다. 방향키 step은
                // 아래 keyboardStep(IC-14) 참고.
                showGrid={false}
                // IC-14 — 기본 keyboardStep은 1px라 방향키로 크롭 프레임을 가로지르려면 수백 번 눌러야
                // 한다. 키보드만으로도 실사용 가능한 속도가 되도록 10px 단위로 올린다.
                keyboardStep={10}
                onCropChange={setCrop}
                onZoomChange={setZoom}
                onCropComplete={(_, areaPixels) => setCroppedAreaPixels(areaPixels)}
                // IC-9 — 라이브러리가 크롭 영역에 칠하는 기본 테두리(rgba(255,255,255,0.5))를 순백 금지
                // 규칙에 맞게 primary 한 겹으로 덮어쓴다. 라이브러리 CSS는 런타임에 <head>로 주입돼
                // Tailwind 유틸리티보다 뒤에 올 수 있어 캐스케이드 순서로는 이길 수 없다 — border-color
                // longhand에 Tailwind v4 important 접미사(`!`)를 써 값의 중요도로 이긴다. 그 외
                // border-width/style은 라이브러리 규칙(1px solid)을 그대로 물려받으므로 겹선이 아니라
                // 한 겹으로 남는다(ring-2를 함께 쓰지 않는 이유).
                classes={{ cropAreaClassName: "border-primary!" }}
              />
            )}
          </div>

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
