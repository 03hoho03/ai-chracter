import { describe, expect, it } from "vitest";

import { flattenFieldErrorPaths } from "./fieldErrorPaths";

function fieldError(message = "필수 항목이에요."): { type: string; message: string } {
  return { type: "custom", message };
}

describe("flattenFieldErrorPaths", () => {
  // RHF의 FieldErrors 타입은 배열 필드마다 `root?: FieldError`를 둔다 — 배열 자체의 위반(`.max()`
  // 등)이 인덱스 자리를 차지 못해 여기 담긴다(errorTabs.test.ts와 같은 모양). `root`는 RHF 예약
  // 키지 폼 경로가 아니므로 꼬리를 벗겨 원래 필드 경로로 낸다 — 라벨 맵(missingFieldsMessage.ts에
  // 넘기는 폼 경로 → 라벨)에 그 키가 있어야 토스트 라벨이 안정되고, `data-field-path` 스크롤
  // 폴백(useFocusFirstError.ts)도 이 문자열과 정확히 일치해야 걸린다.
  it("배열 루트 에러(.root)는 꼬리를 벗겨 배열 경로 자체로 평탄화된다", () => {
    const errors = { startingSetups: Object.assign([], { root: fieldError() }) };

    expect(flattenFieldErrorPaths(errors)).toEqual(["startingSetups"]);
  });

  it("중첩된 배열의 루트 에러도 같은 방식으로 꼬리만 벗긴다", () => {
    const errors = {
      startingSetups: [{ stats: Object.assign([], { root: fieldError() }) }],
    };

    expect(flattenFieldErrorPaths(errors)).toEqual(["startingSetups.0.stats"]);
  });

  // `root`가 접두 없이 단독으로 오는 자리는 RHF의 폼 수준 에러(`errors.root`,
  // `form.setError("root.server", ...)`처럼)다 — 벗길 상위 경로가 없으므로 그대로 "root"를 낸다.
  // 빈 문자열로 만들면 그 경로 자체가 사라진다(스펙에서 명시적으로 금지한 동작).
  it("접두 없는 단독 root는 그대로 유지된다", () => {
    const errors = { root: fieldError("발행에 실패했어요.") };

    expect(flattenFieldErrorPaths(errors)).toEqual(["root"]);
  });

  it("root 아래 자식이 있으면 벗기지 않는다 — 꼬리가 root가 아니라서", () => {
    const errors = { root: { server: fieldError("서버 오류예요.") } };

    expect(flattenFieldErrorPaths(errors)).toEqual(["root.server"]);
  });

  it("배열 루트 에러와 다른 필드 에러가 함께 있어도 각각 올바르게 평탄화된다", () => {
    const errors = {
      profile: { name: fieldError() },
      startingSetups: Object.assign([], { root: fieldError("최대 4개까지 만들 수 있어요.") }),
    };

    expect(flattenFieldErrorPaths(errors)).toEqual(["profile.name", "startingSetups"]);
  });
});
