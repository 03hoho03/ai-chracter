import { describe, expect, it } from "vitest";

import { formToCreateRequest, formToUpdateRequest } from "./formToServer";

describe("formToCreateRequest", () => {
  it("maps 'unspecified' gender to null and carries setAsDefault", () => {
    expect(
      formToCreateRequest({ name: "하늘", gender: "unspecified", description: "", setAsDefault: true }),
    ).toEqual({ name: "하늘", gender: null, description: "", setAsDefault: true });
  });

  it("keeps male/female as the server literal", () => {
    expect(
      formToCreateRequest({ name: "하늘", gender: "female", description: "밤하늘", setAsDefault: false }),
    ).toEqual({ name: "하늘", gender: "female", description: "밤하늘", setAsDefault: false });
  });
});

describe("formToUpdateRequest", () => {
  // `PUT /me/personas/{id}`는 `setAsDefault`를 받지 않는다(기본 변경은 `PUT /me/default-persona`).
  it("drops setAsDefault and maps gender", () => {
    expect(
      formToUpdateRequest({ name: "하늘", gender: "male", description: "설명", setAsDefault: true }),
    ).toEqual({ name: "하늘", gender: "male", description: "설명" });
  });
});
