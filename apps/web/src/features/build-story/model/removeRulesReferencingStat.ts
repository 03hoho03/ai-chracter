import { countRules, type RuleListItemValues } from "./schema";

/**
 * 엔딩 탭에서 조건 줄이나 규칙 그룹의 삭제 버튼을 눌렀을 때의 처리. 지운 항목은 자기 `nextOp` 와 함께 사라지고 남은 항목의
 * `nextOp` 는 그대로 둔다 — `A 또는 X 그리고 B` 에서 X 를 지우면 `A 또는 B` 가 된다. 스탯 삭제로 조건이 함께 지워질 때도
 * 같은 결과가 나와야 작가가 같은 조건을 손으로 지웠을 때와 다른 엔딩 조건을 받지 않는다.
 */
export function removeRuleListItem(items: RuleListItemValues[], id: string): RuleListItemValues[] {
  return items.filter((item) => item.id !== id);
}

/**
 * 스탯을 지울 때 그 스탯을 가리키는 엔딩·상황 노트 조건도 함께 지운다. 남겨 두면 규칙 줄은 '지워진 스탯'으로 보이고, 서버는 없는
 * 스탯을 가리키는 규칙이 든 초안의 저장을 거절해 그 뒤 자동저장이 통째로 멈춘다.
 *
 * 그룹 안의 규칙도 같이 지운다. 규칙이 전부 지워져 비게 된 그룹은 그룹째 지운다 — 빈 그룹은 참으로 평가되므로 남겨 두면
 * `(지운 스탯 조건) or 다른 조건` 이 언제나 참이 된다. 작가가 처음부터 비워 둔 그룹은 이 삭제와 무관하므로 건드리지 않는다.
 * 지울 것이 없으면 받은 배열을 그대로 돌려줘 호출부가 쓰기를 건너뛸 수 있게 한다.
 */
export function removeRulesReferencingStat(items: RuleListItemValues[], statId: string): RuleListItemValues[] {
  let changed = false;
  const next: RuleListItemValues[] = [];
  for (const item of items) {
    if (item.kind === "rule") {
      if (item.statId === statId) changed = true;
      else next.push(item);
      continue;
    }
    const rules = item.rules.filter((rule) => rule.statId !== statId);
    if (rules.length === item.rules.length) {
      next.push(item);
      continue;
    }
    changed = true;
    if (rules.length > 0) next.push({ ...item, rules });
  }
  return changed ? next : items;
}

/** 스탯 삭제로 바뀌는 엔딩 하나·상황 노트 하나의 새 조건 목록. */
type StatRemovalEndingUpdate = { endingIndex: number; statRules: RuleListItemValues[] };
type StatRemovalNoteUpdate = { noteIndex: number; conditionRules: RuleListItemValues[] };
/** 지우는 스탯을 우선순위 스탯으로 고른 엔딩 — 그 칸을 '없음'으로 비운다. id 는 되돌리기가 같은 엔딩을 다시 찾을 때 쓴다. */
type StatRemovalPriorityUpdate = { endingIndex: number; endingId: string };

export type StatRemovalUpdates = {
  endings: StatRemovalEndingUpdate[];
  priorityStatEndings: StatRemovalPriorityUpdate[];
  situationNotes: StatRemovalNoteUpdate[];
};

/** 확인 문장에 들어갈 수. 조건은 그룹 안의 조건도 하나씩 센다. */
export type StatRemovalCounts = {
  endingRuleCount: number;
  noteRuleCount: number;
  /** 이 삭제로 조건이 하나도 남지 않게 되는 상황 노트 수 — 조건 없는 노트는 발행이 막히고 대화에도 실리지 않는다. */
  emptiedNoteCount: number;
  /** 이 스탯을 우선순위 스탯으로 고른 엔딩 수 — 그 엔딩들은 우선순위 스탯이 '없음'이 된다. */
  priorityEndingCount: number;
};

/** 그 스탯을 가리키는 조건 수. 그룹 안의 조건도 하나씩 센다. */
function countRulesReferencingStat(items: RuleListItemValues[], statId: string): number {
  let count = 0;
  for (const item of items) {
    if (item.kind === "rule") count += item.statId === statId ? 1 : 0;
    else count += item.rules.filter((rule) => rule.statId === statId).length;
  }
  return count;
}

/**
 * 스탯 하나를 지우기 전에 같은 시작설정의 엔딩·상황 노트에서 함께 지울 조건을 정한다. 함께 지워질 조건이 있으면 작가가 모른
 * 채 조건을 잃지 않도록 그 수를 들고 **한 번만** 먼저 묻고, 거절하면 `undefined` 를 돌려줘 호출부가 스탯도 조건도 건드리지
 * 않게 한다. 조건이 없으면 묻지 않고 빈 목록을 돌려준다. 바뀌는 엔딩·노트만 담는다.
 *
 * 그 스탯을 우선순위 스탯으로 고른 엔딩은 그 칸을 비운다. 남겨 두면 서버가 없는 스탯을 가리키는 초안의 저장을 거절해 자동저장이
 * 멈춘다. 우선순위 스탯만 걸린 삭제는 묻지 않는다 — 잃는 것은 고른 칸 하나라 스탯 삭제의 되돌리기가 함께 되살린다. 조건 때문에
 * 묻게 되면 그 수도 확인 문장에 함께 센다.
 */
export async function planStatRemoval(
  setup: {
    endings: { id: string; statRules: RuleListItemValues[]; priorityStatId: string | null }[];
    situationNotes: { conditionRules: RuleListItemValues[] }[];
  },
  statId: string,
  confirm: (counts: StatRemovalCounts) => Promise<boolean>,
): Promise<StatRemovalUpdates | undefined> {
  const updates: StatRemovalUpdates = { endings: [], priorityStatEndings: [], situationNotes: [] };
  setup.endings.forEach((ending, endingIndex) => {
    const statRules = removeRulesReferencingStat(ending.statRules, statId);
    if (statRules !== ending.statRules) updates.endings.push({ endingIndex, statRules });
    if (ending.priorityStatId === statId) updates.priorityStatEndings.push({ endingIndex, endingId: ending.id });
  });
  let emptiedNoteCount = 0;
  setup.situationNotes.forEach((note, noteIndex) => {
    const conditionRules = removeRulesReferencingStat(note.conditionRules, statId);
    if (conditionRules === note.conditionRules) return;
    updates.situationNotes.push({ noteIndex, conditionRules });
    if (countRules(conditionRules) === 0) emptiedNoteCount += 1;
  });
  const counts: StatRemovalCounts = {
    endingRuleCount: setup.endings.reduce((sum, ending) => sum + countRulesReferencingStat(ending.statRules, statId), 0),
    noteRuleCount: setup.situationNotes.reduce(
      (sum, note) => sum + countRulesReferencingStat(note.conditionRules, statId),
      0,
    ),
    emptiedNoteCount,
    priorityEndingCount: updates.priorityStatEndings.length,
  };
  if (counts.endingRuleCount + counts.noteRuleCount > 0 && !(await confirm(counts))) return undefined;
  return updates;
}
