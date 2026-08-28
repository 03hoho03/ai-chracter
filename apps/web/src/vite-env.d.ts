/// <reference types="vite/client" />

/**
 * Vite의 `ImportMetaEnv`에는 `[key: string]: any` 인덱스 시그니처가 있어서, 선언하지 않은 커스텀
 * 키는 전부 `any`로 읽힌다. 그 `any`가 `apiBaseUrl`을 타고 `client.ts`와 `googleLoginUrl.ts`까지
 * 번져 `no-unsafe-*` 위반을 만들고 있었다(도입 시점 9건).
 *
 * 인터페이스 선언 병합이라 **여기 적은 키만** 좁혀진다 — 새 `VITE_*`를 쓰기 시작하면 여기에도
 * 추가할 것. 안 하면 조용히 `any`로 돌아간다.
 *
 * 옵셔널인 이유: `.env.local`이 없는 환경(CI·fresh clone)에서 실제로 `undefined`이고,
 * `client.ts`가 `?? "http://localhost:8000"`으로 그 경우를 받는다.
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}
