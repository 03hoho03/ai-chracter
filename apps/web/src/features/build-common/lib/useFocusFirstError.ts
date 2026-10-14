import { useCallback, useEffect, useRef } from "react";
import type { FieldValues, Path, UseFormReturn } from "react-hook-form";

import type { FirstErrorLocation } from "../model/firstErrorLocation";

/** `IconPicker`/`ColorPicker`/`GeneratedImageField`처럼 `setFocus`로 포커스를 줄 DOM이 없는 필드는
 * 이 속성으로 스크롤 대상을 찾는다. 값은
 * `firstErrorLocation`이 돌려주는 `fieldPath`와 정확히 같은 문자열이다 — `field.id`(배열 항목의 RHF
 * 내부 uuid) 없이도 매칭되도록, DOM `id` 규칙을 역산하지 않고 이 속성을 직접 심는다.
 *
 * 서버 거절처럼 목록 자리만 가리키는 경로(`startingSetups.0.stats`, `keywordNotes`)를 위해 목록을 감싸는 요소에도 심는다 —
 * 경로에 맞는 표식이 없으면 조상 경로의 표식을 찾는다.
 *
 * JSX는 속성 이름을 변수로 쓸 수 없어 호출부(ProfileTab.tsx의 `profile.image`, StatTab.tsx의
 * `stats.*.icon`/`.color`)는 이 문자열("data-field-path")을 그대로 리터럴로 심는다 — 값(fieldPath)만
 * 맞으면 된다. */
const FIELD_PATH_ATTRIBUTE = "data-field-path";

/**
 * 발행 실패 시 첫 에러 필드로 이동한다. Radix `TabsContent`는 비활성
 * 탭을 언마운트하므로(`forceMount` 미사용) 다른 탭 필드로 포커스를 줄 DOM이 없다. 그래서 이동은
 * 2단계다: 대상 탭이 활성 탭과 다르면 먼저 전환하고, 그 탭이 마운트를 커밋한 뒤(`useEffect`) 다음
 * 프레임(`requestAnimationFrame`)에 실제 포커스를 준다. 이미 활성 탭이면 전환 없이 바로 다음
 * 프레임에 포커스한다(불필요한 리렌더 회피).
 *
 * 반환하는 함수를 발행 실패 경로에서 호출한다 — 폼 스키마 실패(`handleSubmit`의 `onInvalid`)와
 * 서버 거부(`form.setError()` 이후) 둘 다. 폼은 `shouldFocusError: false` 여야 한다 — RHF 가 검증 실패 직후 스스로 첫 칸에
 * 포커스하면 확인 목록이 서기 전 자리에서 스크롤이 끝나고, 아래 함수가 포커스가 옮겨 갔는지로 대체 경로를 고르는 판단도 틀어진다.
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
  // 클로저가 stale해진다 — 호출 시점의 최신값을 읽도록 ref로 미러링한다.
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

/** 컨테이너 안에서 포커스를 받을 수 있는 첫 요소를 찾는 셀렉터. 숨은 요소는 `focus()` 가 조용히 실패하므로 걸러 내지 않는다. */
const FOCUSABLE_SELECTOR =
  'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function focusAndScroll<T extends FieldValues>(form: UseFormReturn<T>, fieldPath: string): void {
  const behavior: ScrollBehavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  const previous = document.activeElement;
  // fieldPath는 firstErrorLocation이 런타임에 계산한 문자열이라 Path<T>로 정적으로 좁힐 수 없다
  // (StoryBuilderShell.tsx의 zodResolver 캐스팅과 같은 사유).
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  form.setFocus(fieldPath as Path<T>);

  // register()/Controller 필드 대부분은 위 setFocus로 포커스가 옮겨 가고 브라우저가 그 칸을 화면 안으로 민다. 그래도 한 번 더
  // 화면 안으로 맞춘다 — 첫 발행 실패처럼 같은 순간 폼 열 맨 위에 확인 목록이 새로 서면, 포커스 때 맞춘 자리에서 칸이 목록 높이만큼
  // 아래로 밀려 화면 밖에 남는다. 이미 보이면 움직이지 않는다(`nearest`).
  const focused = document.activeElement;
  if (focused !== previous && focused instanceof HTMLElement) {
    focused.scrollIntoView({ block: "nearest" });
    return;
  }

  // 포커스가 옮겨 가지 않았다 — IconPicker/ColorPicker/GeneratedImageField·키워드 칩처럼 setFocus에 포커스 가능한 DOM을 내놓지
  // 않는 칸이거나, 서버 거절처럼 목록 자리만 가리키는 경로다. 그 경로나 가장 가까운 조상 경로에 심어 둔 FIELD_PATH_ATTRIBUTE
  // 요소를 찾아 그 요소(포커스를 받는 컨트롤이면 그 자체, 아니면 안의 첫 컨트롤)로 포커스를 옮기고 화면 안으로 민다. 포커스를
  // 그대로 두면 누른 목록 줄에 남은 채 그 줄이 스크롤로 화면 위로 밀려, 키보드 사용자가 보이지 않는 자리에서 다음 Tab 을 누르게 된다.
  // 표식이 어디에도 없으면 열린 탭 본문으로 옮긴다.
  const container = closestFieldPathElement(fieldPath);
  if (container) {
    const target = container.tabIndex >= 0 ? container : container.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    target?.focus({ preventScroll: true });
    container.scrollIntoView({ behavior, block: "center" });
    return;
  }
  const panel = document.querySelector<HTMLElement>('[data-slot="tabs-content"][data-state="active"]');
  panel?.focus({ preventScroll: true });
  panel?.scrollIntoView({ behavior, block: "start" });
}

/** 경로 자신부터 조상 경로 순으로 올라가며 FIELD_PATH_ATTRIBUTE 가 붙은 첫 요소. 없으면 `null`. */
function closestFieldPathElement(fieldPath: string): HTMLElement | null {
  const segments = fieldPath.split(".");
  for (let length = segments.length; length > 0; length--) {
    const element = document.querySelector(`[${FIELD_PATH_ATTRIBUTE}="${segments.slice(0, length).join(".")}"]`);
    if (element instanceof HTMLElement) return element;
  }
  return null;
}
