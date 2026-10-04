import { useFormContext, useWatch, type Path } from "react-hook-form";

import type { CharacterBuilderFormValues } from "@/features/build-character";
import { AuthorMacroNotice } from "@/features/build-common";

/** 캐릭터 글 칸의 매크로 알림. 칸 값을 읽어 공용 알림에 넘긴다(캐릭터에서는 `{{char}}` 도 이름으로 바뀐다). */
export function CharacterMacroNotice({ name }: { name: Path<CharacterBuilderFormValues> }) {
  const { control } = useFormContext<CharacterBuilderFormValues>();
  const value = useWatch({ control, name });
  if (typeof value !== "string") return null;
  return <AuthorMacroNotice text={value} contentType="character" />;
}
