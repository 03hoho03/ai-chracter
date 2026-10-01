import { useFormContext, useWatch } from "react-hook-form";

import type { MediaBookValues, StoryBuilderFormValues } from "@/features/build-story";

/**
 * 미디어 북 화면이 폼을 읽고 쓰는 유일한 길. 쓰기는 언제나 `setValue("mediaBook", 새 값 전체)` 다 — 배열 항목
 * 단위 액션(`useFieldArray` 의 append·remove)은 자동저장 구독이 놓치는 경우가 있어(삭제·재정렬이 다음 편집 때까지
 * 저장되지 않는 것을 재현했다) 쓰지 않고, `setValue` 는 호출한 자리에서 바로 변경을 알려 자동저장이 확실히 돈다.
 * 비동기 작업(업로드) 뒤에는 `getMediaBook()` 으로 그 순간의 값을 다시 읽어 그 위에 쓴다.
 */
export function useMediaBookEditor() {
  const { control, getValues, setValue } = useFormContext<StoryBuilderFormValues>();
  const mediaBook = useWatch({ control, name: "mediaBook" });

  return {
    mediaBook,
    getMediaBook: () => getValues("mediaBook"),
    commit: (next: MediaBookValues) => setValue("mediaBook", next, { shouldDirty: true }),
  };
}
