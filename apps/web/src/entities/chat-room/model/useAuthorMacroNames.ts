import { createContext, useContext } from "react";

import type { AuthorMacroNames } from "@/shared/lib/text/authorMacros";

/** `AuthorMacroNamesProvider` 가 채우는 이름 컨텍스트. */
export const AuthorMacroNamesContext = createContext<AuthorMacroNames | undefined>(undefined);

/** 감싼 자리면 `{{user}}`·`{{char}}` 를 바꿀 이름, 아니면 undefined(매크로를 글자 그대로 둔다). */
export function useAuthorMacroNames(): AuthorMacroNames | undefined {
  return useContext(AuthorMacroNamesContext);
}
