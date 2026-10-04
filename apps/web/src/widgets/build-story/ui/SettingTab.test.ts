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
  // 사용자에 관한 칸이 한 자리에 모이도록 기본 이름은 "사용자의 역할과 목표" 바로 뒤, 전개 예시 앞에 선다.
  it("sits right after the user's role and goal", () => {
    const html = renderToStaticMarkup(createElement(SettingTabWithForm));
    const userGoal = html.indexOf('name="storySetting.userGoal"');
    const defaultUserName = html.indexOf('name="storySetting.defaultUserName"');
    const examples = html.indexOf('name="storySetting.developmentExamples.0.userLine"');
    expect(userGoal).toBeGreaterThan(-1);
    expect(defaultUserName).toBeGreaterThan(userGoal);
    expect(examples).toBeGreaterThan(defaultUserName);
  });

  // 자동저장은 폼 검증을 거치지 않으므로 서버가 받지 않을 이름은 발행 전에도 바로 알린다.
  it("shows a name the server would reject while typing, before any publish", () => {
    const html = renderToStaticMarkup(createElement(SettingTabWithForm, { defaultUserName: "별*" }));
    expect(html).toContain("고칠 때까지 이 칸은 저장되지 않아요");
    expect(renderToStaticMarkup(createElement(SettingTabWithForm, { defaultUserName: "조수" }))).not.toContain(
      "저장되지 않아요",
    );
  });
});
