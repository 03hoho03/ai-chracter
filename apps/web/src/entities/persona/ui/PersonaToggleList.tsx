import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";

import type { PersonaList } from "../model/persona";
import { PersonaSummary } from "./PersonaSummary";

type PersonaToggleListProps = {
  personaList: PersonaList;
  /** 선택된 프로필 id. null = "선택 안 함"(`includeNone` 일 때만 의미가 있다). */
  value: string | null;
  /** 항목을 누를 때마다 부른다 — 이미 선택된 항목을 다시 눌러도 그 값으로 부른다(받는 쪽이 무시하거나 확정으로 읽는다). */
  onValueChange: (personaId: string | null) => void;
  /** 맨 위에 "선택 안 함"을 둔다. 대화방은 프로필 없이 대화할 수 있고, 새 대화를 시작할 때는 늘 하나를 고른다. */
  includeNone: boolean;
  "aria-label": string;
  "aria-busy"?: boolean;
};

/** 토글 값으로 "선택 안 함"을 담는 표식. 프로필 id는 UUID라 겹치지 않는다. */
const NO_PERSONA_VALUE = "none";

const ITEM_CLASS =
  "group/persona-option h-auto min-h-11 w-full justify-start px-3.5 py-2.5 whitespace-normal hover:bg-secondary";

/** 행 안 보조 글자(설명·`기본` 배지)는 행 표면이 한 칸 오르면(hover `secondary`, 선택 `primary/10`·`/15` 틴트)
 * 잉크도 `foreground`로 함께 올린다. 라이트 `muted-foreground`(0.53)는 `popover` 위 4.84:1이지만 선택 행
 * 4.10 · 선택+hover 3.76 · hover 행 4.30으로 AA 미달이었고, 사다리에서 그
 * 표면들 위 4.5:1을 넘는 무채색 잉크는 `foreground`뿐이다(13.45 / 12.34 / 14.09, 다크 12.55 / 11.54 /
 * 12.64 — oklch 토큰 → sRGB 합성 계산). 쉬는 행은 `muted-foreground` 그대로라 이름과의 위계가 남는다. */
const SECONDARY_TEXT_CLASS =
  "text-muted-foreground group-hover/persona-option:text-foreground group-data-[state=on]/persona-option:text-foreground";

/** 모달 안에서 프로필 하나를 고르는 세로 목록 — 대화방의 프로필 바꾸기와 새 대화의 프로필 고르기가 함께 쓴다. 고른 뒤
 * 무엇을 할지(바로 저장, 시작 전 선택)는 받는 쪽이 정한다.
 *
 * `variant="list"` — 넓은 행이 세로로 쌓인 선택지라 틴트로 표시한다(DESIGN.md Toggles 절). `hover:bg-secondary`는
 * 프리미티브의 `hover:bg-muted`가 모달 표면(`popover`)과 같은 값이라 사라지는 것을 한 칸 올린다. */
export function PersonaToggleList({
  personaList,
  value,
  onValueChange,
  includeNone,
  "aria-label": ariaLabel,
  "aria-busy": ariaBusy,
}: PersonaToggleListProps) {
  const selectedValue = value ?? NO_PERSONA_VALUE;

  return (
    <ToggleGroup
      type="single"
      variant="list"
      orientation="vertical"
      value={selectedValue}
      // 선택된 항목을 다시 누르면 Radix가 ""를 낸다 — 선택은 언제나 정확히 하나라 지금 값으로 읽는다.
      onValueChange={(next) => {
        const picked = next === "" ? selectedValue : next;
        onValueChange(picked === NO_PERSONA_VALUE ? null : picked);
      }}
      aria-label={ariaLabel}
      aria-busy={ariaBusy}
      className="w-full flex-col gap-1.5"
    >
      {includeNone && (
        <ToggleGroupItem value={NO_PERSONA_VALUE} className={ITEM_CLASS}>
          <span className="flex flex-col gap-0.5 text-left">
            <span className="text-sm font-medium">선택 안 함</span>
            <span className={cn("text-xs break-keep", SECONDARY_TEXT_CLASS)}>프로필 없이 대화해요.</span>
          </span>
        </ToggleGroupItem>
      )}
      {personaList.items.map((persona) => (
        <ToggleGroupItem key={persona.id} value={persona.id} className={ITEM_CLASS}>
          <PersonaSummary
            persona={persona}
            isDefault={persona.id === personaList.defaultPersonaId}
            secondaryTextClassName={SECONDARY_TEXT_CLASS}
          />
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
