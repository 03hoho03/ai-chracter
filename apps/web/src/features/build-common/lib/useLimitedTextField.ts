import { useState, type ChangeEvent, type CompositionEvent } from "react";
import { useFormContext, type FieldPath, type FieldValues } from "react-hook-form";

import { canReportComposingValue, clampFieldAtCaret, isComposingChange } from "./clampFieldAtCaret";

type TextField = HTMLInputElement | HTMLTextAreaElement;

/**
 * 글자 수 상한이 있는 `register` 칸. `register` 의 `onChange` 를 감싸 상한(코드 포인트)을 넘는 글을 방금 넣은 부분에서
 * 덜어내 폼에 넘기고, 방금 잘렸는지를 함께 돌려준다. 브라우저의 `maxLength` 는 UTF-16 단위라 서버가 받는 이모지를
 * 막고, 붙여넣기가 왜 잘렸는지도 말해 주지 않아 쓰지 않는다. IME 조합 중에는 자르지 않고 조합이 끝날 때 자른다.
 * `setValue` 로 글을 넣는 길(이미지 넣기 등)은 이 감싸기를 거치지 않으므로 그 길이 따로 막고, 발행 검사와 서버가
 * 마지막으로 막는다. 조합 중 값이 상한을 넘으면 폼에 알리지 않아 자동저장이 넘친 값을 보내지 않는다.
 *
 * 글자 수는 여기서 구독하지 않는다 — 탭 전체가 타이핑마다 다시 그려지지 않게 카운터(`FieldCharacterCount`)가 그 칸만
 * 구독한다.
 */
export function useLimitedTextField<TValues extends FieldValues>(name: FieldPath<TValues>, max: number) {
  const { register, getValues } = useFormContext<TValues>();
  const [isTruncated, setIsTruncated] = useState(false);
  const registration = register(name);

  return {
    registration: {
      ...registration,
      onChange: (event: ChangeEvent<TextField>) => {
        if (isComposingChange(event)) {
          // 상한을 넘은 조합 중 값은 폼에 알리지 않는다 — 조합이 끝날 때 자른 값으로 알린다.
          if (!canReportComposingValue(event.target.value, max)) return Promise.resolve();
        } else {
          setIsTruncated(clampFieldAtCaret(event.target, max));
        }
        return registration.onChange(event);
      },
      onCompositionEnd: (event: CompositionEvent<TextField>) => {
        const field = event.currentTarget;
        if (clampFieldAtCaret(field, max)) setIsTruncated(true);
        // 조합 중에 알리지 않고 넘긴 값이 있으면 폼이 직전 값에 머물러 있다 — 칸과 다르면 지금 알린다.
        if (field.value !== getValues(name)) void registration.onChange({ target: field, type: "change" });
      },
    },
    isTruncated,
  };
}
