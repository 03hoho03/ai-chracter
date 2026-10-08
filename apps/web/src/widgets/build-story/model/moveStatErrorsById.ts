import type { StatDefValues, StatRuleValues } from "@/features/build-story";

/** 오류가 붙을 수 있는 스탯 칸. `Record` 로 적어 스탯에 칸이 늘면 여기도 늘리라고 타입이 알린다. 규칙 목록은 칸 하나가 아니라
 * 아래에서 따로 옮긴다. */
type StatErrorField = Exclude<keyof StatDefValues, "id" | "rules">;

const STAT_ERROR_FIELDS: Record<StatErrorField, true> = {
  name: true,
  icon: true,
  color: true,
  min: true,
  max: true,
  initial: true,
  unit: true,
  description: true,
  perTurnDelta: true,
};

/** 규칙 한 줄에서 오류가 붙을 수 있는 칸. */
type StatRuleErrorField = Exclude<keyof StatRuleValues, "id">;

const STAT_RULE_ERROR_FIELDS: Record<StatRuleErrorField, true> = {
  condition: true,
  delta: true,
};

function isStatErrorField(key: string): key is StatErrorField {
  return Object.hasOwn(STAT_ERROR_FIELDS, key);
}

function isStatRuleErrorField(key: string): key is StatRuleErrorField {
  return Object.hasOwn(STAT_RULE_ERROR_FIELDS, key);
}

type StatFieldError = { type: string; message?: string };

function isStatFieldError(value: unknown): value is StatFieldError {
  return typeof value === "object" && value !== null && "type" in value && typeof value.type === "string";
}

/** 스탯 안에서 오류가 붙는 자리 — 칸 하나, 규칙 목록 자체(개수 상한·판정 스탯의 규칙 없음), 규칙 한 줄의 칸. */
export type StatErrorPath = StatErrorField | "rules" | `rules.${number}.${StatRuleErrorField}`;

export type MovedStatError = { statIndex: number; field: StatErrorPath; error: StatFieldError };

function pick(error: StatFieldError): StatFieldError {
  return { type: error.type, message: error.message };
}

/** 규칙 목록 자리의 오류. 목록 자체의 위반은 `.type`/`.message` 나 `.root` 로, 줄마다의 위반은 인덱스 키 아래로 온다. */
type RuleErrorEntry = { field: "rules" | `rules.${number}.${StatRuleErrorField}`; error: StatFieldError };

function ruleErrorsOf(rulesError: unknown): RuleErrorEntry[] {
  if (typeof rulesError !== "object" || rulesError === null) return [];
  if (isStatFieldError(rulesError)) return [{ field: "rules", error: pick(rulesError) }];
  return Object.entries(rulesError).flatMap(([key, value]: [string, unknown]): RuleErrorEntry[] => {
    if (key === "root") return isStatFieldError(value) ? [{ field: "rules" as const, error: pick(value) }] : [];
    if (!/^\d+$/.test(key) || typeof value !== "object" || value === null) return [];
    return Object.entries(value).flatMap(([ruleField, ruleError]: [string, unknown]): RuleErrorEntry[] =>
      isStatRuleErrorField(ruleField) && isStatFieldError(ruleError)
        ? [{ field: `rules.${Number(key)}.${ruleField}` as const, error: pick(ruleError) }]
        : [],
    );
  });
}

/**
 * 스탯 목록이 인덱스를 거치지 않고 바뀔 때(필드 배열 이름에 `setValue`) 칸 오류를 스탯 id 를 따라 새 자리로 옮긴 목록을
 * 돌려준다. RHF 는 필드 배열의 `insert`·`remove` 에서만 오류를 함께 밀고 당기고, `setValue` 는 값만 바꿔 오류를 옛
 * 인덱스에 둔다 — 그대로 두면 끼워 넣은 자리 뒤의 스탯들이 바로 앞 스탯의 오류를 달고 보인다.
 *
 * 규칙 목록의 오류(목록 자체와 줄마다의 칸)도 함께 옮긴다 — 스탯 안 규칙 순서는 그대로라 규칙 인덱스는 바꾸지 않는다.
 *
 * `beforeIds` 는 바꾸기 전 id 순서, `errorAt` 은 그 순서의 인덱스로 스탯 하나의 오류 객체를 읽는다. `afterIds` 에 없는
 * 스탯의 오류는 버린다. 옮긴 오류는 type·message 만 담는다 — `ref` 는 옛 자리의 입력칸이라 `setError` 가 새로 잡게 둔다.
 */
export function moveStatErrorsById(
  beforeIds: readonly string[],
  errorAt: (index: number) => object | undefined,
  afterIds: readonly string[],
): MovedStatError[] {
  const moved: MovedStatError[] = [];
  beforeIds.forEach((id, beforeIndex) => {
    const statIndex = afterIds.indexOf(id);
    const statErrors = errorAt(beforeIndex);
    if (statIndex === -1 || statErrors === undefined) return;
    for (const [field, error] of Object.entries(statErrors)) {
      if (field === "rules") {
        for (const ruleError of ruleErrorsOf(error)) moved.push({ statIndex, ...ruleError });
        continue;
      }
      if (!isStatErrorField(field) || !isStatFieldError(error)) continue;
      moved.push({ statIndex, field, error: pick(error) });
    }
  });
  return moved;
}
