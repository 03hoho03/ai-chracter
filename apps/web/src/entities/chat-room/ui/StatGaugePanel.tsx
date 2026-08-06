import { getIconByName } from "../../../shared/ui/color-icon-picker";
import type { StatDef } from "../api/chat-room";

interface StatGaugePanelProps {
  stats: StatDef[];
  values: Record<string, number>;
}

// US-060 — contentSnapshot.stats(정의)와 ChatRoomState.stats(현재값)를 statId로 조인해 게이지로
// 상시 노출한다. 스토리 챗 전용(캐릭터 챗은 room.contentSnapshot이 없어 ChatRoomView가 렌더링하지 않음).
export function StatGaugePanel({ stats, values }: StatGaugePanelProps) {
  if (stats.length === 0) return null;

  return (
    <div role="group" aria-label="스탯" className="flex shrink-0 gap-4 overflow-x-auto border-b border-border px-4 py-2.5">
      {stats.map((stat) => {
        const value = values[stat.id] ?? stat.initial;
        const ratio = stat.max > stat.min ? (value - stat.min) / (stat.max - stat.min) : 0;
        const percent = Math.min(100, Math.max(0, ratio * 100));
        // stat.icon은 "Droplet" 같은 이름 문자열이다 — 컴포넌트로 되돌리지 않으면 글자로 렌더된다.
        const Icon = getIconByName(stat.icon);

        // w-32: 시드 스탯 이름의 85%가 7자 이하이고, 그 길이까지는 아이콘·값과 나란히 놓아도
        // 안 잘린다(w-28은 5자에서 잘렸다). 더 긴 이름은 의도대로 truncate + title로 노출.
        return (
          <div key={stat.id} className="flex w-32 shrink-0 flex-col gap-1">
            <div className="flex items-center justify-between gap-1.5 text-xs">
              {/* min-w-0 이 없으면 flex 아이템의 기본 min-width:auto 때문에 truncate가 먹지 않는다. */}
              <span className="flex min-w-0 items-center gap-1 font-medium text-foreground">
                {Icon && <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />}
                <span className="truncate" title={stat.name}>
                  {stat.name}
                </span>
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {value}
                {stat.unit ?? ""}
              </span>
            </div>
            <div
              role="progressbar"
              aria-label={stat.name}
              aria-valuemin={stat.min}
              aria-valuemax={stat.max}
              aria-valuenow={value}
              className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
            >
              <div
                className="h-full rounded-full motion-safe:transition-[width] motion-safe:duration-300 motion-safe:ease-out"
                style={{ width: `${percent}%`, backgroundColor: stat.color }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
