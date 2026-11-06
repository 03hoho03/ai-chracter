import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";

import { AXIS_LABELS, CLAUDE_MODEL_AXES } from "../model/axes";
import type { AdminLlmCredentialListResponse, ClaudeModelAxis } from "../model/credential";
import { envRouteText, LIST_ROUTE_TEXT, SWITCH_FAILED_TEXT, SWITCH_PENDING_TEXT } from "../model/labels";
import { latestCheck, type EffectiveRoute, type FirstCandidates } from "../model/status";
import { POOL_HEADING_ID, STORE_NOTICE_ID } from "./elementIds";

/** 서버 스위치 조회의 지금 상태. 실패해도 이 절의 경로 줄만 바뀌고 목록과 동작은 그대로다. */
export type RuntimeSwitchState =
  | { status: "ready"; value: boolean }
  | { status: "pending" }
  | { status: "failed"; isRetrying: boolean; retry: () => void };

type PoolSectionProps = {
  list: AdminLlmCredentialListResponse;
  route: EffectiveRoute;
  firsts: FirstCandidates;
  runtimeSwitch: RuntimeSwitchState;
  onPoolChange: (enabled: boolean) => void;
};

/**
 * 목록 사용 절. 어드민 설정(켜짐·꺼짐)과 실효 경로를 따로 보인다 — 어드민에서 켜 두었어도 서버 스위치가 꺼져 있으면 실효는 env 키다.
 * 둘을 한 단어로 합치면 서버 스위치가 꺼진 동안 "사용 중"이 거짓이 된다.
 */
export function PoolSection({ list, route, firsts, runtimeSwitch, onPoolChange }: PoolSectionProps) {
  const isEnableBlocked = !list.poolEnabled && !list.storeConfigured;
  const isListRoute = route.kind === "list";

  return (
    <section aria-labelledby={POOL_HEADING_ID} className="flex flex-col gap-3 rounded-xl border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h2 id={POOL_HEADING_ID} className="text-lg font-semibold text-foreground">
            목록 사용
          </h2>
          <span className="text-sm text-muted-foreground">어드민 설정 {list.poolEnabled ? "켜짐" : "꺼짐"}</span>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-disabled={isEnableBlocked}
          aria-describedby={isEnableBlocked ? STORE_NOTICE_ID : undefined}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (!isEnableBlocked) onPoolChange(!list.poolEnabled);
          }}
        >
          {list.poolEnabled ? "목록 사용 끄기…" : "목록 사용 켜기…"}
        </Button>
      </div>

      <RouteLine route={route} runtimeSwitch={runtimeSwitch} />

      <div className="flex flex-col gap-1.5">
        <p className="text-xs text-muted-foreground">{isListRoute ? "모델마다 지금 보낼 항목" : "목록을 쓰면 모델마다 보낼 항목"}</p>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
          {CLAUDE_MODEL_AXES.map((axis) => (
            <AxisCandidate key={axis} axis={axis} list={list} firsts={firsts} isListRoute={isListRoute} />
          ))}
        </dl>
      </div>
    </section>
  );
}

type RouteLineProps = {
  route: EffectiveRoute;
  runtimeSwitch: RuntimeSwitchState;
};

function RouteLine({ route, runtimeSwitch }: RouteLineProps) {
  if (route.kind === "list") return <p className="break-keep text-sm text-foreground">{LIST_ROUTE_TEXT}</p>;
  if (route.kind === "env") {
    return (
      <p className="break-keep text-sm text-foreground">
        {envRouteText(route.cause)}
        {route.cause === "switch-off" && (
          <>
            {" "}
            <Link
              to="/feature-switches"
              className="admin-hit-area font-medium text-primary hover:underline focus-visible:underline"
            >
              기능 스위치 화면에서 보기
            </Link>
          </>
        )}
      </p>
    );
  }
  if (runtimeSwitch.status === "failed") {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="break-keep text-sm text-foreground">{SWITCH_FAILED_TEXT}</p>
        {/* 다시 시도 중에도 `disabled` 를 쓰지 않는다 — 누른 버튼이 포커스를 잃는다. 진행 중이면 눌러도 무시한다. */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-disabled={runtimeSwitch.isRetrying}
          className="aria-disabled:opacity-65"
          onClick={() => {
            if (!runtimeSwitch.isRetrying) runtimeSwitch.retry();
          }}
        >
          {runtimeSwitch.isRetrying ? "다시 시도하는 중…" : "다시 시도"}
        </Button>
      </div>
    );
  }
  return <p className="break-keep text-sm text-muted-foreground">{SWITCH_PENDING_TEXT}</p>;
}

type AxisCandidateProps = {
  axis: ClaudeModelAxis;
  list: AdminLlmCredentialListResponse;
  firsts: FirstCandidates;
  isListRoute: boolean;
};

/** 한 축의 첫 후보. 목록이 실효가 아닐 때는 "목록을 쓰면"의 값이라 흐린 글자로 둔다. 목록 사용 켜기는 최신 확인 행으로 판정하므로(서버가
 * 409 로 최종 판정한다) 그 축의 최신 확인이 옛 모델 id 면 덧붙인다. */
function AxisCandidate({ axis, list, firsts, isListRoute }: AxisCandidateProps) {
  const first = firsts[axis];
  const ink = isListRoute ? "text-foreground" : "text-muted-foreground";

  if (first === undefined) {
    return (
      <>
        <dt className="text-muted-foreground">{AXIS_LABELS[axis]}</dt>
        <dd className={cn("break-keep", isListRoute ? "text-destructive-text" : "text-muted-foreground")}>
          {isListRoute ? "없음 — 이 모델 호출은 실패·환불돼요" : "없음"}
        </dd>
      </>
    );
  }

  const position = list.credentials.findIndex((credential) => credential.id === first.id) + 1;
  const latestOnAxis = latestCheck(first.checks.filter((check) => check.modelAxis === axis));
  const isOldModelId = latestOnAxis !== undefined && !latestOnAxis.isCurrentModelId;

  return (
    <>
      <dt className="text-muted-foreground">{AXIS_LABELS[axis]}</dt>
      <dd className={cn("min-w-0 break-keep wrap-anywhere", ink)}>
        <span className="tabular-nums">{position}</span> · {first.label}
        {isOldModelId && <span className="text-muted-foreground"> · 최신 확인이 옛 모델 id</span>}
      </dd>
    </>
  );
}
