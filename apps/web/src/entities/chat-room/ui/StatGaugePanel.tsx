import { useEffect, useId, useState, type FocusEvent, type ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Popover, PopoverContent, PopoverTrigger } from "@ai-character-chat/ui/components/popover";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, ChevronUp, Clock, MapPin, Sparkles } from "lucide-react";

import type { StatDef } from "../model/chatRoomState";
import { getIconByName } from "../model/statIcons";
import { readStatusLineCollapsed, writeStatusLineCollapsed } from "../model/statusLineCollapse";
import {
  formatStatDelta,
  formatStatValue,
  HIDDEN_STAT_SIGNAL_TEXT,
  isUnshownTurnFeedback,
  turnFeedbackKey,
  type StatTurnFeedback,
} from "../model/statTurnFeedback";
import { hasSceneText, type StoryScene } from "../model/storyScene";

type StatGaugePanelProps = {
  stats: StatDef[];
  values: Record<string, number>;
  /** 확정된 마지막 턴의 증감·익명 신호·안내 문장. 없으면 칩·신호·안내가 없다(첫 진입·새로고침·재접속, 방 이동·초기화·되돌리기 뒤). */
  feedback?: StatTurnFeedback;
  /** 윗줄에 놓을 지금 장면(장소·시간, 작가 매크로를 펼친 글). 장면 헤더를 끈 작품은 넘기지 않고, 장소·시간이 둘 다 비면 장면
   * 줄이 없다. */
  scene?: StoryScene;
  /** 플레이어에게 숨긴 스탯 id — 작가만 보는 빌더 미리보기가 넘긴다. 플레이어 화면에는 숨긴 스탯이 오지 않는다. */
  hiddenStatIds?: ReadonlySet<string>;
};

/** 증감 칩이 떠 있는 시간과 그 끝의 퇴장 페이드. 퇴장 페이드는 줄인 모션에서 꺼지고 타이머는 그대로다. */
const CHIP_VISIBLE_MS = 4000;
const CHIP_EXIT_MS = 300;

/**
 * 스토리 챗의 상태 줄 — 지금 장면(장소·시간) 한 줄과, contentSnapshot.stats(정의)와 현재값을 statId 로 조인한 게이지 칸들,
 * 접기·익명 신호를 담은 흐름 줄 하나다(채팅 열 안의 `shrink-0` 줄이라 sticky 띠가 아니다). 캐릭터 챗은 스냅숏이 없어
 * ChatRoomView 가 그리지 않는다. 보이는 스탯이 없는 작품도 장면이나 익명 신호가 있으면 그 줄만 그린다 — 접을 칸이 없어 접기
 * 버튼도 없다.
 *
 * 칸은 버튼이고 누르면 팝오버로 이름·값·범위·플레이어용 설명을 보인다. 버튼은 자식을 표현용으로 취급해 안의 막대가
 * progressbar 로 읽히지 않으므로, 값은 버튼 접근 이름("호감도 48/100, 자세히")에 싣는다.
 *
 * 한 턴의 변화는 `aria-live` 영역 하나가 한 번에 읽는다. 칩은 화면 전용(`aria-hidden`)이고 버튼 이름에는 증감을 넣지 않아
 * 같은 말이 두 번 읽히지 않는다.
 */
