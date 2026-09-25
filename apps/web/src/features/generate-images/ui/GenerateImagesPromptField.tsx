import { Button } from "@ai-character-chat/ui/components/button";
import { Label } from "@ai-character-chat/ui/components/label";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { useFormContext, useWatch } from "react-hook-form";

import {
  CloverBalance,
  IMAGE_CLOVER_COST,
  isCloverInsufficient,
  shouldShowCloverBalance,
  useCloverBalanceQuery,
} from "@/entities/clover";

import { getPromptSyntaxHint, PROMPT_WEIGHT_SYNTAX_HINT } from "../model/promptSyntaxHint";
import type { GenerateImagesFormValues } from "../model/schema";
import { useGenerateImagesSubmit } from "../model/useGenerateImagesSubmit";

// danbooru 태그 예시(품질 부스터 금지, 서버에서 치운
// Animagine 시그니처 문구라 FE 번들에도 넣지 않는다).
const PROMPT_PLACEHOLDER =
  "1girl, solo, long hair, school uniform, cherry blossoms, looking at viewer, upper body";

// `<form>` 엘리먼트는 이 조각(중앙 열)이 감싼다. FormProvider는
// React context라 DOM 위치와 무관하므로, 다른 열/시트의 필드도 이 제출에 포함된다.
export function GenerateImagesPromptField() {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useFormContext<GenerateImagesFormValues>();
  const { onSubmit, isModelsPending } = useGenerateImagesSubmit();
  const isSubmitBlocked = isSubmitting || isModelsPending;
  // 무료 토큰을 다 쓴 뒤에만 나타난다.
  // 단가는 1장 기준 `IMAGE_UNIT_COST`(30)다 — 한 요청 최대 2장이지만 "한 장도 못 만드는가"가
  // 부족의 기준이라 장수를 곱하지 않는다.
  const { data: clover } = useCloverBalanceQuery();
  const cloverBalance = clover?.balance ?? 0;
  const isCloverShort = isCloverInsufficient(cloverBalance, IMAGE_CLOVER_COST);
  const showClover =
    clover !== undefined &&
    shouldShowCloverBalance({
      spendConfirmedToday: clover.spendConfirmedToday,
      hasCloverShortage: isCloverShort,
    });
  // useWatch로 렌더 시점에 계산한다(useEffect 금지, 파생 상태).
  const promptValue = useWatch({ control, name: "prompt" });
  const syntaxHint = getPromptSyntaxHint(promptValue ?? "");
  const isSyntaxWarning = syntaxHint !== PROMPT_WEIGHT_SYNTAX_HINT;
  const describedByIds = errors.prompt
    ? "generate-images-prompt-hint generate-images-prompt-error"
    : "generate-images-prompt-hint";

  return (
    <form
      className="flex flex-col gap-6"
      noValidate
      onSubmit={(event) => {
        // aria-disabled는 포인터만 막으므로(pointer-events-none) 버튼을 키보드로 누른 Enter는
        // 그대로 들어온다 — 실제 중복 제출 차단은 여기다.
        if (isSubmitBlocked) {
          event.preventDefault();
          return;
        }
        // `handleSubmit`은 프라미스를 반환하는데 이 속성은 void를 기대한다(no-misused-promises).
        void handleSubmit(onSubmit)(event);
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="generate-images-prompt">프롬프트</Label>
        {/* 브라우저 실검증 — 프롬프트와 제출 버튼을 한 보더 박스에 묶는다(크랙 실측: 박스 안
            우하단 버튼). 포커스 링은 안쪽 Textarea가 아니라 이 박스가 받아야 하므로
            `has-[textarea:focus-visible]:`로 하우스 레시피(DESIGN.md §Buttons Focus)를 얹는다 —
            안쪽 Textarea의 자기 보더·링은 아래에서 지운다(이중 보더 방지). */}
        <div className="flex flex-col gap-2 rounded-lg border border-input bg-background p-2 has-[textarea:focus-visible]:border-ring has-[textarea:focus-visible]:ring-3 has-[textarea:focus-visible]:ring-ring/50">
          <Textarea
            id="generate-images-prompt"
            placeholder={PROMPT_PLACEHOLDER}
            rows={4}
            aria-invalid={!!errors.prompt}
            aria-describedby={describedByIds}
            className="border-0 bg-transparent p-0 focus-visible:ring-0"
            {...register("prompt")}
          />
          {/* 생성 버튼 줄의 **왼쪽**에 잔량을 둔다. 박스 아래에는 이미
              힌트·에러 `<p>`가 있어 거기 넣으면 세 번째 줄이 되고, 버튼과 같은 줄이면 "이걸 누르면
              얼마가 빠지나"가 한눈에 붙는다. 잔량이 없을 땐 `justify-between`이 빈 자리를 만들지
              않도록 버튼만 남는다(아래 조건부 렌더). */}
          <div className="flex items-center justify-between gap-2">
            {/* 빈 `<span>`을 항상 두어 `justify-between`이 버튼을 오른쪽에 붙여 둔다 — 조건부로
                통째로 빼면 버튼이 홀로 남아 왼쪽으로 튄다. */}
            <span>{showClover && <CloverBalance balance={cloverBalance} isInsufficient={isCloverShort} />}</span>
            {/* 모델 목록이 아직 로딩 중이면 model/style이 비어 있어 제출해도 zod가 조용히 막는다(그
                필드엔 에러 텍스트 UI가 없다) — 누를 게 없는 상태를 숨기지 않고 버튼을 함께 잠근다.
                apps/web/CLAUDE.md §포커스 — plain `disabled`는 브라우저가 즉시 blur해 포커스를
                <body>로 떨어뜨린다. 제출 중(isSubmitting)에 실제로 그 상황이 되므로
                ContentListLoadMore·ReconsentModal·WithdrawAccountDialog와 같은 레시피를 쓴다.
                isModelsPending은 마운트 시점부터 true라 blur 위험은 없지만, 한 버튼에 두 어휘가
                섞이지 않게 같은 축으로 묶는다 — 덕분에 모델 로딩 중에도 버튼이 tab 순서에 남는다. */}
            <Button
              type="submit"
              aria-disabled={isSubmitBlocked}
              className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
            >
              이미지 생성
            </Button>
          </div>
        </div>
        {/* 가중치 문법 안내/괄호 경고를 한 줄로 합친다. 하드
            에러(errors.prompt)와 다른 어휘라 aria-invalid/role="alert"/text-destructive-text에는
            연결하지 않는다 — 제출을 막지 않는 경고다(GenerateImagesOptionsFields.tsx:106-108 선례).
            aria-live="polite" + 항상 마운트(GenerateImagesResultGrid.tsx:143-148 선례) — 문구가
            타이핑마다 바뀌므로 조건부 마운트하면 announce 여부가 갈린다. */}
        <p
          id="generate-images-prompt-hint"
          aria-live="polite"
          className={
            isSyntaxWarning
              ? "break-keep text-xs text-foreground"
              : "break-keep text-xs text-muted-foreground"
          }
        >
          {syntaxHint}
        </p>
        {errors.prompt && (
          <p id="generate-images-prompt-error" role="alert" className="text-xs text-destructive-text">
            {errors.prompt.message}
          </p>
        )}
      </div>
    </form>
  );
}
