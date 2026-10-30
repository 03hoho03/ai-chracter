/// <reference types="vite/client" />

/**
 * Vite 의 `ImportMetaEnv` 에는 `[key: string]: any` 인덱스 시그니처가 있어, 선언하지 않은 키는 `any` 로 읽힌다.
 * 인터페이스 선언 병합이라 여기 적은 키만 좁혀진다 — 새 `VITE_*` 를 쓰기 시작하면 여기에도 적는다.
 *
 * 옵셔널인 이유: 대부분의 실행(CI·새로 받은 체크아웃)에는 이 값이 없고, `shared/api/client.ts` 가 기본 주소로 받는다.
 */
interface ImportMetaEnv {
  /** 측정 서버 주소를 기본값(127.0.0.1:8791)이 아닌 곳으로 돌릴 때. */
  readonly VITE_CHAT_LAB_API?: string;
}
