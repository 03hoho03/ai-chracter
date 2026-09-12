import { cn } from "@ai-character-chat/ui/lib/utils";
import { HelpCircle, type LucideIcon } from "lucide-react";
import { useRef, useState } from "react";
import { useClickAway } from "react-use";

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
}

/** techspec-builder-story.md §1.2 — lucide-react 아이콘 서브셋 중에서만 고르는 피커. 서브셋은
 * 도메인 어휘라 `options`로 주입받는다(fe-convention-refactor-goal-prompt.md R-8).
 * ColorPicker와 동일한 relative 트리거 + absolute 패널 구조. */
export function IconPicker({ value, onChange, options, triggerLabel }: IconPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useClickAway(containerRef, () => setIsOpen(false));
  const selected = options.find((option) => option.name === value);
  const SelectedIcon = selected?.Icon;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex size-9 shrink-0 items-center justify-center rounded-md border border-input text-foreground hover:bg-secondary/50"
      >
        {SelectedIcon ? (
          <SelectedIcon aria-hidden className="size-5" />
        ) : (
          <HelpCircle aria-hidden className="size-5 text-muted-foreground" />
        )}
      </button>

      {isOpen && (
        <div
          role="listbox"
          aria-label={triggerLabel}
          className="absolute z-10 mt-2 grid w-40 grid-cols-4 gap-1 rounded-md bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          {options.map((option) => (
            <button
              key={option.name}
              type="button"
              role="option"
              aria-selected={option.name === value}
              aria-label={option.label}
              title={option.label}
              onClick={() => {
                onChange(option.name);
                setIsOpen(false);
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
