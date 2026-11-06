import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import type { MouseEvent } from "react";

import { formatDateTime } from "@/shared/lib/format/formatDateTime";

import { ADJUSTABLE_SWITCH_COPY, onOffText } from "../model/switchCopy";
import type { AdminAdjustableSwitch, AdminFeatureSwitchListResponse } from "../model/types";
import { ClearOverrideDialog } from "./ClearOverrideDialog";
import { HISTORY_HEADING_ID, toggleButtonId } from "./elementIds";
import { SwitchChangeDialog } from "./SwitchChangeDialog";
import {
  EffectiveValue,
  SWITCH_ROW_CLASS,
  SwitchNameBlock,
  SwitchValue,
  SwitchValueList,
} from "./SwitchRowParts";
import { OUTLINE_BADGE_CLASS, TEXT_LINK_CLASS } from "./styles";

type AdjustableSwitchRowProps = {
  item: AdminAdjustableSwitch;
  list: AdminFeatureSwitchListResponse;
  /** 지금 로그인한 운영자 id — 본인이 남긴 덮어쓰기는 이메일 대신 `나`. */
  meId: string | undefined;
};

/** 어드민에서 켜고 끄는 스위치 한 행. 조작은 토글이 아니라 확인 모달을 여는 버튼이다 — 토글은 누르는 순간 바뀐 것처럼 그려져
 * 모달을 취소하면 되돌아가는 거짓 상태가 생기고, 켜진 수만큼 `primary` 솔리드 채움이 한 화면에 생긴다. */
export function AdjustableSwitchRow({ item, list, meId }: AdjustableSwitchRowProps) {
  const copy = ADJUSTABLE_SWITCH_COPY[item.name];
  const { override, effectiveState } = item;

  return (
    <li className={SWITCH_ROW_CLASS}>
      <SwitchNameBlock name={item.name} label={copy.label} description={copy.description} />

      <SwitchValueList>
        <SwitchValue label="실효" placement="effective">
          <EffectiveValue value={item.effectiveValue} />
          {override !== null && <span className={cn(OUTLINE_BADGE_CLASS, "text-foreground")}>덮어씀</span>}
          {item.effectiveValue !== item.envValue && <span className="text-xs text-foreground">.env 와 다름</span>}
        </SwitchValue>
        <SwitchValue label=".env" placement="env">
          <span className="text-muted-foreground">{onOffText(item.envValue)}</span>
        </SwitchValue>
        <SwitchValue label="덮어쓰기" placement="override">
          {override === null ? (
            <span className="text-muted-foreground">없음</span>
          ) : (
            <span className="flex min-w-0 flex-col">
              <span className="text-foreground">{onOffText(override.value)}</span>
              <span className="text-xs break-all text-muted-foreground">
                {override.adminId === meId ? "나" : override.adminEmail} · {formatDateTime(override.updatedAt)}
              </span>
            </span>
          )}
        </SwitchValue>
        {effectiveState !== null && (
          <SwitchValue label="실제 상태" placement="state">
            <span className="min-w-0 break-keep wrap-anywhere text-foreground">
              {effectiveState.open ? "실제로 열림" : "실제로 닫힘"}
              {effectiveState.missingSettings.length > 0 &&
                ` — 비어 있는 설정: ${effectiveState.missingSettings.join(", ")}`}
            </span>
          </SwitchValue>
        )}
      </SwitchValueList>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* 켜기·끄기는 라벨만 바뀌는 버튼 하나다 — 저장 뒤 모달이 포커스를 돌려줄 같은 요소가 남아야 한다. */}
        <Button
          id={toggleButtonId(item.name)}
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void SwitchChangeDialog.call({ item, list })}
        >
          <span className="sr-only">{copy.label} </span>
          {item.effectiveValue ? "끄기…" : "켜기…"}
        </Button>
        {override !== null && (
          // 카드 위에서는 ghost 의 `hover:bg-muted` 가 카드와 같은 값이라 사라진다 — 한 칸 진한 면으로 덮는다.
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="hover:bg-secondary"
            onClick={() => void ClearOverrideDialog.call({ kind: "known", item, list })}
          >
            <span className="sr-only">{copy.label} </span>
            덮어쓰기 지우기…
          </Button>
        )}
        <Link
          to="/feature-switches"
          search={{ switch: item.name }}
          hash={HISTORY_HEADING_ID}
          resetScroll={false}
          hashScrollIntoView={false}
          className={cn(TEXT_LINK_CLASS, "text-sm")}
          onClick={focusHistoryHeading}
        >
          <span className="sr-only">{copy.label} </span>
          이력
        </Link>
      </div>
    </li>
  );
}

/** 이력 섹션은 같은 화면 아래에 늘 있어, 거르기를 바꾸는 이동과 함께 그 제목으로 포커스를 옮긴다(포커스가 그 자리로 스크롤한다).
 * 새 탭으로 여는 누름은 이 탭의 포커스를 옮기지 않는다. */
function focusHistoryHeading(event: MouseEvent<HTMLAnchorElement>) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  document.getElementById(HISTORY_HEADING_ID)?.focus();
}
