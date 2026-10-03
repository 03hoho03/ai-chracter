import { cn } from "@ai-character-chat/ui/lib/utils";
import type { LucideIcon } from "lucide-react";

import { PICKER_TRIGGER_CLASSNAME, triggerAccessibleName } from "./pickerTrigger";
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
  /** 무엇을 고르는지(예: "아이콘"). 트리거 이름은 여기에 지금 고른 값을 붙여 만든다 — 열지 않고도 값을 들을 수 있게. */
  label: string;
  /** 비었을 때 트리거 이름에 "(필수)"를 붙인다. */
  isRequired?: boolean;
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
  label,
  isRequired = false,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
}: IconPickerProps) {
  const selectedIndex = options.findIndex((option) => option.name === value);
  const selected = options[selectedIndex];
  const picker = useGridPicker({ optionCount: options.length, selectedIndex, columns: 4 });
  const SelectedIcon = selected?.Icon;
  const triggerName = triggerAccessibleName(label, selected?.label, isRequired);

  return (
    <div ref={picker.containerRef} className="relative">
      <button
        ref={picker.triggerRef}
        type="button"
        aria-label={triggerName}
        aria-haspopup="listbox"
        aria-expanded={picker.isOpen}
        aria-invalid={ariaInvalid}
        aria-describedby={ariaDescribedBy}
        onClick={picker.toggle}
        className={cn(PICKER_TRIGGER_CLASSNAME, "text-foreground")}
      >
        {/* 빈 자리는 색 트리거와 같은 점선 자리표시다 — 물음표 아이콘은 '도움말' 버튼으로 읽혔다. 네모는 둥근 색 자리표시와
            모양으로 갈린다. */}
        {SelectedIcon ? (
          <SelectedIcon aria-hidden className="size-5" />
        ) : (
          <span aria-hidden className="size-5 rounded-md border border-dashed border-muted-foreground" />
        )}
      </button>

      {picker.isOpen && (
        <div
          role="listbox"
          aria-label={label}
          onKeyDown={picker.handleListKeyDown}
          className="absolute z-10 mt-2 grid w-max grid-cols-4 gap-1 rounded-md bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
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
              // 고른 옵션은 채움에 `foreground` 보더를 더한다. 채움(`secondary`)만으로는 팝오버 지면 대비 약 1.14:1이라
              // 고른 옵션이 안 보이고, hover 와 같은 채움이라 마우스를 올린 옵션과도 갈리지 않는다 — 보더가 3:1을 진다.
              // 포커스는 키보드 포커스에만 링으로 진다 — 팝오버 목록의 1px `inset-ring` 에 하우스 레시피의 3px 반투명 링을 더해
              // 이웃 트리거와 같은 굵기다. 보더와 다른 속성이라 둘이 겹쳐도 서로 지우지 않고, 바깥 링은 칸 사이 간격(4px) 안에 든다.
              // 터치에서만 40px로 키운다 — 32px는 손가락으로 이웃 옵션을 누르기 쉽고, 마우스 데스크톱의 밀도는 그대로 둔다.
              className={cn(
                "flex size-8 items-center justify-center rounded-md border-2 border-transparent outline-none hover:bg-secondary focus-visible:inset-ring-1 focus-visible:inset-ring-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:size-10",
                option.name === value && "border-foreground bg-secondary",
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
