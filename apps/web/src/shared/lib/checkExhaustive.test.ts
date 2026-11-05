import { describe, expect, it } from "vitest";

import { checkExhaustive } from "./checkExhaustive";

type Status = "ok" | "failed";

function label(status: Status): string {
  switch (status) {
    case "ok":
      return "성공";
    case "failed":
      return "실패";
    default:
      checkExhaustive(status);
      return "알 수 없음";
  }
}

describe("checkExhaustive", () => {
  it("타입에 없는 값이 런타임에 닿아도 던지지 않고 호출한 쪽의 기본값으로 흘러간다", () => {
    const fromServer: string = "new-status";
    expect(() => checkExhaustive(fromServer as never)).not.toThrow();
    expect(label(fromServer as Status)).toBe("알 수 없음");
  });

  it("다루지 않은 멤버가 남으면 컴파일 에러가 난다", () => {
    const partial = (status: Status) => {
      if (status === "ok") return;
      // @ts-expect-error 남은 멤버 "failed" 는 never 가 아니다
      checkExhaustive(status);
    };
    expect(partial).toBeTypeOf("function");
  });
});
