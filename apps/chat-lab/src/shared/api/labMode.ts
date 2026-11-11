import { staticBundleState, type StaticBundleState } from "./staticBundle";

/**
 * 이 화면이 데이터를 어디서 읽는가.
 * - `local`: 같은 컴퓨터의 측정 서버.
 * - `static`: 정적 HTML 에 실린 런 하나. 어느 서버에도 닿지 않는다.
 * - `hosted`: 같은 출처의 호스팅 서비스에 올라온 판. 측정 서버에는 닿지 않는다.
 */
export type LabMode = "local" | "static" | "hosted";

/** 순수 판정 — 시험이 문서·빌드 상수 없이 갈래를 본다. */
export function pickLabMode(input: { isHostedBuild: boolean; staticKind: StaticBundleState["kind"] }): LabMode {
  // 정적 묶음이 실린 문서면 빌드와 상관없이 정적이다 — 파일로 연 화면은 어느 서버에도 닿지 않고, 호스팅 빌드 결과로 내보낸
  // 정적 HTML 도 정적으로 돌아야 한다. 읽지 못한 묶음도 정적이다(서버로 넘어가면 파일이 깨졌다는 까닭 대신 연결 실패가 뜬다).
  if (input.staticKind !== "absent") return "static";
  return input.isHostedBuild ? "hosted" : "local";
}

/**
 * 지금 화면의 모드. 빌드 상수를 읽는 곳은 여기 하나다. 부를 때마다 상수를 다시 읽는다 — 모듈 변수에 굳히면 시험이 모듈을 다시
 * 읽지 않고는 갈래를 바꾸지 못한다(빌드 결과에서는 상수가 글자 그대로 박혀 같은 값이다).
 */
export function labMode(): LabMode {
  return pickLabMode({
    isHostedBuild: import.meta.env.VITE_CHAT_LAB_MODE === "hosted",
    staticKind: staticBundleState().kind,
  });
}

/** 페이지 출처에서 막는 판정이 보는 두 칸(`window.location` 의 일부). */
export type PageLocation = { protocol: string; hostname: string };

/** 측정 서버가 받는 출처의 호스트 — 측정 서버 CORS 가 루프백 출처만 받는다. 브라우저는 IPv6 호스트를 대괄호째 준다. */
const LOOPBACK_HOSTS: ReadonlySet<string> = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** 지금 페이지의 출처. 문서 밖(Node 에서 도는 시험)에서는 없다. */
export function currentPageLocation(): PageLocation | undefined {
  return typeof location === "undefined" ? undefined : location;
}

/**
 * 로컬 빌드가 측정 서버를 불러도 되는 출처인가. http(s) 출처면 루프백이어야 한다 — 로컬 빌드가 실수로 서비스에 실리면(정적 내보내기가
 * 같은 빌드 폴더를 덮었거나 빌드 상수를 빠뜨림) 팀원 브라우저가 자기 컴퓨터의 127.0.0.1 을 부르고 "측정 서버를 띄운다" 는 틀린
 * 안내가 뜬다. 파일로 연 화면(`file://`)은 지금처럼 둔다.
 */
export function isMeasurementPage(page: PageLocation | undefined): boolean {
  if (page === undefined) return true;
  if (page.protocol !== "http:" && page.protocol !== "https:") return true;
  return LOOPBACK_HOSTS.has(page.hostname);
}

/** 루프백 밖 출처에서 연 로컬 빌드가 측정 서버에 요청하려 했다. 화면은 이것을 보고 호스팅 빌드로 다시 만들라고 안내한다. */
export class LocalBuildElsewhereError extends Error {
  readonly hostname: string;

  constructor(hostname: string) {
    super(
      `측정 서버를 읽는 로컬 빌드가 ${hostname} 에서 열렸다 — 보는 사람 컴퓨터의 측정 서버를 부르게 되므로 요청을 보내지 않았다. 호스팅 빌드(VITE_CHAT_LAB_MODE=hosted)로 다시 만든다.`,
    );
    this.name = "LocalBuildElsewhereError";
    this.hostname = hostname;
  }
}