export function StatGaugePanel({ stats, values, feedback, scene, hiddenStatIds }: StatGaugePanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(readStatusLineCollapsed);
  const unshownFeedback = useUnshownTurnFeedback(feedback);
  const chipPhase = useChipPhase(unshownFeedback);
  const stripId = useId();

  const hasScene = hasSceneText(scene);
  const announcement = unshownFeedback?.announcement ?? "";

  // 한 턴의 변화(스탯 증감·장면 변화·익명 신호)를 한 번에 읽는다. 턴마다 새 자식을 넣어 같은 문장이 두 턴 연달아 와도 다시
  // 읽힌다. 이미 읽은 응답으로 돌아오면 자식을 넣지 않는다(`useUnshownTurnFeedback`).
  const liveRegion = (
    <div aria-live="polite" aria-atomic="true" className="sr-only">
      {announcement && <span key={unshownFeedback?.turn}>{announcement}</span>}
    </div>
  );

  const deltas = chipPhase === "gone" ? {} : (feedback?.deltas ?? {});
  const hasHiddenSignal = feedback?.hiddenSignal ?? false;

  function handleToggle() {
    const next = !isCollapsed;
    setIsCollapsed(next);
    writeStatusLineCollapsed(next);
  }

  // 스탯이 없고 장면도 신호도 없으면 보이는 줄은 없지만 빈 라이브 영역은 남긴다 — 첫 장면이 생기는 턴에 안내를 품은 영역이
  // 그제야 삽입되면 스크린리더가 읽지 않는다. 줄이 생겨도 같은 바깥 상자의 같은 자리라 영역이 다시 마운트되지 않는다.
  // 영역은 `sr-only` 이고 줄이 없을 때 바깥 상자는 높이 0 이라 배치에 아무것도 더하지 않는다. 장면 없이 익명 신호만 있는
  // 턴에도 줄을 그린다 — 라이브 영역이 읽는 신호를 화면에서도 보여야 한다. 신호는 장면이 있을 때처럼 오른쪽 끝에 선다.
  if (stats.length === 0) {
    const hasLine = hasScene || hasHiddenSignal;
    return (
      <div className={cn("shrink-0", hasLine && "border-b border-border")}>
        {liveRegion}
        {hasLine && (
          <div className="flex min-h-10 items-center justify-end gap-2 py-1 pr-2 pl-4 sm:pr-4 sm:pl-6">
            {hasScene && <SceneLine scene={scene} />}
            {hasHiddenSignal && <HiddenStatSignal isCompact={false} />}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="shrink-0 border-b border-border">
      {liveRegion}

      {/* 접기 버튼은 접힘과 무관하게 늘 오른쪽 같은 자리의 같은 요소다 — 누른 버튼이 숨거나 사라지면 포커스가 문서 처음으로
          빠진다. 접힘에 따라 바뀌는 것은 왼쪽 내용(요약 줄 / 장면·칸 줄)뿐이다. */}
      <div className={cn("flex items-center pr-2 sm:pr-4", isCollapsed ? "gap-2" : "gap-1")}>
        <div className="min-w-0 flex-1">
          {isCollapsed && (
            <div className="flex min-h-10 items-center gap-2 py-1 pl-4 sm:pl-6">
              {hasScene ? (
                <SceneLine scene={scene} />
              ) : (
                <span className="flex-1 text-xs text-muted-foreground">스탯 {stats.length}개</span>
              )}
              <CollapsedDeltaChips stats={stats} deltas={deltas} isLeaving={chipPhase === "leaving"} />
            </div>
          )}

          {!isCollapsed && hasScene && (
            <div className="flex min-h-9 items-center pt-1 pl-4 sm:pl-6">
              <SceneLine scene={scene} />
            </div>
          )}

          {/* 스크롤바를 숨겨도 칸이 버튼이라 Tab 이 칸마다 멈춘다. 일부만 보이는 칸은 브라우저가 포커스 때 스크롤하지 않으므로
              칸이 키보드 포커스를 받을 때 직접 보이는 곳으로 당긴다(`revealFocusedCell`). 당긴 칸이 줄 끝에 붙어 포커스 링이 잘리지
              않게 스크롤 여백을 좌우 패딩과 같게 둔다. */}
          <div
            id={stripId}
            role="group"
            aria-label="스탯"
            hidden={isCollapsed}
            className={cn(
              "flex scroll-px-2.5 gap-1 overflow-x-auto px-2.5 pb-1.5 [scrollbar-width:none] sm:scroll-px-4.5 sm:px-4.5 [&::-webkit-scrollbar]:hidden",
              !hasScene && "pt-1.5",
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

/** 이 탭에서 칩·안내를 이미 띄운 응답의 키. 다른 방에 다녀오는 동안 상태 줄이 언마운트돼도 남아야 해서 컴포넌트 밖에 둔다.
 * 새로고침하면 비지만, 그때는 확정된 턴 알림 자체가 없다. */
const shownTurnFeedbackKeys = new Set<string>();

/** 알림 가운데 칩·안내를 띄울 몫만 돌려준다 — 응답 하나에 한 번이다. 판정은 알림이 바뀐 렌더에서 한 번 하고 그 알림이
 * 머무는 동안 유지한다. 그래서 띄운 직후 키를 기억해도 이 마운트의 칩 4초는 끝까지 가고, 다른 방에 갔다 돌아오면(다시
 * 마운트됐든 아니든) 같은 응답은 칩도 안내도 없다. 익명 신호는 알림 원본을 따라 다음 메시지까지 남는다. */
function useUnshownTurnFeedback(feedback: StatTurnFeedback | undefined): StatTurnFeedback | undefined {
  const key = feedback && turnFeedbackKey(feedback);
  const [decision, setDecision] = useState(() => ({
    key,
    isUnshown: isUnshownTurnFeedback(feedback, shownTurnFeedbackKeys),
  }));
  let current = decision;
  if (decision.key !== key) {
    current = { key, isUnshown: isUnshownTurnFeedback(feedback, shownTurnFeedbackKeys) };
    setDecision(current);
  }

  useEffect(() => {
    if (current.isUnshown && current.key !== undefined) shownTurnFeedbackKeys.add(current.key);
  }, [current.isUnshown, current.key]);

  return current.isUnshown ? feedback : undefined;
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
          onFocus={revealFocusedCell}
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
        <span className="min-w-0 break-keep wrap-anywhere">{stat.name}</span>
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
      {/* 숨긴 스탯의 플레이어용 설명은 플레이어에게 가지 않는다 — 작가 미리보기도 그대로 보이지 않게 둔다. 띄어쓰기 없는 긴
          글은 `break-keep` 만으로는 끊을 자리가 없어 팝오버 밖으로 넘치므로, 넘칠 때만 아무 데서나 끊는다(위 이름 줄도 같다). */}
      {stat.playerDescription && !isHidden && <p className="text-xs break-keep wrap-anywhere">{stat.playerDescription}</p>}
      {isHidden && <p className="text-xs break-keep text-muted-foreground">플레이어에게 숨긴 스탯이에요. 미리보기에서만 보여요.</p>}
    </div>
  );
}

/** 키보드로 포커스된 칸을 가로 줄 안에서 보이는 곳으로 당긴다. 브라우저는 포커스 때 요소가 조금이라도 보이면 스크롤하지
 * 않아, 끝에 걸쳐 일부만 보이는 칸이 가려진 채 남는다. 마우스·터치 포커스(`:focus-visible` 아님)에는 당기지 않는다 —
 * 누르는 순간 줄이 움직이면 손을 뗄 때 포인터가 칸 밖이라 클릭이 칸에 닿지 않고 팝오버가 안 열린다. `nearest` 라 이미 다
 * 보이는 칸은 움직이지 않고, 즉시 이동이라 줄인 모션 설정과 부딪히지 않는다. */
function revealFocusedCell(event: FocusEvent<HTMLButtonElement>) {
  if (!event.currentTarget.matches(":focus-visible")) return;
  event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
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

/**
 * 장면 한 줄 — 장소 · 시간. 하나만 있으면 그것만 보이고 줄 폭을 다 쓴다. 둘 다 줄에 들어가면 자르지 않고, 넘치면 장소가
 * 먼저 말줄임된다. 시간은 줄 폭의 절반까지는 통째로 남는다 — 절반의 기준이 줄(컨테이너)이어야 한다. 내용 폭으로 줄어든 글
 * 묶음을 기준으로 잡으면 짧은 시간도 늘 반쯤에서 잘린다. 잘린 글은 `title` 이 아니라 눌러 여는 팝오버로 전체를 보인다(`title` 은 터치·키보드로 열 수 없다). 버튼 이름에 전체 글을
 * 실어 스크린리더는 누르지 않아도 다 읽는다.
 *
 * 장면이 바뀌면 글을 다시 마운트해 페이드로 들인다 — 장식 전환이라 `motion-safe:` 로 가드하고, 처음 그릴 때(방에 들어올 때)는
 * 페이드하지 않는다. 한 번 바뀐 뒤로는 모든 변화가 페이드한다 — 앞서 본 장면으로 돌아가는 변화(되돌리기, A→B→A 턴)도
 * 바뀐 것이다. 글은 장면이 바뀔 때만 다시 마운트되므로 클래스를 계속 달아 두어도 같은 장면에서 다시 페이드하지 않는다.
 */
function SceneLine({ scene }: { scene: StoryScene }) {
  const { place, time } = scene;
  const sceneKey = `${place ?? ""}\n${time ?? ""}`;
  const [firstSceneKey] = useState(sceneKey);
  const [hasChanged, setHasChanged] = useState(false);
  if (!hasChanged && sceneKey !== firstSceneKey) setHasChanged(true);
  const Icon = place === undefined ? Clock : MapPin;
  const label = ["지금 장면", place && `장소 ${place}`, time && `시간 ${time}`].filter(Boolean).join(", ");

  return (
    <div className="@container flex min-w-0 flex-1">
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={`${label}, 자세히`}
            className="-mx-1 flex max-w-full min-w-0 items-center rounded-md px-1 py-0.5 text-left text-xs hover:bg-secondary/50 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none aria-expanded:inset-ring aria-expanded:inset-ring-input"
          >
            <span
              key={sceneKey}
              className={cn(
                "flex min-w-0 items-center gap-1.5",
                hasChanged && "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-300",
              )}
            >
              <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
              {place !== undefined && <span className="min-w-0 truncate font-medium">{place}</span>}
              {place !== undefined && time !== undefined && (
                <span aria-hidden className="shrink-0 text-muted-foreground">
                  ·
                </span>
              )}
              {time !== undefined && (
                <span
                  className={cn(
                    "truncate",
                    place === undefined ? "min-w-0 font-medium" : "max-w-[50cqw] shrink-0 text-muted-foreground",
                  )}
                >
                  {time}
                </span>
              )}
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent aria-label="지금 장면">
          <dl className="flex flex-col gap-2 text-xs">
            {place !== undefined && <SceneDetailRow term="장소" value={place} />}
            {time !== undefined && <SceneDetailRow term="시간" value={time} />}
          </dl>
        </PopoverContent>
      </Popover>
    </div>
  );
}

function SceneDetailRow({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground">{term}</dt>
      {/* 띄어쓰기 없는 긴 글은 `break-keep` 만으로 끊을 자리가 없어 넘치므로 넘칠 때만 아무 데서나 끊는다(스탯 팝오버와 같다). */}
      <dd className="text-sm font-semibold break-keep wrap-anywhere">{value}</dd>
    </div>
  );
}
