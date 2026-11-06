import { cn } from "@ai-character-chat/ui/lib/utils";
import { ToggleLeft, ToggleRight } from "lucide-react";
import type { ReactNode } from "react";

import { switchHeadingId } from "./elementIds";
import { FOCUS_TARGET_HEADING_CLASS, OUTLINE_BADGE_CLASS } from "./styles";

/**
 * 스위치 행의 격자. 묶음 카드의 컨테이너 쿼리로 가른다 — 사이드바가 접히고 펴지면 같은 뷰포트에서도 본문 폭이 바뀌어서다.
 * 넓을 때 열은 `이름+설명 | .env | 덮어쓰기 | 실효 | 조치`이고, 좁을 때는 세로로 쌓는다. 행 목록을 `DataList` 로 그리지
 * 않는 것은 그 행 계약이 "행 전체를 덮는 대상 하나"라 버튼 둘을 둘 수 없어서고, `DenseTable` 이 아닌 것은 가로 스크롤이라 좁은
 * 화면에서 조치 버튼이 화면 밖으로 밀려서다.
 */
export const SWITCH_ROW_GRID_CLASS = "@4xl:grid @4xl:grid-cols-[minmax(0,1fr)_4.5rem_12rem_9rem_11rem] @4xl:gap-x-4";

/** 행 사이 구분은 윗선이고 첫 행만 뺀다. `relative` 는 넓을 때 숨기는 값 이름(`dt`)의 위치 기준이다. */
export const SWITCH_ROW_CLASS = cn(
  "relative flex flex-col gap-3 border-t border-border py-4 first:border-t-0 @4xl:items-start",
  SWITCH_ROW_GRID_CLASS,
);

type SwitchNameBlockProps = {
  name: string;
  label: string;
  description: string;
  isReadOnly?: boolean;
  children?: ReactNode;
};

/** 행의 첫 칸 — 사람 이름(제목), 코드 이름, 한 줄 설명. 제목은 「롤백 전에」 상자의 링크가 포커스를 옮기는 자리다. */
export function SwitchNameBlock({ name, label, description, isReadOnly = false, children }: SwitchNameBlockProps) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3
          id={switchHeadingId(name)}
          tabIndex={-1}
          className={cn("break-keep text-sm font-semibold text-foreground", FOCUS_TARGET_HEADING_CLASS)}
        >
          {label}
        </h3>
        {isReadOnly && <span className={cn(OUTLINE_BADGE_CLASS, "text-muted-foreground")}>읽기 전용</span>}
      </div>
      {/* 고정폭 서체는 채팅 코드 블록에만 쓴다 — 코드 이름도 본문 서체 그대로다. */}
      <code className="font-sans text-xs wrap-anywhere text-muted-foreground">{name}</code>
      <p className="text-sm break-keep text-muted-foreground">{description}</p>
      {children}
    </div>
  );
}

/** 값 목록(`dl`). 좁을 때는 이름·값 두 열이고, 넓을 때는 행 격자의 세 열(.env·덮어쓰기·실효)을 이어받는다. */
export function SwitchValueList({ children }: { children: ReactNode }) {
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm @4xl:col-span-3 @4xl:grid-cols-subgrid @4xl:gap-y-2">
      {children}
    </dl>
  );
}

/** 넓을 때 그 값이 앉는 열. 좁을 때는 적은 순서대로 쌓여 실효가 맨 위다(지금 도는 값이 가장 중요하다). */
const VALUE_PLACEMENT_CLASS = {
  effective: "@4xl:col-start-3 @4xl:row-start-1",
  env: "@4xl:col-start-1 @4xl:row-start-1",
  override: "@4xl:col-start-2 @4xl:row-start-1",
  // 실제 상태는 머리줄에 열이 없어 넓을 때 세 열을 가로지르는 둘째 줄에 이름과 함께 둔다.
  state: "@4xl:col-span-3 @4xl:col-start-1 @4xl:row-start-2 @4xl:flex @4xl:flex-wrap @4xl:gap-x-2",
} satisfies Record<string, string>;

type SwitchValueProps = {
  label: string;
  placement: keyof typeof VALUE_PLACEMENT_CLASS;
  children: ReactNode;
};

/** 값 한 쌍. 넓을 때는 묶음 머리줄이 열 이름을 보여 주므로 이름(`dt`)을 화면에서만 숨긴다 — 화면 읽기는 행마다 "실효 켜짐,
 * .env 꺼짐…"을 듣는다. 실제 상태는 열 이름이 없어 늘 보인다. */
export function SwitchValue({ label, placement, children }: SwitchValueProps) {
  const isStandalone = placement === "state";
  return (
    <div
      className={cn(
        "col-span-2 grid grid-cols-subgrid items-baseline",
        !isStandalone && "@4xl:col-span-1 @4xl:block",
        VALUE_PLACEMENT_CLASS[placement],
      )}
    >
      <dt className={cn("text-muted-foreground", !isStandalone && "@4xl:sr-only")}>{label}</dt>
      <dd className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">{children}</dd>
    </div>
  );
}

/** 켬·끔은 색이 아니라 글자와 아이콘 모양으로 가른다. */
export function EffectiveValue({ value, prefix = "" }: { value: boolean; prefix?: string }) {
  const Icon = value ? ToggleRight : ToggleLeft;
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
      <Icon aria-hidden className="size-4 shrink-0" />
      {prefix}
      {value ? "켜짐" : "꺼짐"}
    </span>
  );
}
