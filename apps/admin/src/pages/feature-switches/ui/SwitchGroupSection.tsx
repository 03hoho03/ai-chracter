import { cn } from "@ai-character-chat/ui/lib/utils";

import { SWITCH_GROUP_COPY, type SwitchGroup } from "../model/switchCopy";
import type { AdminAdjustableSwitch, AdminFeatureSwitchListResponse, AdminReadOnlySwitch } from "../model/types";
import { AdjustableSwitchRow } from "./AdjustableSwitchRow";
import { groupHeadingId } from "./elementIds";
import { ReadOnlySwitchRow } from "./ReadOnlySwitchRow";
import { SWITCH_ROW_GRID_CLASS } from "./SwitchRowParts";
import { FOCUS_TARGET_HEADING_CLASS, SECTION_CARD_CLASS } from "./styles";

type SwitchGroupSectionProps = {
  group: SwitchGroup;
  adjustable: readonly AdminAdjustableSwitch[];
  readOnly: readonly AdminReadOnlySwitch[];
  list: AdminFeatureSwitchListResponse;
  meId: string | undefined;
};

/** 묶음 하나의 섹션 카드. 버튼으로 바꾸는 행이 먼저, `.env` 로만 바꾸는 행이 뒤다. */
export function SwitchGroupSection({ group, adjustable, readOnly, list, meId }: SwitchGroupSectionProps) {
  const copy = SWITCH_GROUP_COPY[group];
  const headingId = groupHeadingId(group);

  return (
    <section aria-labelledby={headingId} className={cn(SECTION_CARD_CLASS, "@container")}>
      <div className="flex flex-col gap-1">
        {/* 모르는 덮어쓰기를 지워 그 섹션이 사라지면 포커스가 첫 묶음 제목으로 온다. */}
        <h2
          id={headingId}
          tabIndex={-1}
          className={cn("break-keep text-lg font-semibold text-foreground", FOCUS_TARGET_HEADING_CLASS)}
        >
          {copy.title}
        </h2>
        {copy.note !== null && <p className="max-w-prose text-sm break-keep text-muted-foreground">{copy.note}</p>}
      </div>

      {/* 넓을 때만 그리는 시각용 열 이름. 화면 읽기는 행마다 값 이름을 듣는다(`dt`). */}
      <div
        aria-hidden
        className={cn("hidden border-b border-border pb-2 text-xs text-muted-foreground", SWITCH_ROW_GRID_CLASS)}
      >
        <span>스위치</span>
        <span>.env</span>
        <span>덮어쓰기</span>
        <span>실효</span>
      </div>

      <ul className="flex flex-col">
        {adjustable.map((item) => (
          <AdjustableSwitchRow key={item.name} item={item} list={list} meId={meId} />
        ))}
        {readOnly.map((item) => (
          <ReadOnlySwitchRow key={item.name} item={item} />
        ))}
      </ul>
    </section>
  );
}
