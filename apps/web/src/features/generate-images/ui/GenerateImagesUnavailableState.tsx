import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageOff, TriangleAlert, WifiOff } from "lucide-react";

type UnavailableReason = "error" | "empty" | "unavailable";

const COPY: Record<
  UnavailableReason,
  { icon: typeof TriangleAlert; title: string; description: string; isError: boolean }
> = {
  error: {
    icon: TriangleAlert,
    title: "모델 목록을 불러오지 못했어요",
    description: "일시적인 오류일 수 있어요. 잠시 후 다시 시도해주세요.",
    isError: true,
  },
  empty: {
    icon: ImageOff,
    title: "생성 가능한 모델이 없어요",
    description: "지금은 이미지를 생성할 수 있는 모델이 없어요.",
    isError: false,
  },
  unavailable: {
    icon: WifiOff,
    title: "지금은 이미지를 생성할 수 없어요",
    description: "이미지 생성 서버가 일시적으로 응답하지 않아요. 잠시 후 다시 시도해주세요.",
    isError: false,
  },
};

/** tasks/local-image-gen-techspec.md LT-11, tasks/local-image-gen-goal-prompt.md LG-17 — 모델 목록
 * 조회 실패·빈 목록·전 모델 일시 불가를 대신 보여주는 제출 이전(pre-submission) 상태. 시각 어휘는
 * `widgets/content-detail/ui/ContentUnavailableState.tsx`(아이콘 + 제목 + 설명, 전체 패널 빈 상태)를
 * 따른다 — 이미 제출 이후의 "뭔가 잘못됨" 표면이 셋 있어(제출 에러 토스트, 잡 실패 alert, 잡 조회
 * 에러 alert) 이 상태를 그것들과 겹치거나 모순되게 만들지 않는다. `onRetry`가 있는 두 사유(error·
 * unavailable)만 재시도 버튼을 보여준다 — `empty`는 정적 레지스트리가 빈 것이라 재시도로 고쳐지지
 * 않는다. */
export function GenerateImagesUnavailableState({
  reason,
  onRetry,
}: {
  reason: UnavailableReason;
  onRetry?: () => void;
}) {
  const { icon: Icon, title, description, isError } = COPY[reason];

  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <Icon aria-hidden className="size-8 text-muted-foreground" />
      <p className="text-lg font-semibold text-foreground">{title}</p>
      <p className={cn("text-sm", isError ? "text-destructive-text" : "text-muted-foreground")}>
        {description}
      </p>
      {/* apps/web/CLAUDE.md §UI/컴포넌트 — 빈 상태 패널 한가운데의 액션이 그 화면의 유일한 앞길이면
          `size="sm"`을 쓰지 않는다(보조 액션으로 읽힌다). 채움은 올리지 않는다(솔리드는 실제 CTA
          자리, `primary`가 아니다) — 기본 크기 `outline`까지만 올린다. */}
      {onRetry && (
        <Button type="button" variant="outline" onClick={onRetry}>
          다시 시도
        </Button>
      )}
    </div>
  );
}
