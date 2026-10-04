import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Trash2 } from "lucide-react";
import { useId } from "react";

export type ActionChoiceOption<V extends string> = {
  value: V;
  label: string;
  /** 되돌릴 수 없는 처리(삭제). 고르기 전부터 아이콘·글자색으로, 고르면 채움까지 destructive 틴트로 갈린다. */
  tone?: "default" | "destructive";
  disabled?: boolean;
};

type ActionChoiceProps<V extends string> = {
  /** 화면에 보이는 그룹 이름("처리 방법"). 라디오 그룹의 접근 이름이 된다. */
  legend: string;
  options: readonly ActionChoiceOption<V>[];
  value: V | undefined;
  onValueChange: (value: V) => void;
  error?: string;
};

/**
 * 처리 방법 하나를 고르는 세로 라디오 목록. 신고 처리 패널 셋이 모두 이것을 쓴다.
 *
 * 늘 세로다 — 조치가 놓이는 자리가 `lg` 이상은 좁은 조치 열, 미만은 바텀시트라 가로 배치가 맞는 폭이 없다.
 * 가로로 늘어놓고 칸마다 `flex-1` 을 주면, 토글 프리미티브의 `min-w-9` 가 flex 항목의 자동 최소 폭(글자 폭)을
 * 덮어 칸이 36px 까지 줄고 줄바꿈 없는 글자가 옆 칸으로 넘쳐 겹친다. 세로 전폭 + 줄바꿈 허용이면 그 최소 폭이
 * 의미를 잃는다.
 *
 * 다시 눌러 선택을 비우지 않는다(라디오다) — 단일 토글 그룹이 재클릭에 보내는 빈 값은 옵션에서 찾지 못해 버린다.
 * 조치 열(`card`)·시트(`popover`) 위라 hover 채움은 `muted` 가 아니라 `secondary` 다(값이 같아 사라진다).
 */
export function ActionChoice<V extends string>({ legend, options, value, onValueChange, error }: ActionChoiceProps<V>) {
  const id = useId();
  const legendId = `${id}-legend`;
  const errorId = `${id}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <span id={legendId} className="text-sm font-medium text-foreground">
        {legend}
      </span>
      <ToggleGroup
        type="single"
        variant="list"
        orientation="vertical"
        value={value ?? ""}
        onValueChange={(next) => {
          const option = options.find((candidate) => candidate.value === next);
          if (option) onValueChange(option.value);
        }}
        aria-labelledby={legendId}
        aria-invalid={!!error}
        aria-describedby={error ? errorId : undefined}
        className="w-full"
      >
        {options.map((option) => (
          <ToggleGroupItem
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            className={cn(
              "h-auto min-h-10 w-full justify-start py-2 text-left whitespace-normal wrap-anywhere hover:bg-secondary",
              option.tone === "destructive" &&
                "text-destructive-text focus-visible:border-destructive focus-visible:ring-destructive/50 data-[state=on]:border-destructive data-[state=on]:bg-destructive/10 data-[state=on]:text-destructive-text data-[state=on]:hover:bg-destructive/20",
            )}
          >
            {option.tone === "destructive" && <Trash2 aria-hidden />}
            {option.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {!!error && (
        <p id={errorId} role="alert" className="text-xs text-destructive-text">
          {error}
        </p>
      )}
    </div>
  );
}
