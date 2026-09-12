import { COLOR_PALETTE } from "@ai-character-chat/ui/lib/color-palette";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef, useState } from "react";
import { useClickAway } from "react-use";

type ColorPickerProps = {
  value: string;
  onChange: (value: string) => void;
  triggerLabel: string;
}

/** techspec-builder-story.md §1.2 — 자유 컬러피커가 아니라 사전 정의 팔레트(packages/ui의
 * COLOR_PALETTE) 중에서만 고르는 피커. Popover/Command 프리미티브가 없어 US-066과 동일하게
 * relative 트리거 + 조건부 absolute 패널로 구현한다.
 *
 * 선택 표시는 스와치 위 글리프가 아니라 링이 진다 — 지우기 전 잉크였던 흰색은 팔레트 10색 중
 * 5색에서(다크 `foreground`로 바꿔 달아도 6색에서) 3:1을 못 넘겨 글리프가 배경에 묻혔다. 링은 스와치가 아니라 `popover` 지면
 * 위에 앉으므로 스와치 색과 무관하게 대비가 고정된다(`foreground`↔`popover` 다크 14.4 / 라이트 15.9). */
export function ColorPicker({ value, onChange, triggerLabel }: ColorPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useClickAway(containerRef, () => setIsOpen(false));
  const selected = COLOR_PALETTE.find((swatch) => swatch.value === value);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={triggerLabel}
        aria-haspopup="true"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex size-9 shrink-0 items-center justify-center rounded-md border border-input hover:bg-secondary/50"
      >
        {selected ? (
          <span aria-hidden className="size-5 rounded-full" style={{ backgroundColor: selected.value }} />
        ) : (
          <span aria-hidden className="size-5 rounded-full border border-dashed border-muted-foreground" />
        )}
      </button>

      {isOpen && (
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
                setIsOpen(false);
              }}
              // ring-2 + ring-offset-2는 스와치 밖으로 4px 나가고 그리드 간격은 gap-1.5(6px)다.
              // 선택은 언제나 하나뿐이라 이웃 스와치에는 링이 없고, 4px는 그 6px 안에서만 자란다.
              // 이 버튼에는 하우스 포커스 레시피(`focus-visible:ring-3 ring-ring/50`, DESIGN.md §6)를 얹지 않는다 —
              // 같은 `--tw-ring-*` 변수를 쓰므로 특이도에서 이겨 선택 링을 덮어쓴다. 포커스는 UA 아웃라인이 진다
              // (preflight가 지우지 않는다). 선택을 inset-ring으로 내리는 대안은 잉크가 스와치 위로 돌아와 위 3:1 문제를 되살린다.
              className={cn(
                "size-7 rounded-full",
                swatch.value === value && "ring-2 ring-foreground ring-offset-2 ring-offset-popover",
              )}
              style={{ backgroundColor: swatch.value }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
