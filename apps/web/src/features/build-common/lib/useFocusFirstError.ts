import { useCallback, useEffect, useRef } from "react";
import type { FieldValues, Path, UseFormReturn } from "react-hook-form";

import type { FirstErrorLocation } from "../model/firstErrorLocation";

/** `IconPicker`/`ColorPicker`/`GeneratedImageField`처럼 `setFocus`로 포커스를 줄 DOM이 없는 필드는
 * 이 속성으로 스크롤 대상을 찾는다(builder-techspec.md §9-1, builder-goal-prompt.md §5-4). 값은
 * `firstErrorLocation`이 돌려주는 `fieldPath`와 정확히 같은 문자열이다 — `field.id`(배열 항목의 RHF
 * 내부 uuid) 없이도 매칭되도록, DOM `id` 규칙을 역산하지 않고 이 속성을 직접 심는다.
 *
 * JSX는 속성 이름을 변수로 쓸 수 없어 호출부(ProfileTab.tsx의 `profile.image`, StatTab.tsx의
 * `stats.*.icon`/`.color`)는 이 문자열("data-field-path")을 그대로 리터럴로 심는다 — 값(fieldPath)만
 * 맞으면 된다. */
const FIELD_PATH_ATTRIBUTE = "data-field-path";

/**
 * builder-techspec.md §9-1 — 발행 실패 시 첫 에러 필드로 이동한다. Radix `TabsContent`는 비활성
 * 탭을 언마운트하므로(`forceMount` 미사용) 다른 탭 필드로 포커스를 줄 DOM이 없다. 그래서 이동은
 * 2단계다: 대상 탭이 활성 탭과 다르면 먼저 전환하고, 그 탭이 마운트를 커밋한 뒤(`useEffect`) 다음
 * 프레임(`requestAnimationFrame`)에 실제 포커스를 준다. 이미 활성 탭이면 전환 없이 바로 다음
 * 프레임에 포커스한다(불필요한 리렌더 회피).
 *
 * 반환하는 함수를 발행 실패 경로에서 호출한다 — 폼 스키마 실패(`handleSubmit`의 `onInvalid`)와
 * 서버 거부(`form.setError()` 이후) 둘 다.
 */
export function useFocusFirstError<T extends FieldValues>({
  form,
  activeTab,
  setActiveTab,
}: {
  form: UseFormReturn<T>;
  activeTab: string;
  setActiveTab: (tabId: string) => void;
}): (location: FirstErrorLocation | undefined) => void {
  const pendingFieldPathRef = useRef<string>(undefined);
  // handlePublish는 async라 발행 await 도중 사용자가 탭을 수동 전환하면 클릭 시점 activeTab을 든
  // 클로저가 stale해진다 — 호출 시점의 최신값을 읽도록 ref로 미러링한다(builder-goal-prompt.md §5-4).
  const activeTabRef = useRef(activeTab);

  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  useEffect(() => {
    const fieldPath = pendingFieldPathRef.current;
    if (fieldPath === undefined) return;
    pendingFieldPathRef.current = undefined;
    const frameId = requestAnimationFrame(() => focusAndScroll(form, fieldPath));
    return () => cancelAnimationFrame(frameId);
  }, [activeTab, form]);

  return useCallback(
    (location: FirstErrorLocation | undefined) => {
      if (location === undefined) return;
      if (location.tabId === activeTabRef.current) {
        requestAnimationFrame(() => focusAndScroll(form, location.fieldPath));
        return;
      }
      pendingFieldPathRef.current = location.fieldPath;
      setActiveTab(location.tabId);
    },
    [form, setActiveTab],
  );
}

function focusAndScroll<T extends FieldValues>(form: UseFormReturn<T>, fieldPath: string): void {
  // fieldPath는 firstErrorLocation이 런타임에 계산한 문자열이라 Path<T>로 정적으로 좁힐 수 없다
  // (StoryBuilderShell.tsx의 zodResolver 캐스팅과 같은 사유).
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  form.setFocus(fieldPath as Path<T>);

  // register()/Controller 필드 대부분은 위 setFocus만으로 포커스 + (브라우저 기본 동작인) 스크롤까지
  // 끝난다. IconPicker/ColorPicker/GeneratedImageField처럼 포커스 가능한 DOM을 setFocus에 노출하지
  // 않는 필드는 조용히 아무 일도 하지 않으므로, 그런 필드가 심어 둔 FIELD_PATH_ATTRIBUTE로 최소한
  // 스크롤은 되게 한다(builder-goal-prompt.md §5-4 — "최소한 스크롤은 되게").
  const fallbackTarget = document.querySelector(`[${FIELD_PATH_ATTRIBUTE}="${fieldPath}"]`);
  fallbackTarget?.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "center",
  });
}
