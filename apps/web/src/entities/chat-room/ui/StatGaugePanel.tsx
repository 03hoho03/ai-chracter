import { useEffect, useId, useState, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Popover, PopoverContent, PopoverTrigger } from "@ai-character-chat/ui/components/popover";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react";

import type { StatDef } from "../model/chatRoomState";
import { getIconByName } from "../model/statIcons";
import { readStatusLineCollapsed, writeStatusLineCollapsed } from "../model/statusLineCollapse";
import {
  formatStatDelta,
  formatStatValue,
  HIDDEN_STAT_SIGNAL_TEXT,
  type StatTurnFeedback,
} from "../model/statTurnFeedback";

type StatGaugePanelProps = {
  stats: StatDef[];
  values: Record<string, number>;
  /** 확정된 마지막 턴의 증감·익명 신호·안내 문장. 없으면 칩·신호·안내가 없다(첫 진입·새로고침·재접속, 방 이동·초기화·되돌리기 뒤). */
  feedback?: StatTurnFeedback;
  /** 윗줄에 놓을 지금 장면(장소·시간). 아직 장면 데이터가 없어 지금은 아무도 넘기지 않는다. */
  scene?: string;
  /** 플레이어에게 숨긴 스탯 id — 작가만 보는 빌더 미리보기가 넘긴다. 플레이어 화면에는 숨긴 스탯이 오지 않는다. */
  hiddenStatIds?: ReadonlySet<string>;
};

/** 증감 칩이 떠 있는 시간과 그 끝의 퇴장 페이드. 퇴장 페이드는 줄인 모션에서 꺼지고 타이머는 그대로다. */
const CHIP_VISIBLE_MS = 4000;
const CHIP_EXIT_MS = 300;

/**
 * 스토리 챗의 상태 줄 — contentSnapshot.stats(정의)와 현재값을 statId 로 조인한 게이지 칸들과, 접기·익명 신호를 담은 흐름 줄
 * 하나다(채팅 열 안의 `shrink-0` 줄이라 sticky 띠가 아니다). 캐릭터 챗은 스냅숏이 없어 ChatRoomView 가 그리지 않는다.
 *
 * 칸은 버튼이고 누르면 팝오버로 이름·값·범위·플레이어용 설명을 보인다. 버튼은 자식을 표현용으로 취급해 안의 막대가
 * progressbar 로 읽히지 않으므로, 값은 버튼 접근 이름("호감도 48/100, 자세히")에 싣는다.
 *
 * 한 턴의 변화는 `aria-live` 영역 하나가 한 번에 읽는다. 칩은 화면 전용(`aria-hidden`)이고 버튼 이름에는 증감을 넣지 않아
 * 같은 말이 두 번 읽히지 않는다.
 */
