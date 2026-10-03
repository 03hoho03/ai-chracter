import { describe, expect, it } from "vitest";

import { moveStatErrorsById } from "./moveStatErrorsById";

const maxError = { type: "custom", message: "최대값은 최소값보다 커야 해요" };
const nameError = { type: "too_small", message: "스탯 이름을 입력해주세요" };

describe("moveStatErrorsById", () => {
  it("되살린 스탯 뒤쪽 스탯의 오류는 인덱스가 아니라 id 를 따라 한 칸 뒤로 간다", () => {
    // [가, 다] 에서 다(1)에 오류가 있고, 나를 가운데로 되살린다.
    const errors = [undefined, { max: maxError }];
    const moved = moveStatErrorsById(["a", "c"], (index) => errors[index], ["a", "b", "c"]);
    expect(moved).toEqual([{ statIndex: 2, field: "max", error: maxError }]);
  });

  it("한 스탯의 여러 칸 오류를 모두 옮기고, 오류 없는 스탯과 되살린 스탯 자리에는 아무것도 두지 않는다", () => {
    const errors = [{ name: nameError }, undefined, { max: maxError, name: nameError }];
    const moved = moveStatErrorsById(["a", "b", "c"], (index) => errors[index], ["x", "a", "b", "c"]);
    expect(moved).toEqual([
      { statIndex: 1, field: "name", error: nameError },
      { statIndex: 3, field: "max", error: maxError },
      { statIndex: 3, field: "name", error: nameError },
    ]);
  });

  it("오류 객체의 칸 이름이 아닌 키와 FieldError 모양이 아닌 값은 옮기지 않는다", () => {
    const errors = [{ ref: { name: "x" }, type: "custom", message: "배열 전체 오류", id: maxError, max: maxError }];
    const moved = moveStatErrorsById(["a"], (index) => errors[index], ["b", "a"]);
    expect(moved).toEqual([{ statIndex: 1, field: "max", error: maxError }]);
  });

  it("옮길 목록에 없는 스탯의 오류는 버린다", () => {
    const errors = [{ max: maxError }];
    expect(moveStatErrorsById(["gone"], (index) => errors[index], ["a"])).toEqual([]);
  });

  it("옮긴 오류는 type·message 만 담는다(ref 는 setError 가 새 자리의 칸으로 다시 잡는다)", () => {
    const errors = [{ max: { ...maxError, ref: { name: "old" } } }];
    expect(moveStatErrorsById(["a"], (index) => errors[index], ["a"])).toEqual([
      { statIndex: 0, field: "max", error: maxError },
    ]);
  });
});
