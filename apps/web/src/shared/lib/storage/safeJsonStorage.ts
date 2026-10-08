import type { ZodType } from "zod";

type StringStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** jotai `atomWithStorage` 가 받는 동기 저장소 모양. jotai 가 이 타입을 공개 경로로 내보내지 않아 같은 모양을
 * 여기서 적는다(구조 타입이라 그대로 맞물린다). */
export type SafeJsonStorage<T> = {
  getItem: (key: string, initialValue: T) => T;
  setItem: (key: string, newValue: T) => void;
  removeItem: (key: string) => void;
};

/** 브라우저 저장소. 사생활 모드·차단된 사이트 데이터에서는 `localStorage` 접근 자체가 던지고, 테스트(node)처럼
 * `window` 가 없는 환경에서는 참조가 던지므로 여기서 삼킨다. */
function browserLocalStorage(): StringStorage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/**
 * 편의값(뷰어 설정 등)을 JSON 으로 저장하는 jotai 호환 저장소. jotai 기본 저장소는 읽기·쓰기 예외를 삼키지 않아
 * 저장소가 막힌 브라우저에서 설정 하나를 바꾸다 화면이 죽는다 — 여기서는 읽기·쓰기·지우기 전부를 삼키고, 읽은 값이
 * 깨졌거나 모양이 바뀌었으면(`schema` 실패) 초기값으로 떨어진다. 저장에 실패하면 이 기기에서 다음에 기억하지 못할
 * 뿐이다.
 *
 * `getOnInit` 으로 쓰면 atom 을 만드는 모듈 로드 시점에 `getItem` 이 불리므로, 저장소를 얻는 일도 각 호출 안에서
 * 한다.
 */
export function createSafeJsonStorage<T>(
  schema: ZodType<T>,
  getStorage: () => StringStorage | undefined = browserLocalStorage,
): SafeJsonStorage<T> {
  return {
    getItem(key, initialValue) {
      try {
        const raw = getStorage()?.getItem(key);
        if (raw === null || raw === undefined) return initialValue;
        const parsed = schema.safeParse(JSON.parse(raw));
        return parsed.success ? parsed.data : initialValue;
      } catch {
        return initialValue;
      }
    },
    setItem(key, newValue) {
      try {
        getStorage()?.setItem(key, JSON.stringify(newValue));
      } catch {
        // 저장하지 못하면 다음 방문에 기본값으로 돌아갈 뿐이다.
      }
    },
    removeItem(key) {
      try {
        getStorage()?.removeItem(key);
      } catch {
        // 지우지 못해도 다음 읽기에서 스키마가 걸러 낸다.
      }
    },
  };
}