export function StatGaugePanel({ stats, values, feedback, scene, hiddenStatIds }: StatGaugePanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(readStatusLineCollapsed);
  const chipPhase = useChipPhase(feedback);
  const stripId = useId();

  if (stats.length === 0) return null;

  const deltas = chipPhase === "gone" ? {} : (feedback?.deltas ?? {});
  const hasHiddenSignal = feedback?.hiddenSignal ?? false;
  const announcement = feedback?.announcement ?? "";

  function handleToggle() {
    const next = !isCollapsed;
    setIsCollapsed(next);
    writeStatusLineCollapsed(next);
  }

  return (
    <div className="shrink-0 border-b border-border">
      {/* 한 턴의 변화를 한 번에 읽는다. 턴마다 새 자식을 넣어 같은 문장이 두 턴 연달아 와도 다시 읽힌다. */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement && <span key={feedback?.turn}>{announcement}</span>}
      </div>

      {/* 접기 버튼은 접힘과 무관하게 늘 오른쪽 같은 자리의 같은 요소다 — 누른 버튼이 숨거나 사라지면 포커스가 문서 처음으로
          빠진다. 접힘에 따라 바뀌는 것은 왼쪽 내용(요약 줄 / 장면·칸 줄)뿐이다. */}
      <div className={cn("flex items-center pr-2 sm:pr-4", isCollapsed ? "gap-2" : "gap-1")}>
        <div className="min-w-0 flex-1">
          {isCollapsed && (
            <div className="flex min-h-10 items-center gap-2 py-1 pl-4 sm:pl-6">
              {scene ? <SceneLine scene={scene} /> : <span className="flex-1 text-xs text-muted-foreground">스탯 {stats.length}개</span>}
              <CollapsedDeltaChips stats={stats} deltas={deltas} isLeaving={chipPhase === "leaving"} />
            </div>
          )}

          {!isCollapsed && scene && (
            <div className="flex min-h-9 items-center pt-1 pl-4 sm:pl-6">
              <SceneLine scene={scene} />
            </div>
          )}

          {/* 스크롤바를 숨겨도 칸이 버튼이라 Tab 이 칸마다 멈추고, 포커스된 칸은 브라우저가 보이는 곳으로 스크롤한다. */}
          <div
            id={stripId}
            role="group"
            aria-label="스탯"
            hidden={isCollapsed}
            className={cn(
              "flex gap-1 overflow-x-auto px-2.5 pb-1.5 [scrollbar-width:none] sm:px-4.5 [&::-webkit-scrollbar]:hidden",
              !scene && "pt-1.5",
            )}
          >
            {stats.map((stat) => (
              <StatCell
                key={stat.id}
                stat={stat}
                value={values[stat.id] ?? stat.initial}
                delta={deltas[stat.id]}
                isChipLeaving={chipPhase === "leaving"}
                isHidden={hiddenStatIds?.has(stat.id) ?? false}
              />
            ))}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {hasHiddenSignal && <HiddenStatSignal isCompact={isCollapsed} />}
          <Button
            variant="ghost"
            size="icon-sm"
            aria-expanded={!isCollapsed}
            aria-controls={stripId}
            aria-label={isCollapsed ? "상태 줄 펼치기" : "상태 줄 접기"}
            className="text-muted-foreground hover:text-foreground"
            onClick={handleToggle}
          >
            {isCollapsed ? <ChevronDown aria-hidden className="size-4" /> : <ChevronUp aria-hidden className="size-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

type ChipPhase = "shown" | "leaving" | "gone";

/** 턴마다 칩을 4초 띄운다. 새 턴이 오면 `turn` 이 바뀌어 타이머를 다시 잰다. 타이머가 끝난 단계만 state 로 두고, 지금 턴의
 * 단계가 아니면 "보임"으로 읽는다 — 새 턴이 들어온 렌더에서 바로 칩이 선다. */
function useChipPhase(feedback: StatTurnFeedback | undefined): ChipPhase {
  const turn = feedback?.turn;
  const [timed, setTimed] = useState<{ turn: number; phase: "leaving" | "gone" }>();

  useEffect(() => {
    if (turn === undefined) return;
    const leave = window.setTimeout(() => setTimed({ turn, phase: "leaving" }), CHIP_VISIBLE_MS - CHIP_EXIT_MS);
    const gone = window.setTimeout(() => setTimed({ turn, phase: "gone" }), CHIP_VISIBLE_MS);
    return () => {
      window.clearTimeout(leave);
      window.clearTimeout(gone);
    };
  }, [turn]);

  if (turn === undefined) return "gone";
  return timed?.turn === turn ? timed.phase : "shown";
}

type StatCellProps = {
  stat: StatDef;
  value: number;
  delta: number | undefined;
  isChipLeaving: boolean;
  isHidden: boolean;
};

function StatCell({ stat, value, delta, isChipLeaving, isHidden }: StatCellProps) {
  // stat.icon은 "Droplet" 같은 이름 문자열이다 — 컴포넌트로 되돌리지 않으면 글자로 렌더된다.
  const Icon = getIconByName(stat.icon);
  const valueText = formatStatValue(stat, value);
  // 칩이 떠 있는 동안 "/최대"를 접어 칩 자리를 만든다 — 이름 칸이 좁아지지 않게.
  const shownValue = delta === undefined ? valueText : formatStatValue(stat, value, { short: true });
  const label = `${stat.name} ${valueText.value}${valueText.rest}${isHidden ? ", 플레이어에게 숨김" : ""}, 자세히`;

  // w-39(156px) = 칸 글자 폭 144px + 좌우 패딩 12px. 글자 폭 144px 은 --text-xs 가 14px 로 오른 뒤 7~8자 스탯
  // ("손전등 배터리"·"규칙 위반 횟수")이 잘리지 않는 폭으로 잰 값이다(2026-09-11, 8개 스토리·24개 스탯). 그보다 긴
  // 이름("첫서리까지 남은 날")은 말줄임되고 전체 이름은 팝오버가 보인다.
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="flex w-39 shrink-0 flex-col gap-1 rounded-lg p-1.5 text-left hover:bg-secondary/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none aria-expanded:inset-ring aria-expanded:inset-ring-input"
        >
          <span className="flex w-full items-center justify-between gap-1.5 text-xs">
            {/* min-w-0 이 없으면 flex 아이템의 기본 min-width:auto 때문에 truncate가 먹지 않는다. */}
            <span className={cn("flex min-w-0 items-center gap-1 font-medium", isHidden ? "text-muted-foreground" : "text-foreground")}>
              {isHidden ? (
                <span className="shrink-0 text-badge font-semibold">숨김</span>
              ) : (
                Icon && <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              )}
              <span className="truncate">{stat.name}</span>
            </span>
            <span className="flex shrink-0 items-center gap-1 tabular-nums text-muted-foreground">
              <span>
                <span className="text-foreground">{shownValue.value}</span>
                {shownValue.rest}
              </span>
              {delta !== undefined && <DeltaChip delta={delta} isLeaving={isChipLeaving} />}
            </span>
          </span>
          <StatBar stat={stat} value={value} isHidden={isHidden} />
        </button>
      </PopoverTrigger>
      <PopoverContent aria-label={stat.name}>
        <StatDetail stat={stat} value={value} isHidden={isHidden} />
      </PopoverContent>
    </Popover>
  );
}

function StatDetail({ stat, value, isHidden }: { stat: StatDef; value: number; isHidden: boolean }) {
  const Icon = getIconByName(stat.icon);
  const unit = stat.unit ?? "";

  return (
    <div className="flex flex-col gap-2">
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: stat.color }} />
        {Icon && <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 break-keep">{stat.name}</span>
      </p>
      <p className="flex items-baseline justify-between gap-2 text-xs tabular-nums">
        <span>
          <span className="text-sm font-semibold">{value}</span>
          {unit === "%" ? "%" : <span className="font-medium text-muted-foreground"> / {stat.max}{unit}</span>}
        </span>
        <span className="text-muted-foreground">
          범위 {stat.min}–{stat.max}
          {unit}
        </span>
      </p>
      <StatBar stat={stat} value={value} isHidden={isHidden} />
      {stat.playerDescription && <p className="text-xs break-keep">{stat.playerDescription}</p>}
      {isHidden && <p className="text-xs break-keep text-muted-foreground">플레이어에게 숨긴 스탯이에요. 미리보기에서만 보여요.</p>}
    </div>
  );
}

/** 트랙은 `secondary` 다 — 팝오버(`popover`) 위에서 `muted` 는 같은 값이라 사라진다. 채움 색은 작가가 고른 스탯 색(사용자
 * 콘텐츠)이고, 숨긴 스탯은 흐리게 그려 작가에게 "플레이어에게 안 보인다"를 함께 알린다. */
function StatBar({ stat, value, isHidden }: { stat: StatDef; value: number; isHidden: boolean }) {
  const ratio = stat.max > stat.min ? (value - stat.min) / (stat.max - stat.min) : 0;
  const percent = Math.min(100, Math.max(0, ratio * 100));
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-secondary">
      <span
        className={cn(
          "block h-full rounded-full motion-safe:transition-[width] motion-safe:duration-300 motion-safe:ease-out",
          isHidden && "opacity-50",
        )}
        style={{ width: `${percent}%`, backgroundColor: stat.color }}
      />
    </span>
  );
}

