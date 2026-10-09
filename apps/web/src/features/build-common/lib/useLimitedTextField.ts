import { useState, type ChangeEvent } from "react";
import { useFormContext, useWatch, type FieldPath, type FieldValues } from "react-hook-form";

import { clampCharacters, countCharacters } from "@/shared/lib/text/characterCount";

/**
 * 글자 수 상한이 있는 `register` 칸. `register` 의 `onChange` 를 감싸 상한(코드 포인트)을 넘는 글을 잘라서 폼에 넘기고,
 * 카운터에 쓸 글자 수와 방금 잘렸는지를 함께 돌려준다. 브라우저의 `maxLength` 는 UTF-16 단위라 서버가 받는 이모지를
 * 막고, 붙여넣기가 왜 잘렸는지도 말해 주지 않아 쓰지 않는다. `setValue` 로 글을 넣는 길(이미지 넣기 등)은 이 감싸기를
 * 거치지 않으므로 발행 검사와 서버가 마지막으로 막는다.
 */
export function useLimitedTextField<TValues extends FieldValues>(name: FieldPath<TValues>, max: number) {
  const { register, control } = useFormContext<TValues>();
  const value: unknown = useWatch({ control, name });
  const [isTruncated, setIsTruncated] = useState(false);
  const registration = register(name);

  return {
    registration: {
      ...registration,
      onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const clamped = clampCharacters(event.target.value, max);
        if (clamped.isTruncated) event.target.value = clamped.value;
        setIsTruncated(clamped.isTruncated);
        return registration.onChange(event);
      },
    },
    count: countCharacters(typeof value === "string" ? value : ""),
    isTruncated,
  };
}
