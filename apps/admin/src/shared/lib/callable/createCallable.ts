import { createCallable as createReactCallable, type Callable, type UserComponent } from "react-call";

/**
 * `react-call` 의 `createCallable` 에 "닫히면 연 자리로 포커스를 돌려준다"만 더한다. 이 앱의 Callable 은
 * 반드시 이것으로 만든다(eslint `no-restricted-imports` 가 `react-call` 의 `createCallable` 을 직접 가져오는 것 —
 * 이름 import·재수출·네임스페이스 import — 을 막는다. `Callable` 같은 타입 import 는 허용된다).
 *
 * 왜 필요한가: 모달 `DialogContent` 는 닫힐 때 포커스 범위의 기본 복원(열기 전 요소로)을 언제나 막고
 * `DialogTrigger` 로 포커스를 보낸다. Callable 은 `DialogTrigger` 없이 `call()` 로 열리므로 보낼 곳이 없고,
 * 모달 내용이 사라지면서 포커스가 `<body>` 로 떨어진다 — 다음 Tab 이 문서 처음(사이드바)부터 다시 시작한다.
 *
 * 새 객체를 만들지 않고 받은 Callable 의 `call` 만 바꿔 끼워 같은 객체를 돌려준다. Callable 은 그 자체가 Root
 * 컴포넌트라 `<X />` 마운트·`X.Root`·타입이 전부 그 객체에 묶여 있어서다.
 */
export function createCallable<Props = void, Response = void, RootProps = object>(
  component: UserComponent<Props, Response, RootProps>,
  unmountingDelay = 0,
): Callable<Props, Response, RootProps> {
  const callable = createReactCallable(component, unmountingDelay);
  const callReactCallable = callable.call.bind(callable);
  callable.call = (props) => {
    // 메뉴·시트·패널 안 항목에서 열었다면 그 항목은 곧 사라지고, 무엇이 그것을 열었는지 알려 주는
    // 속성도 닫히면 지워진다 — 그래서 돌아갈 후보는 지금 요소로 풀어 둔다.
    const returnTargets = captureReturnTargets();
    const response = callReactCallable(props);
    const restore = () => restoreFocusAfterClose(returnTargets, unmountingDelay);
    void response.then(restore, restore);
    return response;
  };
  return callable;
}

/** 1순위는 지금 포커스된 요소, 2순위는 그 요소를 품은 메뉴·시트·패널을 연 트리거다. */
function captureReturnTargets(): HTMLElement[] {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || active === document.body) return [];

  const opener = findExpandedTrigger(active);
  return opener ? [active, opener] : [active];
}

/**
 * 조상 중 하나를 `aria-expanded="true"` + `aria-controls` 로 가리키는 트리거를 찾는다. Radix 메뉴·시트
 * 트리거와 접었다 펴는 패널 버튼이 이 짝을 단다. 탭 버튼도 `aria-controls` 로 탭 패널을 가리키지만
 * `aria-expanded` 가 없어 걸리지 않는다 — 약관·프롬프트 탭 안에서 연 게시 모달이 탭 버튼으로 튀면 안 된다.
 */
function findExpandedTrigger(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    if (!node.id) continue;
    const trigger = document.querySelector(
      `[aria-expanded="true"][aria-controls~="${CSS.escape(node.id)}"]`,
    );
    if (trigger instanceof HTMLElement) return trigger;
  }
  return null;
}

/**
 * 모달이 완전히 닫힌 뒤, 포커스를 잃은 상태일 때만 후보 중 살아 있는 첫 요소로 옮긴다. 이미 누가 포커스를
 * 옮겼으면(스스로 복원하는 모달, 결과를 받아 입력칸으로 옮기는 호출부, 바로 열린 다음 모달, 라우트 이동 뒤
 * 페이지) 아무것도 하지 않는다 — 이 래퍼는 빠진 기본값을 채울 뿐 호출부를 이기지 않는다.
 *
 * 기다리는 순서는 `react-call` 2.0 과 Radix Dialog 1.1 의 내부 타이밍에 맞춘 것이다: `unmountingDelay` 뒤
 * 모달이 언마운트되고, 포커스 범위가 그다음 타이머에서 닫힘 포커스 이벤트를 내고, 스스로 복원하는 모달은 그
 * 이벤트에서 다시 다음 프레임에 옮긴다. 두 라이브러리를 올리면 이 순서를 다시 확인해야 한다.
 */
function restoreFocusAfterClose(targets: HTMLElement[], unmountingDelay: number) {
  if (targets.length === 0) return;
  setTimeout(() => {
    setTimeout(() => {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (!isFocusLost()) return;
          targets.find(isFocusable)?.focus();
        });
      });
    }, 0);
  }, unmountingDelay);
}

function isFocusLost() {
  const active = document.activeElement;
  return active === null || active === document.body || !active.isConnected;
}

/** 아직 문서에 있고, 열린 다른 모달이 바깥을 가려 둔 영역 안이 아니어야 한다. */
function isFocusable(element: HTMLElement) {
  return element.isConnected && element.closest('[aria-hidden="true"], [inert]') === null;
}
