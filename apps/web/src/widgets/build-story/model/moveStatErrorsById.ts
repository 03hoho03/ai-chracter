import type { StatDefValues } from "@/features/build-story";

/** 오류가 붙을 수 있는 스탯 칸. `Record` 로 적어 스탯에 칸이 늘면 여기도 늘리라고 타입이 알린다. */
type StatErrorField = Exclude<keyof StatDefValues, "id">;

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

function isStatErrorField(key: string): key is StatErrorField {
  return Object.hasOwn(STAT_ERROR_FIELDS, key);
}

type StatFieldError = { type: string; message?: string };

function isStatFieldError(value: unknown): value is StatFieldError {
  return typeof value === "object" && value !== null && "type" in value && typeof value.type === "string";
}

export type MovedStatError = { statIndex: number; field: StatErrorField; error: StatFieldError };

/**
 * 스탯 목록이 인덱스를 거치지 않고 바뀔 때(필드 배열 이름에 `setValue`) 칸 오류를 스탯 id 를 따라 새 자리로 옮긴 목록을
 * 돌려준다. RHF 는 필드 배열의 `insert`·`remove` 에서만 오류를 함께 밀고 당기고, `setValue` 는 값만 바꿔 오류를 옛
 * 인덱스에 둔다 — 그대로 두면 끼워 넣은 자리 뒤의 스탯들이 바로 앞 스탯의 오류를 달고 보인다.
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
      if (!isStatErrorField(field) || !isStatFieldError(error)) continue;
      moved.push({ statIndex, field, error: { type: error.type, message: error.message } });
    }
  });
  return moved;
}
