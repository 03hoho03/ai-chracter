import { closestCenter, DndContext } from "@dnd-kit/core";
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Trash2, TriangleAlert } from "lucide-react";
import { useId, useRef } from "react";

import {
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemDragHandle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderUiState,
  useSortableList,
  type SortableHandleProps,
} from "@/features/build-common";
import {
  COMPARISON_OPERATORS,
  countRules,
  hasRuleWithMissingStat,
  isMissingStat,
  LOGIC_OPERATOR_LABELS,
  LOGIC_OPERATORS,
  removeRuleListItem,
  type RuleListItemValues,
  type SingleRuleValues,
  type StatDefValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

type LogicOp = (typeof LOGIC_OPERATORS)[number];

type RuleListEditorProps = {
  items: RuleListItemValues[];
  stats: StatDefValues[];
  allowGroups: boolean;
  /** 규칙이 하나도 없을 때의 문장 — 규칙이 선택인 목록(엔딩)과 필수인 목록이 다르게 말한다. 그룹 안에도 같은 문장이 쓰인다. */
  emptyText: string;
  /** 그룹 열림 키의 목록 이름. 발행 실패 때 셸이 오류가 든 그룹을 여는 키와 같아야 해서, 편집기를 쓰는 목록마다 따로 둔다. */
  groupList: StoryCollapsibleList;
  /** 이 목록의 폼 경로. 주면 조건 줄의 스탯 칸과 '단일 규칙 추가'에 경로 표식이 붙어, 발행 실패 때 셸이 그 칸을 찾아 포커스한다
   * (조건 줄은 폼에 등록된 입력이 아니라 경로로는 포커스할 수 없다). */
  fieldPath?: string;
  /** 조건 수 상한(그룹 안 조건까지 센다). 상한이 없는 목록(엔딩)은 넘기지 않는다. */
  ruleLimit?: RuleLimit;
  /** 그룹 안 편집기에만 그룹이 넘긴다 — 바깥 목록 전체의 조건 수. */
  rootRuleCount?: number;
  /** 스탯이 없어 조건을 만들 수 없을 때 추가 버튼 아래에 보일 사유. 없으면(엔딩) 버튼만 잠근다. */
  noStatsReason?: string;
  onChange: (items: RuleListItemValues[]) => void;
};

type RuleLimit = {
  max: number;
  /** 상한에 닿았을 때 추가 버튼 아래에 보일 사유. */
  reason: string;
};

type SingleRuleRowProps = {
  rule: SingleRuleValues;
  /** 같은 목록 안에서 몇 번째 단일 규칙인지(1부터) — 손잡이 이름을 가른다. */
  ruleOrdinal: number;
  /** 손잡이의 id·화살표 키 재정렬(`useSortableList`). */
  handleProps: SortableHandleProps;
  stats: StatDefValues[];
  /** 이 조건의 폼 경로(편집기에 `fieldPath` 를 준 목록만). 발행 실패 때 셸이 스탯 칸을 찾아 포커스하는 표식이 된다. */
  fieldPath: string | undefined;
  onChange: (rule: SingleRuleValues) => void;
  onRemove: () => void;
};

type RuleGroupRowProps = {
  group: Extract<RuleListItemValues, { kind: "group" }>;
  /** 같은 목록 안에서 몇 번째 그룹인지(1부터). 그룹은 이름이 없어 손잡이·삭제 버튼의 이름을 이 순번으로 가른다. */
  groupOrdinal: number;
  /** 손잡이의 id·화살표 키 재정렬(`useSortableList`). */
  handleProps: SortableHandleProps;
  stats: StatDefValues[];
  emptyText: string;
  groupList: StoryCollapsibleList;
  /** 이 그룹의 폼 경로(편집기에 `fieldPath` 를 준 목록만). */
  fieldPath: string | undefined;
  ruleLimit: RuleLimit | undefined;
  /** 바깥 목록 전체의 조건 수 — 상한은 그룹 하나가 아니라 노트 전체로 센다. */
  rootRuleCount: number;
  noStatsReason: string | undefined;
  onChange: (group: Extract<RuleListItemValues, { kind: "group" }>) => void;
  onRemove: () => void;
};

/** 스탯 기반 규칙 목록 편집기. "단일 규칙 추가"/"규칙 그룹 추가"로 항목을 늘리고 손잡이를 끌거나 화살표 키로 재정렬한다.
 * `allowGroups=false`로 그룹 내부(단일 규칙만)에도 그대로 재사용된다. 폼 상태를 직접 잡지 않는 제어 컴포넌트라 호출부가
 * 목록을 읽어 넘기고 바뀐 목록을 통째로 써 넣는다.
 *
 * 상한(`ruleLimit`)에 닿으면 추가 버튼을 지우지 않고 `aria-disabled` 로 잠근 채 사유를 잇는다 — 지우면 왜 더 못 만드는지가
 * 사라지고, `disabled` 는 누른 버튼의 포커스를 body 로 떨어뜨린다. 자동저장은 폼 검증을 거치지 않아 상한을 넘은 목록이 폼에
 * 들어가면 서버가 초안 저장을 통째로 거절하므로, 실제 차단은 클릭 핸들러가 한다. 빈 그룹은 조건 수를 늘리지 않지만 그 안에
 * 넣을 수 없으니 함께 잠근다. */
export function RuleListEditor({
  items,
  stats,
  allowGroups,
  emptyText,
  groupList,
  fieldPath,
  ruleLimit,
  rootRuleCount,
  noStatsReason,
  onChange,
}: RuleListEditorProps) {
  const sortable = useSortableList({
    ids: items.map((item) => item.id),
    move: (from, to) => onChange(arrayMove(items, from, to)),
    itemObject: "규칙을",
    orderMeaning: "위에서부터 차례로 이어 판정해요.",
  });
  const uiState = useBuilderUiState();
  const addRuleButtonRef = useRef<HTMLButtonElement>(null);
  const addGroupButtonRef = useRef<HTMLButtonElement>(null);
  const reasonId = useId();
  const totalRuleCount = rootRuleCount ?? countRules(items);
  const isFull = ruleLimit !== undefined && totalRuleCount >= ruleLimit.max;
  const hasNoStats = stats.length === 0;
  // 상한이 스탯 없음보다 먼저다 — 상한이면 스탯을 만들어도 추가할 수 없다.
  let reason: string | undefined;
  if (isFull) reason = ruleLimit.reason;
  else if (hasNoStats) reason = noStatsReason;

  function updateItem(id: string, next: RuleListItemValues) {
    onChange(items.map((item) => (item.id === id ? next : item)));
  }

  // 지우기 전에 포커스를 이웃 그룹의 머리 줄로 옮긴다. 이웃이 단일 규칙이면 머리 줄이 없어(그 키의 토글이 없다) 추가
  // 버튼으로 간다 — 그룹을 받는 목록이면 언제나 누를 수 있는 '규칙 그룹 추가'로.
  function removeItem(id: string) {
    const index = items.findIndex((item) => item.id === id);
    const keys = items.map((item) => itemOpenKey(groupList, item.id));
    focusNeighborToggle(keys, index, addGroupButtonRef.current ?? addRuleButtonRef.current);
    onChange(removeRuleListItem(items, id));
  }

  function addRule() {
    if (isFull || hasNoStats) return;
    onChange([
      ...items,
      {
        kind: "rule",
        id: crypto.randomUUID(),
        statId: stats[0]?.id ?? "",
        operator: ">=",
        value: 0,
        nextOp: null,
      },
    ]);
  }

  // 새 그룹은 펼친 채 만든다(안에 규칙을 바로 넣을 수 있게).
  function addGroup() {
    if (isFull) return;
    const id = crypto.randomUUID();
    uiState.open([itemOpenKey(groupList, id)]);
    onChange([...items, { kind: "group", id, rules: [], nextOp: null }]);
  }

  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <DndContext
          sensors={sortable.sensors}
          collisionDetection={closestCenter}
          onDragEnd={sortable.handleDragEnd}
          accessibility={sortable.accessibility}
        >
          <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-2">
              {items.map((item, index) => (
                <div key={item.id} className="flex flex-col gap-2">
                  {item.kind === "group" ? (
                    <RuleGroupRow
                      group={item}
                      groupOrdinal={items.slice(0, index + 1).filter((other) => other.kind === "group").length}
                      handleProps={sortable.handleProps(index)}
                      stats={stats}
                      emptyText={emptyText}
                      groupList={groupList}
                      fieldPath={fieldPath === undefined ? undefined : `${fieldPath}.${index}`}
                      ruleLimit={ruleLimit}
                      rootRuleCount={totalRuleCount}
                      noStatsReason={noStatsReason}
                      onChange={(next) => updateItem(item.id, next)}
                      onRemove={() => removeItem(item.id)}
                    />
                  ) : (
                    <SingleRuleRow
                      rule={item}
                      ruleOrdinal={items.slice(0, index + 1).filter((other) => other.kind === "rule").length}
                      handleProps={sortable.handleProps(index)}
                      stats={stats}
                      fieldPath={fieldPath === undefined ? undefined : `${fieldPath}.${index}`}
                      onChange={(next) => updateItem(item.id, next)}
                      onRemove={() => removeItem(item.id)}
                    />
                  )}
                  {index < items.length - 1 && (
                    <LogicOpToggle
                      value={item.nextOp ?? "and"}
                      onChange={(op) => updateItem(item.id, { ...item, nextOp: op })}
                    />
                  )}
                </div>
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <div className="flex flex-col gap-1.5">
        <div className="flex gap-2">
          <Button
            ref={addRuleButtonRef}
            type="button"
            variant="secondary"
            size="sm"
            className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
            disabled={hasNoStats}
            aria-disabled={isFull || undefined}
            aria-describedby={reason === undefined ? undefined : reasonId}
            data-field-path={fieldPath}
            onClick={addRule}
          >
            단일 규칙 추가
          </Button>
          {allowGroups && (
            <Button
              ref={addGroupButtonRef}
              type="button"
              variant="secondary"
              size="sm"
              className="aria-disabled:pointer-events-none aria-disabled:opacity-65"
              aria-disabled={isFull || undefined}
              aria-describedby={isFull ? reasonId : undefined}
              onClick={addGroup}
            >
              규칙 그룹 추가
            </Button>
          )}
        </div>
        {reason !== undefined && (
          <p id={reasonId} className="text-xs break-keep text-muted-foreground">
            {reason}
          </p>
        )}
      </div>

      <p className="sr-only" aria-live="polite">
        {sortable.announcement}
      </p>
    </div>
  );
}

/** Radix 토글·셀렉트는 재클릭 시 빈 문자열을 흘려보내고 item value도 `string`이라 좁힘이 필요하다.
 * `as` 대신 술어를 쓴다 — 둘 다 화면이 실제로 그리는 목록을 근거로 삼는다. */
function isGroupOperator(value: string): value is LogicOp {
  return LOGIC_OPERATORS.some((op) => op === value);
}

function isComparisonOperator(value: string): value is SingleRuleValues["operator"] {
  return COMPARISON_OPERATORS.some((op) => op === value);
}

/** 목록 위에서 인접한 두 항목 사이의 and/or 관계. 마지막 항목의 nextOp는 평가에서 무시되므로
 * (entities/chat-room/model/endingRules.ts) 마지막 항목 뒤에는 렌더링하지 않는다. */
function LogicOpToggle({ value, onChange }: { value: LogicOp; onChange: (op: LogicOp) => void }) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      className="ml-7 w-fit"
      value={value}
      onValueChange={(next) => isGroupOperator(next) && onChange(next)}
      aria-label="다음 규칙과의 관계"
    >
      {LOGIC_OPERATORS.map((op) => (
        <ToggleGroupItem key={op} value={op}>
          {LOGIC_OPERATOR_LABELS[op]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** 단일 규칙 한 줄(스탯/연산자/기준값). 그룹 내부와 최상위 목록 양쪽에서 재사용된다.
 *
 * 스탯 칸이 가리키는 스탯이 이 시작설정에 없으면(지워진 스탯) 셀렉트는 고른 항목을 찾지 못해 빈칸을 그린다 — 그 대신
 * 경고 아이콘과 '지워짐'을 오류 표시와 함께 그리고 줄 아래에 고치는 법을 적는다. 넓은 화면에서 스탯 칸은 128px 이라 패딩·
 * 셰브론·아이콘을 빼면 글자 칸이 54px 남짓이고, '지워진 스탯'(약 73px)은 '지워진…'으로 잘려 뜻이 사라졌다 — 그래서 칸에는
 * 세 글자만 보이고, 온전한 이름은 접근 이름(`스탯 선택: 지워진 스탯`)과 줄 아래 문장이 맡는다. 셀렉트를 열면 지금 스탯 목록이
 * 그대로 나와 하나를 고르면 고쳐지고, 줄 삭제 버튼으로 지울 수도 있다. 사실을 알리는 정적 문장이라 `role="alert"` 를 달지 않는다. */
function SingleRuleRow({
  rule,
  ruleOrdinal,
  handleProps,
  stats,
  fieldPath,
  onChange,
  onRemove,
}: SingleRuleRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: rule.id });
  const isStatMissing = isMissingStat(rule.statId, stats);
  const missingStatHintId = `rule-${rule.id}-missing-stat`;

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="flex flex-col gap-1.5 rounded-lg border border-border bg-background p-3"
    >
      <div className="flex items-center gap-2">
        <ItemDragHandle
          {...attributes}
          {...listeners}
          {...handleProps}
          aria-label={`${ruleOrdinal}번째 규칙 순서 변경`}
        />

        {/* 세 컨트롤의 고정 폭 합(128+80+96px + 간격)이 좁은 행보다 넓어서, 한 줄에 두면 줄어들 수 있는
            유일한 칸인 기준값 입력이 26px로 찌그러지고 삭제 버튼이 행 밖으로 밀려났다(390px 실측).
            같은 행이 최상위 목록과 규칙 그룹 안 양쪽에 들어가 폭이 뷰포트만으로 정해지지 않으므로
            브레이크포인트 대신 컨테이너 폭으로 가른다 — 좁으면 스탯을 한 줄로 올리고 연산자·기준값을
            다음 줄에 둔다. */}
        <div className="@container min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={rule.statId} onValueChange={(value) => onChange({ ...rule, statId: value })}>
              <SelectTrigger
                className="w-full @xs:w-32"
                aria-label={isStatMissing ? "스탯 선택: 지워진 스탯" : "스탯 선택"}
                aria-invalid={isStatMissing || undefined}
                aria-describedby={isStatMissing ? missingStatHintId : undefined}
                data-field-path={fieldPath === undefined ? undefined : `${fieldPath}.statId`}
              >
                <SelectValue placeholder="스탯">
                  {isStatMissing ? (
                    <>
                      <TriangleAlert aria-hidden className="size-3.5 text-destructive-text" />
                      <span className="truncate text-destructive-text">지워짐</span>
                    </>
                  ) : undefined}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {stats.map((stat) => (
                  <SelectItem key={stat.id} value={stat.id}>
                    {stat.name || "이름없음"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={rule.operator}
              onValueChange={(value) => isComparisonOperator(value) && onChange({ ...rule, operator: value })}
            >
              <SelectTrigger className="w-20 shrink-0" aria-label="연산자 선택">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMPARISON_OPERATORS.map((op) => (
                  <SelectItem key={op} value={op}>
                    {op}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Input
              id={`rule-${rule.id}-value`}
              type="number"
              className="w-24 shrink-0"
              aria-label="기준값"
              value={rule.value}
              onChange={(event) => onChange({ ...rule, value: Number(event.target.value) })}
            />
          </div>
        </div>

        <Button type="button" variant="ghost" size="icon" aria-label="규칙 삭제" className="shrink-0" onClick={onRemove}>
          <Trash2 aria-hidden className="size-4" />
        </Button>
      </div>

      {/* 손잡이가 줄 안쪽 여백으로 당겨진 만큼(-8px)을 빼고 손잡이(36px, 손가락 포인터 40px)와 간격(8px)만큼 들여 스탯 칸 왼쪽
          끝에 맞춘다 — 위 컨트롤 줄의 높이·정렬은 문장이 있어도 그대로다. */}
      {isStatMissing && (
        <p id={missingStatHintId} className="pl-9 text-xs break-keep text-destructive-text pointer-coarse:pl-10">
          이 조건의 스탯이 지워졌어요. 다른 스탯을 고르거나 조건을 지워 주세요.
        </p>
      )}
    </div>
  );
}

/** 규칙 그룹 컨테이너(내부는 단일 규칙만, 중첩 불가) — 내부 목록은 위 RuleListEditor를 그대로
 * 재사용한다("그룹 안의 rules 배열도 동일한 재정렬 UI를 재사용"). 바깥 항목 카드 본문 안에서 한 번 더 접히는 카드라, 바깥
 * 카드와 구별되게 점선 테두리와 조금 좁은 안쪽 여백을 유지한다. 접혀 있어도 안에 지워진 스탯 조건이 있으면 머리 줄에 경고를
 * 띄운다(펼침은 하지 않는다). */
function RuleGroupRow({
  group,
  groupOrdinal,
  stats,
  emptyText,
  groupList,
  fieldPath,
  ruleLimit,
  rootRuleCount,
  noStatsReason,
  handleProps,
  onChange,
  onRemove,
}: RuleGroupRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: group.id });

  return (
    <CollapsibleItemCard
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className="rounded-lg border-dashed px-3"
      openKey={itemOpenKey(groupList, group.id)}
      title="규칙 그룹"
      placeholderTitle="규칙 그룹"
      srTitlePrefix={`${groupOrdinal}번째 `}
      summary={`조건 ${group.rules.length}개`}
      hasError={hasRuleWithMissingStat(group.rules, stats)}
      leading={
        <ItemDragHandle
          {...attributes}
          {...listeners}
          {...handleProps}
          aria-label={`${groupOrdinal}번째 규칙 그룹 순서 변경`}
        />
      }
      trailing={<ItemRemoveButton label={`${groupOrdinal}번째 규칙 그룹 삭제`} onClick={onRemove} />}
    >
      <RuleListEditor
        items={group.rules}
        stats={stats}
        allowGroups={false}
        emptyText={emptyText}
        groupList={groupList}
        fieldPath={fieldPath === undefined ? undefined : `${fieldPath}.rules`}
        ruleLimit={ruleLimit}
        rootRuleCount={rootRuleCount}
        noStatsReason={noStatsReason}
        onChange={(next) =>
          onChange({ ...group, rules: next.filter((item): item is SingleRuleValues => item.kind === "rule") })
        }
      />
    </CollapsibleItemCard>
  );
}
