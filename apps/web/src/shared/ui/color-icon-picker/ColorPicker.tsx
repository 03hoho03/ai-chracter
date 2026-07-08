import { COLOR_PALETTE } from "@ai-character-chat/ui/lib/color-palette";
import { Check } from "lucide-react";
import { useRef, useState } from "react";
import { useClickAway } from "react-use";

interface ColorPickerProps {
  value: string;
  onChange: (value: string) => void;
  triggerLabel: string;
}

/** techspec-builder-story.md §1.2 — 자유 컬러피커가 아니라 사전 정의 팔레트(packages/ui의
 * COLOR_PALETTE) 중에서만 고르는 피커. Popover/Command 프리미티브가 없어 US-066과 동일하게
 * relative 트리거 + 조건부 absolute 패널로 구현한다. */
export function ColorPicker({ value, onChange, triggerLabel }: ColorPickerProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useClickAway(containerRef, () => setOpen(false));
  const selected = COLOR_PALETTE.find((swatch) => swatch.value === value);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border hover:bg-secondary/50"
      >
        {selected ? (
          <span aria-hidden className="size-5 rounded-full" style={{ backgroundColor: selected.value }} />
        ) : (
          <span aria-hidden className="size-5 rounded-full border border-dashed border-muted-foreground" />
        )}
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={triggerLabel}
          className="absolute z-10 mt-2 grid w-48 grid-cols-5 gap-1.5 rounded-md bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          {COLOR_PALETTE.map((swatch) => (
            <button
              key={swatch.name}
              type="button"
              role="option"
              aria-selected={swatch.value === value}
              aria-label={swatch.label}
              title={swatch.label}
              onClick={() => {
                onChange(swatch.value);
                setOpen(false);
              }}
              className="flex size-7 items-center justify-center rounded-full"
              style={{ backgroundColor: swatch.value }}
            >
              {swatch.value === value && <Check aria-hidden className="size-4 text-white" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
