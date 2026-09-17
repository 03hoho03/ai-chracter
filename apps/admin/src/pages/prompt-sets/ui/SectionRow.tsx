import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useId } from "react";
import { useFormContext } from "react-hook-form";

import { allowedPlaceholdersFor } from "../model/allowedPlaceholders";
import { isPromptScope, PROMPT_SCOPE_LABELS } from "../model/channels";
import type { PromptSetFormValues } from "../model/schema";

const BADGE_CLASS =
  "inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground";

type SectionRowProps = {
  fieldKey: string;
  fieldIndex: number;
  channel: string;
  scope: string;
  slot: string;
  variant: string;
  conditional: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
};

/** 섹션 하나 — 편집 가능한 건 body와(위/아래 버튼을 통한) order뿐이다. channel/scope/slot/
 * variant/conditional은 코드가 고정한 값이라(D-7) 배지로만 보여주고 폼은 그대로 들고 있다가
 * 되돌려 보낸다. */
export function SectionRow({
  fieldKey,
  fieldIndex,
  channel,
  scope,
  slot,
  variant,
  conditional,
  canMoveUp,
  canMoveDown,
  onMoveUp,
  onMoveDown,
}: SectionRowProps) {
  const {
    register,
    formState: { errors },
  } = useFormContext<PromptSetFormValues>();
  const bodyError = errors.sections?.[fieldIndex]?.body;
  const placeholders = allowedPlaceholdersFor(channel, slot);
  // 공통 슬롯(channel/scope/slot/variant)은 레인마다 사본으로 반복돼 `fieldKey`가 레인 사이에서
  // 겹친다 — 레인 3개가 `forceMount`로 동시에 마운트되면(PromptSetsPage) 이 id도 DOM에 3벌
  // 생겨 `aria-describedby`가 남의 레인 에러 노드를 가리킨다. `useId()`로 컴포넌트 인스턴스별
  // 접두어를 섞는다(선례: `LabelsCard`).
  const uid = useId();
  const bodyFieldId = `${uid}-prompt-section-${fieldKey}-body`;

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={BADGE_CLASS}>{isPromptScope(scope) ? PROMPT_SCOPE_LABELS[scope] : scope}</span>
          {variant && <span className={BADGE_CLASS}>variant: {variant}</span>}
          <code className="font-mono text-xs text-muted-foreground">{slot}</code>
          {conditional && (
            <span className="text-xs text-muted-foreground">· 값이 비면 섹션째 생략돼요</span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="위로 이동"
            disabled={!canMoveUp}
            onClick={onMoveUp}
          >
            <ChevronUp />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="아래로 이동"
            disabled={!canMoveDown}
            onClick={onMoveDown}
          >
            <ChevronDown />
          </Button>
        </div>
      </div>

      <Textarea
        id={bodyFieldId}
        aria-label={`${slot}${variant ? ` (variant: ${variant})` : ""} 본문`}
        aria-invalid={!!bodyError}
        aria-describedby={bodyError ? `${bodyFieldId}-error` : undefined}
        {...register(`sections.${fieldIndex}.body`)}
      />
      {bodyError && (
        <p id={`${bodyFieldId}-error`} role="alert" className="text-xs text-destructive-text">
          {bodyError.message}
        </p>
      )}
      {placeholders.length > 0 && (
        <p className="break-keep text-xs text-muted-foreground">
          허용된 변수: {placeholders.map((name) => `{${name}}`).join(", ")}
        </p>
      )}
    </div>
  );
}
