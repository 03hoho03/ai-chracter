import { describe, expect, it } from "vitest";

import { storySettingSchema } from "./schema";

describe("storySettingSchema", () => {
  it.each(["basic", "emotional", "simulation"] as const)(
    "requires worldSetting when promptTemplate is %s",
    (promptTemplate) => {
      const result = storySettingSchema.safeParse({ promptTemplate });

      expect(result.success).toBe(false);
      expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
        "worldSetting",
      ]);
    },
  );

  it.each(["basic", "emotional", "simulation"] as const)(
    "passes without customPrompt when promptTemplate is %s and worldSetting is set",
    (promptTemplate) => {
      const result = storySettingSchema.safeParse({ promptTemplate, worldSetting: "세계관 설명" });

      expect(result.success).toBe(true);
    },
  );

  it("requires customPrompt when promptTemplate is custom", () => {
    const result = storySettingSchema.safeParse({ promptTemplate: "custom" });

    expect(result.success).toBe(false);
    expect(result.success ? [] : result.error.issues.map((issue) => issue.path)).toContainEqual([
      "customPrompt",
    ]);
  });

  it("passes without worldSetting when promptTemplate is custom and customPrompt is set", () => {
    const result = storySettingSchema.safeParse({
      promptTemplate: "custom",
      customPrompt: "커스텀 프롬프트",
    });

    expect(result.success).toBe(true);
  });

  it("never requires developmentExample regardless of promptTemplate", () => {
    const basic = storySettingSchema.safeParse({
      promptTemplate: "basic",
      worldSetting: "세계관 설명",
    });
    const custom = storySettingSchema.safeParse({
      promptTemplate: "custom",
      customPrompt: "커스텀 프롬프트",
    });

    expect(basic.success).toBe(true);
    expect(custom.success).toBe(true);
  });

  it("defaults promptTemplate to basic when omitted, still requiring worldSetting", () => {
    const missingWorldSetting = storySettingSchema.safeParse({});
    const withWorldSetting = storySettingSchema.safeParse({ worldSetting: "세계관 설명" });

    expect(missingWorldSetting.success).toBe(false);
    expect(withWorldSetting.success).toBe(true);
    expect(withWorldSetting.success && withWorldSetting.data.promptTemplate).toBe("basic");
  });
});
