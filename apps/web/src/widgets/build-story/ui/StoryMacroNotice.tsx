import { useFormContext, useWatch, type Path } from "react-hook-form";

import type { StoryBuilderFormValues } from "@/features/build-story";
import { AuthorMacroNotice } from "@/features/build-common";

/** 스토리 글 칸의 매크로 알림. 칸 값을 읽어 공용 알림에 넘긴다(글이 아닌 값은 알릴 것이 없다). */
export function StoryMacroNotice({ name }: { name: Path<StoryBuilderFormValues> }) {
  const { control } = useFormContext<StoryBuilderFormValues>();
  const value = useWatch({ control, name });
  if (typeof value !== "string") return null;
  return <AuthorMacroNotice text={value} contentType="story" />;
}
