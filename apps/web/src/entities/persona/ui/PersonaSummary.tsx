import { cn } from "@ai-character-chat/ui/lib/utils";

import type { Persona } from "../model/persona";
import { PERSONA_GENDER_LABEL } from "../model/personaGender";

type PersonaSummaryProps = {
  persona: Persona;
  isDefault: boolean;
  className?: string;
  /** 보조 글자(설명·`기본` 배지)의 잉크. 기본은 `text-muted-foreground`이고, 그 값이 AA를 못 넘는 표면에
   * 얹는 호출부만 바꾼다(대화방 선택 목록의 hover·선택 행 — `RoomPersonaPicker`). */
  secondaryTextClassName?: string;
};

/** 관리 페이지 목록과 대화방 선택 목록이 함께 쓰는 한 줄 요약(이름 · 기본 표시 · 성별 · 설명).
 *
 * `기본` 표시는 채움이 아니라 윤곽 배지다 — 중립 상태 배지 규칙(DESIGN.md §5 Status badges). 채움
 * (`bg-muted`)은 모달 표면(`popover`)과 값이 같아 대화방 선택 모달 안에서 사라진다. */
export function PersonaSummary({
  persona,
  isDefault,
  className,
  secondaryTextClassName = "text-muted-foreground",
}: PersonaSummaryProps) {
  const genderLabel = persona.gender ? PERSONA_GENDER_LABEL[persona.gender] : undefined;
  const meta = [genderLabel, persona.description].filter(Boolean).join(" · ");

  return (
    <span className={cn("flex min-w-0 flex-col gap-0.5 text-left", className)}>
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm font-medium text-foreground">{persona.name}</span>
        {isDefault && (
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium",
              secondaryTextClassName,
            )}
          >
            기본
          </span>
        )}
      </span>
      {meta !== "" && (
        <span className={cn("line-clamp-2 text-xs break-words break-keep", secondaryTextClassName)}>{meta}</span>
      )}
    </span>
  );
}
