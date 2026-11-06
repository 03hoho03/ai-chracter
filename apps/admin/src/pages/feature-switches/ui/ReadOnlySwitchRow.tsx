import { onOffText, READ_ONLY_REASON_TEXT, READ_ONLY_SWITCH_COPY } from "../model/switchCopy";
import type { AdminReadOnlySwitch } from "../model/types";
import { EffectiveValue, SWITCH_ROW_CLASS, SwitchNameBlock, SwitchValue, SwitchValueList } from "./SwitchRowParts";

/** `.env` 로만 바꾸는 스위치 한 행. 덮어쓰기가 없어 실효 값이 곧 `.env` 값이고, 버튼 대신 바꿀 수 없는 이유를 적는다. */
export function ReadOnlySwitchRow({ item }: { item: AdminReadOnlySwitch }) {
  const copy = READ_ONLY_SWITCH_COPY[item.name];

  return (
    <li className={SWITCH_ROW_CLASS}>
      <SwitchNameBlock name={item.name} label={copy.label} description={copy.description} isReadOnly>
        <p className="text-xs break-keep text-muted-foreground">
          {READ_ONLY_REASON_TEXT[item.reason]} .env 를 고치고 교체 배포로 바꿔요.
        </p>
      </SwitchNameBlock>

      <SwitchValueList>
        <SwitchValue label="실효" placement="effective">
          <EffectiveValue value={item.value} prefix="지금 " />
        </SwitchValue>
        <SwitchValue label=".env" placement="env">
          <span className="text-muted-foreground">{onOffText(item.value)}</span>
        </SwitchValue>
        <SwitchValue label="덮어쓰기" placement="override">
          <span aria-hidden className="text-muted-foreground">
            —
          </span>
          <span className="sr-only">덮어쓸 수 없음</span>
        </SwitchValue>
      </SwitchValueList>
    </li>
  );
}
