import { createContext, useCallback, useContext, useState, useSyncExternalStore } from "react";

/**
 * 빌더 화면 하나가 쥐는 화면 상태 — 반복 항목의 열림 여부와, 여러 탭이 함께 보는 선택 값(스탯·엔딩 탭의 고른
 * 시작설정 같은 것). 폼 값이 아니라서 자동저장·검증과 무관하고 페이지를 떠나면 사라진다.
 *
 * 셸이 하나를 만들어 컨텍스트로 내린다. 탭 본문은 탭을 바꿀 때 언마운트되므로 탭 안 state 로는 탭을 오가며 기억할 수
 * 없다. 셸 state 대신 외부 저장소 + `useSyncExternalStore` 로 둔 이유는 둘이다. 항목 하나를 펼칠 때 셸과 미리보기가
 * 다시 그려지지 않고 그 키를 읽는 항목만 다시 그려진다. 그리고 이 저장소의 변경은 언제나 동기 우선순위로 커밋되므로,
 * 발행 실패 때 오류 항목을 연 직후 다음 프레임에 주는 포커스보다 펼침이 먼저 화면에 들어간다.
 */
export type BuilderUiState = {
  subscribe: (listener: () => void) => () => void;
  isOpen: (key: string) => boolean;
  toggle: (key: string) => void;
  /** 이미 열린 키는 그대로 둔다. 발행 실패 때 오류 항목을 열 때와 '추가'로 만든 항목을 열 때 쓴다. */
  open: (keys: Iterable<string>) => void;
  close: (key: string) => void;
  /**
   * 인덱스로 키를 만든 목록(값 id 가 없는 배열)에서 `index` 항목을 지운 뒤 부른다. 그 항목의 열림을 지우고 뒤 항목들의
   * 열림을 한 칸씩 당긴다 — 안 당기면 지운 자리에 들어온 다음 항목이 앞 항목의 열림을 물려받는다.
   */
  removeIndexKey: (list: string, index: number) => void;
  getSelection: (name: string) => string | undefined;
  select: (name: string, value: string | undefined) => void;
};

/** 값 id 로 만든 열림 키. 목록 이름을 앞에 붙여 서로 다른 목록의 id 가 섞이지 않게 한다. 부모 배열의 인덱스는 넣지 않는다
 * — 시작설정 순서를 바꿔도 그 아래 스탯·엔딩의 열림이 유지돼야 하고, 값 id 는 그 자체로 유일하다. */
export function itemOpenKey(list: string, id: string): string {
  return `${list}:${id}`;
}

/** 값 id 가 없는 배열(전개 예시)의 열림 키. 지울 때는 `removeIndexKey` 로 뒤 항목을 당겨야 한다. */
export function indexOpenKey(list: string, index: number): string {
  return `${list}#${index}`;
}

export function createBuilderUiState(): BuilderUiState {
  let openKeys = new Set<string>();
  const selections = new Map<string, string>();
  const listeners = new Set<() => void>();

  function emit() {
    for (const listener of listeners) listener();
  }

  function setOpenKeys(next: Set<string>) {
    openKeys = next;
    emit();
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    isOpen: (key) => openKeys.has(key),
    toggle(key) {
      const next = new Set(openKeys);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      setOpenKeys(next);
    },
    open(keys) {
      const added = [...keys].filter((key) => !openKeys.has(key));
      if (added.length === 0) return;
      setOpenKeys(new Set([...openKeys, ...added]));
    },
    close(key) {
      if (!openKeys.has(key)) return;
      const next = new Set(openKeys);
      next.delete(key);
      setOpenKeys(next);
    },
    removeIndexKey(list, index) {
      const prefix = `${list}#`;
      const next = new Set<string>();
      for (const key of openKeys) {
        if (!key.startsWith(prefix)) {
          next.add(key);
          continue;
        }
        const keyIndex = Number(key.slice(prefix.length));
        if (keyIndex < index) next.add(key);
        else if (keyIndex > index) next.add(indexOpenKey(list, keyIndex - 1));
      }
      setOpenKeys(next);
    },
    getSelection: (name) => selections.get(name),
    select(name, value) {
      if (selections.get(name) === value) return;
      if (value === undefined) selections.delete(name);
      else selections.set(name, value);
      emit();
    },
  };
}

/** Provider 밖(셸 없이 탭만 그리는 렌더 테스트 등)에서는 전부 접힘·선택 없음이고 바꾸는 동작은 아무 일도 하지 않는다. */
const INERT_UI_STATE: BuilderUiState = {
  subscribe: () => () => {},
  isOpen: () => false,
  toggle: () => {},
  open: () => {},
  close: () => {},
  removeIndexKey: () => {},
  getSelection: () => undefined,
  select: () => {},
};

/** 셸이 `useCreateBuilderUiState()` 로 만든 저장소를 `value` 로 내린다. */
export const BuilderUiStateContext = createContext<BuilderUiState>(INERT_UI_STATE);

/** 셸이 한 번 부른다 — 셸이 마운트돼 있는 동안 같은 저장소를 돌려준다. 발행 실패 경로에서 바로 쓸 수 있게 반환값을 쥐고
 * 컨텍스트로도 내린다. */
export function useCreateBuilderUiState(): BuilderUiState {
  const [state] = useState(createBuilderUiState);
  return state;
}

/** 구독 없이 동작(열기·닫기·선택)만 쓸 때. 항목을 추가·삭제하는 핸들러가 쓴다. */
export function useBuilderUiState(): BuilderUiState {
  return useContext(BuilderUiStateContext);
}

/** 이 키의 열림 여부를 구독한다. 다른 키가 바뀌면 값이 그대로라 다시 그리지 않는다. */
export function useIsItemOpen(key: string): boolean {
  const state = useContext(BuilderUiStateContext);
  const getSnapshot = useCallback(() => state.isOpen(key), [state, key]);
  return useSyncExternalStore(state.subscribe, getSnapshot, getSnapshot);
}

/** 이름 붙은 선택 값을 구독한다(예: 스탯·엔딩 탭이 함께 보는 고른 시작설정 id). */
export function useBuilderSelection(name: string): [string | undefined, (value: string | undefined) => void] {
  const state = useContext(BuilderUiStateContext);
  const getSnapshot = useCallback(() => state.getSelection(name), [state, name]);
  const value = useSyncExternalStore(state.subscribe, getSnapshot, getSnapshot);
  const setValue = useCallback((next: string | undefined) => state.select(name, next), [state, name]);
  return [value, setValue];
}
