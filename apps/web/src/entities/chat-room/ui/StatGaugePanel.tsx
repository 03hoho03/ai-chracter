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

        return (
          <div key={stat.id} className="flex w-28 shrink-0 flex-col gap-1">
            <div className="flex items-center justify-between gap-1.5 text-xs">
              <span className="truncate font-medium text-foreground">
                {stat.icon} {stat.name}
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
