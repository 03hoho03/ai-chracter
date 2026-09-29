import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { StoryBuilderFormValues } from "@/features/build-story";

import { SettingTab } from "./SettingTab";

function SettingTabWithForm() {
  const form = useForm<StoryBuilderFormValues>({
    defaultValues: { storySetting: { promptTemplate: "basic", developmentExamples: [{ userLine: "", assistantLine: "" }] } },
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
