import { COLOR_PALETTE } from "@ai-character-chat/ui/lib/color-palette";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { PICKER_TRIGGER_CLASSNAME, triggerAccessibleName } from "./pickerTrigger";
import { useGridPicker } from "./useGridPicker";

type ColorPickerProps = {
  value: string;
  onChange: (value: string) => void;
  /** 무엇을 고르는지(예: "색"). 트리거 이름은 여기에 지금 고른 색 이름을 붙여 만든다 — 열지 않고도 값을 들을 수 있게. */
  label: string;
  /** 비었을 때 트리거 이름에 "(필수)"를 붙인다. */
  isRequired?: boolean;
  /** 오류가 있을 때 트리거를 오류 상태로 알리고(`Input` 과 같은 붉은 보더), 오류 문장을 설명으로 잇는다. */
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}

/** 자유 컬러피커가 아니라 사전 정의 팔레트(packages/ui의
 * COLOR_PALETTE) 중에서만 고르는 피커. Popover/Command 프리미티브가 없어
 * relative 트리거 + 조건부 absolute 패널로 구현한다.
 *
 * 선택 표시는 스와치 위 글리프가 아니라 스와치를 둘러싼 보더가 진다 — 지우기 전 잉크였던 흰색은 팔레트 10색 중
 * 5색에서(다크 `foreground`로 바꿔 달아도 6색에서) 3:1을 못 넘겨 글리프가 배경에 묻혔다. 보더는 스와치가 아니라 `popover` 지면
 * 위에 앉으므로 스와치 색과 무관하게 대비가 고정된다(`foreground`↔`popover` 다크 14.4 / 라이트 15.9).
 * 열림·키보드 동작은 `useGridPicker`가 진다(5열 격자). */
export function ColorPicker({
  value,
  onChange,
  label,
  isRequired = false,
  "aria-invalid": ariaInvalid,
  "aria-describedby": ariaDescribedBy,
}: ColorPickerProps) {
  const selectedIndex = COLOR_PALETTE.findIndex((swatch) => swatch.value === value);
  const selected = COLOR_PALETTE[selectedIndex];
  const picker = useGridPicker({ optionCount: COLOR_PALETTE.length, selectedIndex, columns: 5 });
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
        className={PICKER_TRIGGER_CLASSNAME}
      >
        {selected ? (
          <span aria-hidden className="size-5 rounded-full" style={{ backgroundColor: selected.value }} />
        ) : (
          <span aria-hidden className="size-5 rounded-full border border-dashed border-muted-foreground" />
        )}
      </button>

      {picker.isOpen && (
        <div
          role="listbox"
          aria-label={label}
          onKeyDown={picker.handleListKeyDown}
          className="absolute z-10 mt-2 grid w-max grid-cols-5 gap-1 rounded-md bg-popover p-2 text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          {COLOR_PALETTE.map((swatch, index) => (
            // 옵션 버튼은 스와치보다 한 둘레 큰 칸이고, 선택·포커스·hover 는 전부 스와치 밖 `popover` 지면에 그린다.
            // 포커스를 스와치 위에 그리면 핑크 링(`ring`)이 로즈·푸시아 스와치에 묻힌다.
            // 선택은 `foreground` 보더, 키보드 포커스는 링이다. 링은 이웃 트리거와 같은 굵기다 — 팝오버 목록의 1px
            // `inset-ring`(3:1 을 지는 실선)에 하우스 레시피의 3px 반투명 링을 바깥에 더한다. 1px 만이면 스와치 둘레에 붙어
            // 스와치 테두리로 읽혔다. 예전처럼 선택을 `ring` 으로 그리면 포커스 링과 같은 `--tw-ring-*` 변수를 써서 한쪽이
            // 다른 쪽을 덮어쓰는데, 보더와 링은 다른 속성이라 겹쳐도 둘 다 남는다. 바깥 링(3px)은 칸 사이 간격(4px) 안에 든다.
            // 터치에서만 칸을 40px로 키운다 — 스와치 크기는 그대로 두고 누를 자리만 넓힌다.
            <button
              key={swatch.name}
              {...picker.optionProps(index)}
              type="button"
              role="option"
              aria-selected={swatch.value === value}
              aria-label={swatch.label}
              title={swatch.label}
              onClick={() => {
                onChange(swatch.value);
                picker.closeAndRestoreFocus();
              }}
              className={cn(
                "flex size-9 items-center justify-center rounded-full border-2 border-transparent outline-none hover:bg-secondary focus-visible:inset-ring-1 focus-visible:inset-ring-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:size-10",
                swatch.value === value && "border-foreground",
              )}
            >
              <span aria-hidden className="size-7 rounded-full" style={{ backgroundColor: swatch.value }} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
