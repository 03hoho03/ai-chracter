import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { signUpDefaultValues, type SignUpFormValues } from "../model/signUpSchema";

import { LegalConsentFields } from "./LegalConsentFields";

function LegalConsentFieldsWithForm() {
  const form = useForm<SignUpFormValues>({ defaultValues: signUpDefaultValues });
  return createElement(FormProvider<SignUpFormValues>, {
    ...form,
    children: createElement(LegalConsentFields),
  });
}

function detailOf(html: string, term: string): string {
  const match = new RegExp(`<dt[^>]*>${term}</dt><dd[^>]*>([\\s\\S]*?)</dd>`).exec(html);
  return match?.[1] ?? "";
}

describe("LegalConsentFields overseas transfer detail", () => {
  // 가입자는 이 상세를 보고 국외이전에 동의한다. 처리방침이 이전받는 자로 올린 곳이 여기서 빠지면
  // 그곳으로의 이전에 대해 고지 없이 동의를 받은 셈이 되므로, 임베딩을 맡는 Voyage AI 도 칸마다 있어야 한다.
  const html = renderToStaticMarkup(createElement(LegalConsentFieldsWithForm));

  it("lists Voyage AI with its privacy contact among recipients", () => {
    const recipients = detailOf(html, "이전받는 자 / 연락처");
    expect(recipients).toContain("Voyage AI Innovations, Inc.");
    expect(recipients).toContain("legal@voyageai.com");
  });

  it.each(["이전되는 항목", "이전 국가 / 시기 / 방법", "이용 목적 / 보유·이용기간"])(
    "mentions Voyage AI in %s",
    (term) => {
      expect(detailOf(html, term)).toContain("Voyage AI Innovations, Inc.");
    },
  );
});
