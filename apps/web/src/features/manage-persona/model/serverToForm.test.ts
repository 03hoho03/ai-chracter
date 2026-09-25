import { describe, expect, it } from "vitest";

import { createFormDefaults, serverToForm } from "./serverToForm";

describe("createFormDefaults", () => {
  // "기본이 없으면 켜 둔다"는 규칙의 유일한 자리다. BE는 받은 값만 따른다.
  it("starts with setAsDefault on when there is no default persona", () => {
    expect(createFormDefaults(null).setAsDefault).toBe(true);
  });

  it("starts with setAsDefault off when a default persona already exists", () => {
    expect(createFormDefaults("4a1f0b3e-0000-4000-8000-000000000001").setAsDefault).toBe(false);
  });

  // 이름은 빈칸으로 시작한다(닉네임으로 미리 채우지 않는다).
  it("starts with an empty name, no gender and an empty description", () => {
    expect(createFormDefaults(null)).toEqual({
      name: "",
      gender: "unspecified",
      description: "",
      setAsDefault: true,
    });
  });
});

describe("serverToForm", () => {
  it("maps a null gender to 'unspecified'", () => {
    expect(
      serverToForm({
        id: "4a1f0b3e-0000-4000-8000-000000000001",
        name: "하늘",
        gender: null,
        description: "밤하늘",
        createdAt: "2026-09-24T00:00:00Z",
        updatedAt: "2026-09-24T00:00:00Z",
      }),
    ).toEqual({ name: "하늘", gender: "unspecified", description: "밤하늘", setAsDefault: false });
  });

  it("keeps male/female", () => {
    expect(
      serverToForm({
        id: "4a1f0b3e-0000-4000-8000-000000000001",
        name: "하늘",
        gender: "male",
        description: "",
        createdAt: "2026-09-24T00:00:00Z",
        updatedAt: "2026-09-24T00:00:00Z",
      }).gender,
    ).toBe("male");
  });
});