/** 무채색 윤곽 알약. 오르내림은 기호와 숫자가 진다 — 색을 붙이지 않는다. 화면 전용이고 같은 내용은 `aria-live` 가 읽는다. */
function DeltaChip({ delta, isLeaving, icon }: { delta: number; isLeaving: boolean; icon?: ReactNode }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex h-4.5 shrink-0 items-center gap-0.5 rounded-full border border-border bg-background px-1.5 text-badge font-semibold text-foreground tabular-nums",
        isLeaving
          ? "motion-safe:animate-out motion-safe:fade-out-0 motion-safe:fill-mode-forwards motion-safe:duration-300"
          : "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200",
      )}
    >
      {icon}
      {formatStatDelta(delta)}
    </span>
  );
}

/** 접힌 줄의 증감 요약 — 칸이 숨었으니 어느 스탯인지 아이콘을 칩에 함께 싣는다. */
function CollapsedDeltaChips({ stats, deltas, isLeaving }: { stats: StatDef[]; deltas: Record<string, number>; isLeaving: boolean }) {
  const changed = stats.filter((stat) => deltas[stat.id] !== undefined);
  if (changed.length === 0) return null;
  return (
    <span className="flex shrink-0 gap-1">
      {changed.map((stat) => {
        const Icon = getIconByName(stat.icon);
        return (
          <DeltaChip
            key={stat.id}
            delta={deltas[stat.id] ?? 0}
            isLeaving={isLeaving}
            icon={Icon && <Icon className="size-3 text-muted-foreground" />}
          />
        );
      })}
    </span>
  );
}

/** 숨긴 스탯이 바뀐 턴의 익명 신호 — 다음 메시지를 보낼 때까지 남는다. 접힌 줄에서는 아이콘만 남기고 이름을 접근 이름으로
 * 둔다. 등장 페이드는 장식이라 `motion-safe:` 로 가드한다. */
function HiddenStatSignal({ isCompact }: { isCompact: boolean }) {
  if (isCompact) {
    return (
      <span
        role="img"
        aria-label={HIDDEN_STAT_SIGNAL_TEXT}
        title={HIDDEN_STAT_SIGNAL_TEXT}
        className="inline-flex size-6 items-center justify-center text-muted-foreground motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200"
      >
        <Sparkles aria-hidden className="size-3.5" />
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-muted-foreground motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
      <Sparkles aria-hidden className="size-3.5" />
      {HIDDEN_STAT_SIGNAL_TEXT}
    </span>
  );
}

/** 장면 한 줄. 길면 말줄임되고 전체 글은 `title` 로 남는다. */
function SceneLine({ scene }: { scene: string }) {
  return (
    <span className="min-w-0 flex-1 truncate text-xs font-medium" title={scene}>
      {scene}
    </span>
  );
}
