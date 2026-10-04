import { useMemo, type ReactNode } from "react";

import type { AuthorMacroNames } from "@/shared/lib/text/authorMacros";

import { AuthorMacroNamesContext } from "../model/useAuthorMacroNames";

type AuthorMacroNamesProviderProps = {
  names: AuthorMacroNames;
  children: ReactNode;
};

/**
 * 이 안의 `ChatMarkdown` 만 글 속 `{{user}}`·`{{char}}` 를 이름으로 바꿔 그린다. 작성자 글(첫 메시지·에필로그·작성
 * 가이드의 채팅 예시)만 감싼다 — 사용자 메시지는 보낼 때 이미 바꿨고, 모델 응답과 스트리밍 글은 작성자 글이 아니다.
 * 이름을 컨텍스트로 넘기는 이유는 그림 맵(`MediaTagImagesProvider`)과 같다 — 고를 메시지만 감싸고 `MessageBubble`
 * 을 지나는 prop 을 늘리지 않는다. 값 객체는 이름이 바뀔 때만 새로 만든다(바뀔 때마다 감싼 메시지를 다시 그린다).
 */
export function AuthorMacroNamesProvider({ names, children }: AuthorMacroNamesProviderProps) {
  const { userName, charName } = names;
  const value = useMemo(() => ({ userName, charName }), [userName, charName]);
  return <AuthorMacroNamesContext.Provider value={value}>{children}</AuthorMacroNamesContext.Provider>;
}
