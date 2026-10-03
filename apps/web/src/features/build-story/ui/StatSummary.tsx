import { STAT_ICON_OPTIONS } from "@/entities/chat-room";

import type { StatDefValues } from "../model/schema";
import { statSummaryParts } from "../model/statSummary";

type StatSummaryProps = {
  stat: Pick<StatDefValues, "icon" | "color" | "min" | "max" | "initial" | "unit" | "perTurnDelta">;
};

/** 접힌 머리 줄에서 스탯을 가를 최소 정보 — 고른 아이콘·색, 범위(단위 포함)와 초기값, 턴당 변화. 비었거나 숫자가 아닌
 * 칸은 빼고(빈 구분자를 남기지 않는다), 아이콘·색 표식은 장식이라 읽지 않는다. 빌더 스탯 카드와 작성 가이드의 카드 모양
 * 예시가 같이 그린다 — 따로 그리면 한쪽만 고쳐져 가이드 그림이 빌더와 다른 머리 줄을 보인다.
 *
 * 좁으면 범위는 남기고 뒤쪽부터 잘린다. 범위는 줄어들지 않는 조각이고(요약 폭보다 길 때만 말줄임), 초기값·턴당 변화는 한
 * 줄 글로 이어 붙여 말줄임이 끝(턴당 변화)부터 먹는다. 조각마다 따로 줄어들게 하면 폭이 비율로 나뉘어 범위까지 함께 잘린다. */
export function StatSummary({ stat }: StatSummaryProps) {
  const StatIcon = STAT_ICON_OPTIONS.find((option) => option.name === stat.icon)?.Icon;
  const { range, initial, perTurn } = statSummaryParts(stat);
  const rest = [initial, perTurn].filter((part) => part !== undefined);

  return (
    <span className="flex min-w-0 items-center">
      {StatIcon && <StatIcon aria-hidden className="mr-1 size-3.5 shrink-0" />}
      {stat.color && (
        <span aria-hidden className="mr-1.5 size-2.5 shrink-0 rounded-full" style={{ backgroundColor: stat.color }} />
      )}
      {range && <span className="max-w-full shrink-0 truncate">{range}</span>}
      {/* 앞 공백은 줄 첫머리라 접히므로 줄바꿈 없는 공백으로 둔다(범위가 없으면 구분자도 없다). */}
      {rest.length > 0 && (
        <span className="min-w-0 truncate">
          {range ? ` · ${rest.join(" · ")}` : rest.join(" · ")}
        </span>
      )}
    </span>
  );
}
