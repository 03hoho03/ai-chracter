import { describe, expect, it } from "vitest";

import { submitInquirySchema } from "./schema";

function validPayload() {
  return { category: "bug" as const, title: "제목", body: "내용" };
}

describe("submitInquirySchema", () => {
  it("rejects an empty title", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), title: "" });

    expect(result.success).toBe(false);
  });

  it("rejects an empty body", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), body: "" });

    expect(result.success).toBe(false);
  });

  it("accepts a title at exactly 100 characters", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), title: "가".repeat(100) });

    expect(result.success).toBe(true);
  });

  it("rejects a title over 100 characters", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), title: "가".repeat(101) });

    expect(result.success).toBe(false);
  });

  it("accepts a body at exactly 2000 characters", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), body: "가".repeat(2000) });

    expect(result.success).toBe(true);
  });

  it("rejects a body over 2000 characters", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), body: "가".repeat(2001) });

    expect(result.success).toBe(false);
  });

  it("rejects an unknown category", () => {
    const result = submitInquirySchema.safeParse({ ...validPayload(), category: "unknown" });

    expect(result.success).toBe(false);
  });

  it("makes attachmentAssetId optional", () => {
    const result = submitInquirySchema.safeParse(validPayload());

    expect(result.success).toBe(true);
    expect(result.success && result.data.attachmentAssetId).toBeUndefined();
  });
});
