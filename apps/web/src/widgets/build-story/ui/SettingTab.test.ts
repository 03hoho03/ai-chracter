import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { StoryBuilderFormValues } from "@/features/build-story";

import { SettingTab } from "./SettingTab";

function SettingTabWithForm({ defaultUserName = "" }: { defaultUserName?: string }) {
  const form = useForm<StoryBuilderFormValues>({
    defaultValues: {
      storySetting: {
        promptTemplate: "basic",
        developmentExamples: [{ userLine: "", assistantLine: "" }],
        defaultUserName,
      },
    },
  });
  return createElement(FormProvider<StoryBuilderFormValues>, { ...form, children: createElement(SettingTab) });
}

function fieldTagOf(html: string, name: string): string {
  const match = new RegExp(`<(\\w+)[^>]*name="${name.replaceAll(".", "\\.")}"`).exec(html);
  return match?.[1] ?? "";
}

describe("SettingTab development examples", () => {
  // 전개 예시는 여러 문단과 상태창 코드블록을 담는다. 한 줄 입력칸은 붙여 넣은 줄바꿈을 지워 버리므로
  // 두 칸 모두 여러 줄 입력칸이어야 한다.
  it.each(["userLine", "assistantLine"])("renders %s as a multi-line field", (key) => {
    const html = renderToStaticMarkup(createElement(SettingTabWithForm));
    expect(fieldTagOf(html, `storySetting.developmentExamples.0.${key}`)).toBe("textarea");
  });
});

describe("SettingTab default user name", () => {
  // 빌더는 작품 기본 이름을 받지 않는다. 폼에 남은 값은 미리보기로만 실려 가고 화면에는 칸이 없어야 한다.
  it("has no default user name field even when the form carries a stored name", () => {
    const html = renderToStaticMarkup(createElement(SettingTabWithForm, { defaultUserName: "모험가" }));
    expect(html).toContain('name="storySetting.userGoal"');
    expect(fieldTagOf(html, "storySetting.defaultUserName")).toBe("");
  });
});
