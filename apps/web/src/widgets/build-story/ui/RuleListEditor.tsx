import {
  closestCenter,
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { GripVertical, Trash2, TriangleAlert } from "lucide-react";
import { useRef } from "react";

import {
  CollapsibleItemCard,
  focusNeighborToggle,
  ItemDragHandle,
  ItemRemoveButton,
  itemOpenKey,
  useBuilderUiState,
} from "@/features/build-common";
import {
  COMPARISON_OPERATORS,
  hasRuleWithMissingStat,
  isMissingStat,
  LOGIC_OPERATORS,
  removeRuleListItem,
  type RuleListItemValues,
  type SingleRuleValues,
  type StatDefValues,
  type StoryCollapsibleList,
} from "@/features/build-story";

type LogicOp = (typeof LOGIC_OPERATORS)[number];

/** 그룹 내부 규칙을 잇는 접속사. 화면이 이 목록(LOGIC_OPERATORS)으로 항목을 그리므로 술어와 어긋날 수 없다. */
const GROUP_OPERATOR_LABEL: Record<LogicOp, string> = {
  and: "그리고",
  or: "또는",
};

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
          {GROUP_OPERATOR_LABEL[op]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

type SingleRuleRowProps = {
  rule: SingleRuleValues;
  stats: StatDefValues[];
  onChange: (rule: SingleRuleValues) => void;
  onRemove: () => void;
};

/** 단일 규칙 한 줄(스탯/연산자/기준값). 그룹 내부와 최상위 목록 양쪽에서 재사용된다.
 *
 * 스탯 칸이 가리키는 스탯이 이 시작설정에 없으면(지워진 스탯) 셀렉트는 고른 항목을 찾지 못해 빈칸을 그린다 — 그 대신
 * '지워진 스탯'을 오류 표시와 함께 그리고 줄 아래에 고치는 법을 적는다. 셀렉트를 열면 지금 스탯 목록이 그대로 나와 하나를
 * 고르면 고쳐지고, 줄 삭제 버튼으로 지울 수도 있다. 사실을 알리는 정적 문장이라 `role="alert"` 를 달지 않는다. */
function SingleRuleRow({
  rule,
  stats,
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
        <button
          type="button"
          aria-label="순서 변경"
          className="shrink-0 cursor-grab touch-none rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          {...attributes}
          {...listeners}
        >
          <GripVertical aria-hidden className="size-4" />
        </button>

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
              >
                <SelectValue placeholder="스탯">
                  {isStatMissing ? (
                    <>
                      <TriangleAlert aria-hidden className="size-3.5 text-destructive-text" />
                      <span className="truncate text-destructive-text">지워진 스탯</span>
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

      {/* 손잡이(16px)와 간격(8px)만큼 들여 스탯 칸 왼쪽 끝에 맞춘다 — 위 컨트롤 줄의 높이·정렬은 문장이 있어도 그대로다. */}
      {isStatMissing && (
        <p id={missingStatHintId} className="pl-6 text-xs break-keep text-destructive-text">
          이 조건의 스탯이 지워졌어요. 다른 스탯을 고르거나 조건을 지워 주세요.
        </p>
      )}
    </div>
  );
}

type RuleGroupRowProps = {
  group: Extract<RuleListItemValues, { kind: "group" }>;
  /** 같은 목록 안에서 몇 번째 그룹인지(1부터). 그룹은 이름이 없어 손잡이·삭제 버튼의 이름을 이 순번으로 가른다. */
  groupOrdinal: number;
  stats: StatDefValues[];
  emptyText: string;
  groupList: StoryCollapsibleList;
  onChange: (group: Extract<RuleListItemValues, { kind: "group" }>) => void;
  onRemove: () => void;
};

/** 규칙 그룹 컨테이너(내부는 단일 규칙만, 중첩 불가) — 내부 목록은 아래 RuleListEditor를 그대로
 * 재사용한다("그룹 안의 rules 배열도 동일한 재정렬 UI를 재사용"). 바깥 항목 카드 본문 안에서 한 번 더 접히는 카드라, 바깥
 * 카드와 구별되게 점선 테두리와 조금 좁은 안쪽 여백을 유지한다. 접혀 있어도 안에 지워진 스탯 조건이 있으면 머리 줄에 경고를
 * 띄운다(펼침은 하지 않는다). */
function RuleGroupRow({
  group,
  groupOrdinal,
  stats,
  emptyText,
  groupList,
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
      leading={<ItemDragHandle {...attributes} {...listeners} aria-label={`${groupOrdinal}번째 규칙 그룹 순서 변경`} />}
      trailing={<ItemRemoveButton label={`${groupOrdinal}번째 규칙 그룹 삭제`} onClick={onRemove} />}
    >
      <RuleListEditor
        items={group.rules}
        stats={stats}
        allowGroups={false}
        emptyText={emptyText}
        groupList={groupList}
        onChange={(next) =>
          onChange({ ...group, rules: next.filter((item): item is SingleRuleValues => item.kind === "rule") })
        }
      />
    </CollapsibleItemCard>
  );
}

type RuleListEditorProps = {
  items: RuleListItemValues[];
  stats: StatDefValues[];
  allowGroups: boolean;
  /** 규칙이 하나도 없을 때의 문장 — 규칙이 선택인 목록(엔딩)과 필수인 목록이 다르게 말한다. 그룹 안에도 같은 문장이 쓰인다. */
  emptyText: string;
  /** 그룹 열림 키의 목록 이름. 발행 실패 때 셸이 오류가 든 그룹을 여는 키와 같아야 해서, 편집기를 쓰는 목록마다 따로 둔다. */
  groupList: StoryCollapsibleList;
  onChange: (items: RuleListItemValues[]) => void;
};

/** 스탯 기반 규칙 목록 편집기. "단일 규칙 추가"/"규칙 그룹 추가"로 항목을 늘리고 dnd-kit로 재정렬한다.
 * `allowGroups=false`로 그룹 내부(단일 규칙만)에도 그대로 재사용된다. 폼 상태를 직접 잡지 않는 제어 컴포넌트라 호출부가
 * 목록을 읽어 넘기고 바뀐 목록을 통째로 써 넣는다. */
export function RuleListEditor({
  items,
  stats,
  allowGroups,
  emptyText,
  groupList,
  onChange,
}: RuleListEditorProps) {
  const sensors = useSensors(useSensor(PointerSensor));
  const uiState = useBuilderUiState();
  const addRuleButtonRef = useRef<HTMLButtonElement>(null);
  const addGroupButtonRef = useRef<HTMLButtonElement>(null);

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

  // 새 그룹은 펼친 채 만든다(안에 규칙을 바로 넣을 수 있게).
  function addGroup() {
    const id = crypto.randomUUID();
    uiState.open([itemOpenKey(groupList, id)]);
    onChange([...items, { kind: "group", id, rules: [], nextOp: null }]);
  }

  function handleDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === over.id);
    if (oldIndex !== -1 && newIndex !== -1) onChange(arrayMove(items, oldIndex, newIndex));
  }

  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
            <div className="flex flex-col gap-2">
              {items.map((item, index) => (
                <div key={item.id} className="flex flex-col gap-2">
                  {item.kind === "group" ? (
                    <RuleGroupRow
                      group={item}
                      groupOrdinal={items.slice(0, index + 1).filter((other) => other.kind === "group").length}
                      stats={stats}
                      emptyText={emptyText}
                      groupList={groupList}
                      onChange={(next) => updateItem(item.id, next)}
                      onRemove={() => removeItem(item.id)}
                    />
                  ) : (
                    <SingleRuleRow
                      rule={item}
                      stats={stats}
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

      <div className="flex gap-2">
        <Button
          ref={addRuleButtonRef}
          type="button"
          variant="secondary"
          size="sm"
          disabled={stats.length === 0}
          onClick={() =>
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
            ])
          }
        >
          단일 규칙 추가
        </Button>
        {allowGroups && (
          <Button ref={addGroupButtonRef} type="button" variant="secondary" size="sm" onClick={addGroup}>
            규칙 그룹 추가
          </Button>
        )}
      </div>
    </div>
  );
}
