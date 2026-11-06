import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { cn } from "@ai-character-chat/ui/lib/utils";

import { formatDateTimeParts } from "@/shared/lib/format/formatDateTime";
import { DenseTable } from "@/shared/ui/DenseTable";
import { FilterBar, selectFilter } from "@/shared/ui/FilterBar";
import { Pagination } from "@/shared/ui/Pagination";
import { QueryState } from "@/shared/ui/QueryState";

import { useFeatureSwitchChangesQuery } from "../api/useFeatureSwitchChangesQuery";
import { ADJUSTABLE_SWITCH_COPY, FEATURE_SWITCH_NAMES, onOffText, switchLabelOf } from "../model/switchCopy";
import { overrideText } from "../model/switchEffects";
import type { AdminFeatureSwitchChangeItem, FeatureSwitchName } from "../model/types";
import { HISTORY_HEADING_ID } from "./elementIds";
import { FOCUS_TARGET_HEADING_CLASS, SECTION_CARD_CLASS } from "./styles";
import { ValueChange } from "./ValueChange";

/** 거르기 옵션은 버튼으로 바꾸는 스위치뿐이다 — `.env` 로만 바꾸는 스위치에는 이력이 생길 수 없다. */
const SWITCH_FILTER_OPTIONS = FEATURE_SWITCH_NAMES.map((name) => ({ value: name, label: ADJUSTABLE_SWITCH_COPY[name].label }));

type SwitchHistorySectionProps = {
  switchName: FeatureSwitchName | undefined;
  page: number;
  meId: string | undefined;
  onSwitchChange: (switchName: FeatureSwitchName | undefined) => void;
  onPageChange: (page: number) => void;
};

/** 같은 화면 맨 아래의 변경 이력 — 바꾸기 직전에 이 스위치를 누가 왜 바꿨는지 같은 화면에서 본다. 목록과 따로 불러오고 따로
 * 실패한다. */
export function SwitchHistorySection({ switchName, page, meId, onSwitchChange, onPageChange }: SwitchHistorySectionProps) {
  const changesQuery = useFeatureSwitchChangesQuery({ page, switchName });

  return (
    <section aria-labelledby={HISTORY_HEADING_ID} className={SECTION_CARD_CLASS}>
      <h2
        id={HISTORY_HEADING_ID}
        tabIndex={-1}
        className={cn("text-lg font-semibold text-foreground", FOCUS_TARGET_HEADING_CLASS)}
      >
        변경 이력
      </h2>
      <FilterBar
        fields={[
          selectFilter({
            id: "switch",
            label: "스위치",
            options: SWITCH_FILTER_OPTIONS,
            value: switchName,
            defaultLabel: "전체",
            onChange: onSwitchChange,
          }),
        ]}
        onReset={() => onSwitchChange(undefined)}
      />
      <QueryState
        query={changesQuery}
        surface="card"
        errorMessage="변경 이력을 불러오지 못했어요."
        isEmpty={(data) => data.items.length === 0}
        getPage={(data) => data}
        empty={{
          title:
            switchName === undefined
              ? "아직 바꾼 스위치가 없어요. 스위치를 처음 바꾸면 누가·언제·왜 바꿨는지 여기에 쌓여요."
              : "이 스위치는 아직 바꾼 적이 없어요.",
        }}
      >
        {(data) => (
          <>
            <ChangeTable items={data.items} meId={meId} />
            <Pagination
              page={data.page}
              totalPages={data.totalPages}
              totalCount={data.totalCount}
              onPageChange={onPageChange}
            />
          </>
        )}
      </QueryState>
    </section>
  );
}

/** 감사 기록이라 사유는 자르지 않고 줄바꿈까지 그대로 보인다. 표만 가로로 스크롤하고 시각 열은 왼쪽에 고정한다. 표 래퍼가
 * 위치 기준이라 화살표 대신 읽히는 숨김 글자가 그 상자 안에 머문다. */
function ChangeTable({ items, meId }: { items: readonly AdminFeatureSwitchChangeItem[]; meId: string | undefined }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <DenseTable surface="card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>시각</TableHead>
              <TableHead>스위치</TableHead>
              <TableHead>전 → 후</TableHead>
              <TableHead>그때 .env</TableHead>
              <TableHead>사유</TableHead>
              <TableHead>운영자</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <ChangeRow key={item.id} item={item} meId={meId} />
            ))}
          </TableBody>
        </Table>
      </DenseTable>
    </div>
  );
}

function ChangeRow({ item, meId }: { item: AdminFeatureSwitchChangeItem; meId: string | undefined }) {
  const { date, time } = formatDateTimeParts(item.createdAt);
  const label = switchLabelOf(item.name);

  return (
    <TableRow className="align-top">
      <TableCell>
        <span className="whitespace-nowrap">{date}</span> <span className="whitespace-nowrap">{time}</span>
      </TableCell>
      <TableCell>
        {/* 지금 판이 모르는 옛 이름은 코드 이름만 보인다. */}
        <span className="block text-foreground">{label ?? item.name}</span>
        {label !== null && <code className="block font-sans text-xs text-muted-foreground">{item.name}</code>}
      </TableCell>
      <TableCell>
        <span className="block text-foreground">
          실효 <ValueChange before={effectiveText(item.beforeOverride, item.envValue)} after={effectiveText(item.afterOverride, item.envValue)} />
        </span>
        <span className="block text-xs text-muted-foreground">
          덮어쓰기 <ValueChange before={overrideText(item.beforeOverride)} after={overrideText(item.afterOverride)} />
        </span>
      </TableCell>
      {/* 그 순간의 `.env` 값이다 — 지금 `.env` 가 바뀌었어도 그대로다. 없으면 기록한 판이 그 이름을 몰랐다. */}
      <TableCell>{item.envValue === null ? "—" : onOffText(item.envValue)}</TableCell>
      <TableCell>
        <p className="max-w-80 min-w-48 whitespace-pre-wrap wrap-break-word">{item.reason}</p>
      </TableCell>
      <TableCell>{item.adminId === meId ? "나" : item.adminEmail}</TableCell>
    </TableRow>
  );
}

/** 덮어쓰기가 있으면 그 값, 없으면 그때의 `.env` 값. 둘 다 없으면(지금 판이 모르는 이름을 지운 행) 알 수 없다. */
function effectiveText(override: boolean | null, envValue: boolean | null) {
  const value = override ?? envValue;
  return value === null ? "—" : onOffText(value);
}
