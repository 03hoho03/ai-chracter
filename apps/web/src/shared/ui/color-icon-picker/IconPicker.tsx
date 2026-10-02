import { cn } from "@ai-character-chat/ui/lib/utils";
import { HelpCircle, type LucideIcon } from "lucide-react";

import { useGridPicker } from "./useGridPicker";

/** 피커가 고를 수 있는 아이콘 하나. 목록은 도메인이 쥐고 있고(스탯은
 * `entities/chat-room/model/statIcons.ts`) 이 타입만 둘 사이의 계약이다. */
export type IconPickerOption = {
  name: string;
  label: string;
  Icon: LucideIcon;
}

type IconPickerProps = {
  value: string;
  onChange: (value: string) => void;
  options: readonly IconPickerOption[];
  triggerLabel: string;
  /** 오류가 있을 때 트리거를 오류 상태로 알리고(`Input` 과 같은 붉은 보더), 오류 문장을 설명으로 잇는다. */
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}

/** lucide-react 아이콘 서브셋 중에서만 고르는 피커. 서브셋은
 * 도메인 어휘라 `options`로 주입받는다.
 * ColorPicker와 동일한 relative 트리거 + absolute 패널 구조이고, 열림·키보드 동작도 같은
 * `useGridPicker`를 쓴다(4열 격자). */
export function IconPicker({
  value,
  onChange,
  options,
  triggerLabel,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
}: IconPickerProps) {
  const selectedIndex = options.findIndex((option) => option.name === value);
  const selected = options[selectedIndex];
  const picker = useGridPicker({ optionCount: options.length, selectedIndex, columns: 4 });
  const SelectedIcon = selected?.Icon;

  return (
    <div ref={picker.containerRef} className="relative">
      <button
        ref={picker.triggerRef}
        type="button"
        aria-label={triggerLabel}
        aria-haspopup="listbox"
        aria-expanded={picker.isOpen}
        aria-invalid={ariaInvalid}
        aria-describedby={ariaDescribedBy}
        onClick={picker.toggle}
        className="flex size-9 shrink-0 items-center justify-center rounded-md border border-input text-foreground hover:bg-secondary/50 aria-invalid:border-destructive"
      >
        {SelectedIcon ? (
          <SelectedIcon aria-hidden className="size-5" />
        ) : (
          <HelpCircle aria-hidden className="size-5 text-muted-foreground" />
        )}
      </button>

      {picker.isOpen && (
        <div
          role="listbox"
          aria-label={triggerLabel}
          onKeyDown={picker.handleListKeyDown}
          className="absolute z-10 mt-2 grid w-40 grid-cols-4 gap-1 rounded-md bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          {options.map((option, index) => (
            <button
              key={option.name}
              {...picker.optionProps(index)}
              type="button"
              role="option"
              aria-selected={option.name === value}
              aria-label={option.label}
              title={option.label}
              onClick={() => {
                onChange(option.name);
                picker.closeAndRestoreFocus();
              }}
              className={cn(
                "flex size-8 items-center justify-center rounded-md hover:bg-accent",
                option.name === value && "bg-accent",
              )}
            >
              <option.Icon aria-hidden className="size-4" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
