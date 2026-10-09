import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { CharacterBuilderFormValues } from "@/features/build-character";

import { IntroTab } from "./IntroTab";

function IntroTabWithForm() {
  const form = useForm<CharacterBuilderFormValues>({
    defaultValues: {
      intro: { exampleDialogues: [{ id: "dialogue-1", userLine: "", characterLine: "" }], defaultUserName: "여행자" },
    },
  });
  return createElement(FormProvider<CharacterBuilderFormValues>, { ...form, children: createElement(IntroTab) });
}

function fieldTagOf(html: string, name: string): string {
  const match = new RegExp(`<(\\w+)[^>]*name="${name.replaceAll(".", "\\.")}"`).exec(html);
  return match?.[1] ?? "";
}

describe("IntroTab example dialogues", () => {
  // 캐릭터 대사는 지문과 대사를 문단으로 나눠 쓸 수 있다. 한 줄 입력칸은 붙여 넣은 줄바꿈을 지워 버리므로
  // 두 칸 모두 여러 줄 입력칸이어야 한다.
  it.each(["userLine", "characterLine"])("renders %s as a multi-line field", (key) => {
    const html = renderToStaticMarkup(createElement(IntroTabWithForm));
    expect(fieldTagOf(html, `intro.exampleDialogues.0.${key}`)).toBe("textarea");
  });
});

describe("IntroTab default user name", () => {
  // 빌더는 작품 기본 이름을 받지 않는다. 폼에 남은 값은 미리보기로만 실려 가고 화면에는 칸이 없어야 한다.
  it("has no default user name field even when the form carries a stored name", () => {
    const html = renderToStaticMarkup(createElement(IntroTabWithForm));
    expect(fieldTagOf(html, "intro.defaultUserName")).toBe("");
  });
});
