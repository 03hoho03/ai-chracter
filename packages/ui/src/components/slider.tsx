import * as React from "react"
import { Slider as SliderPrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

function Slider({
  className,
  defaultValue,
  value,
  min = 0,
  max = 100,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root>) {
  const _values = React.useMemo(() => {
    if (Array.isArray(value)) return value
    if (Array.isArray(defaultValue)) return defaultValue
    return [min, max]
  }, [value, defaultValue, min, max])

  return (
    <SliderPrimitive.Root
      data-slot="slider"
      defaultValue={defaultValue}
      value={value}
      min={min}
      max={max}
      className={cn(
        "relative flex w-full touch-none items-center select-none data-disabled:opacity-50 data-vertical:h-full data-vertical:min-h-40 data-vertical:w-auto data-vertical:flex-col",
        className
      )}
      {...props}
    >
      <SliderPrimitive.Track
        data-slot="slider-track"
        // 상류 shadcn 은 트랙이 `bg-muted` 인데 이 시스템에서는 **`popover`/`card` 표면 위에서 사라진다** —
        // `--muted` 와 `--popover` 가 다크 0.210, 라이트 0.970 으로 **값이 완전히 같아 대비가 1.0000:1** 이다.
        // 모달 안에 놓인 슬라이더가 트랙 없이 썸만 점으로 보였다(2026-09-15 실사용 제보).
        // `secondary`(다크 0.260 / 라이트 0.930)는 배경·popover 양쪽에서 모두 살아남는다.
        className="relative grow overflow-hidden rounded-full bg-secondary data-horizontal:h-1 data-horizontal:w-full data-vertical:h-full data-vertical:w-1"
      >
        <SliderPrimitive.Range
          data-slot="slider-range"
          className="absolute bg-primary select-none data-horizontal:h-full data-vertical:w-full"
        />
      </SliderPrimitive.Track>
      {Array.from({ length: _values.length }, (_, index) => (
        <SliderPrimitive.Thumb
          data-slot="slider-thumb"
          key={index}
          className="relative block size-3 shrink-0 rounded-full border border-ring bg-background ring-ring/50 motion-safe:transition-[color,box-shadow] select-none after:absolute after:-inset-2 hover:ring-3 focus-visible:ring-3 focus-visible:outline-hidden active:ring-3 data-disabled:pointer-events-none"
        />
      ))}
    </SliderPrimitive.Root>
  )
}

export { Slider }
