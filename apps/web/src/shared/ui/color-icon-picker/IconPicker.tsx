import { cn } from "@ai-character-chat/ui/lib/utils";
import { HelpCircle } from "lucide-react";
import { useRef, useState } from "react";
import { useClickAway } from "react-use";

import { ICON_OPTIONS } from "./icons";

interface IconPickerProps {
  value: string;
  onChange: (value: string) => void;
  triggerLabel: string;
}

/** techspec-builder-story.md §1.2 — lucide-react 아이콘 서브셋(./icons.ts) 중에서만 고르는 피커.
 * ColorPicker와 동일한 relative 트리거 + absolute 패널 구조. */
export function IconPicker({ value, onChange, triggerLabel }: IconPickerProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useClickAway(containerRef, () => setOpen(false));
  const selected = ICON_OPTIONS.find((option) => option.name === value);
  const SelectedIcon = selected?.Icon;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        className="flex size-9 shrink-0 items-center justify-center rounded-md border border-input text-foreground hover:bg-secondary/50"
      >
        {SelectedIcon ? (
          <SelectedIcon aria-hidden className="size-5" />
        ) : (
          <HelpCircle aria-hidden className="size-5 text-muted-foreground" />
        )}
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={triggerLabel}
          className="absolute z-10 mt-2 grid w-40 grid-cols-4 gap-1 rounded-md bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          {ICON_OPTIONS.map((option) => (
            <button
              key={option.name}
              type="button"
              role="option"
              aria-selected={option.name === value}
              aria-label={option.label}
              title={option.label}
              onClick={() => {
                onChange(option.name);
                setOpen(false);
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
