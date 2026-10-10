import type { ReactNode } from "react";
import { useFormContext, useWatch } from "react-hook-form";

import { countCharacters } from "@/shared/lib/text/characterCount";
import { CharacterCount } from "@/shared/ui/CharacterCount";

type FieldCharacterCountProps = {
  id: string;
  /** 폼 칸의 이름(`useLimitedTextField` 가 돌려준 `registration.name`). */
  name: string;
  max: number;
  isTruncated: boolean;
  help?: ReactNode;
};

/** 폼 칸 하나의 글자 수 카운터. 그 칸만 구독해 타이핑마다 이 줄만 다시 그린다. */
export function FieldCharacterCount({ id, name, max, isTruncated, help }: FieldCharacterCountProps) {
  const { control } = useFormContext();
  const value: unknown = useWatch({ control, name });
  const count = countCharacters(typeof value === "string" ? value : "");
  return <CharacterCount id={id} count={count} max={max} isTruncated={isTruncated} help={help} />;
}
