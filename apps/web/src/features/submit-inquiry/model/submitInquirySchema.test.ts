import { describe, expect, it } from "vitest";

import { SUBMIT_INQUIRY_SCHEMA } from "./submitInquirySchema";

function validPayload() {
  return { category: "bug" as const, title: "제목", body: "내용" };
}

describe("SUBMIT_INQUIRY_SCHEMA", () => {
  it("rejects an empty title", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), title: "" });

    expect(result.success).toBe(false);
  });

  it("rejects an empty body", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), body: "" });

    expect(result.success).toBe(false);
  });

  it("accepts a title at exactly 100 characters", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), title: "가".repeat(100) });

    expect(result.success).toBe(true);
  });

  it("rejects a title over 100 characters", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), title: "가".repeat(101) });

    expect(result.success).toBe(false);
  });

  it("accepts a body at exactly 2000 characters", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), body: "가".repeat(2000) });

    expect(result.success).toBe(true);
  });

  it("rejects a body over 2000 characters", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), body: "가".repeat(2001) });

    expect(result.success).toBe(false);
  });

  it("rejects an unknown category", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse({ ...validPayload(), category: "unknown" });

    expect(result.success).toBe(false);
  });

  it("makes attachmentAssetId optional", () => {
    const result = SUBMIT_INQUIRY_SCHEMA.safeParse(validPayload());

    expect(result.success).toBe(true);
    expect(result.success && result.data.attachmentAssetId).toBeUndefined();
  });
});
