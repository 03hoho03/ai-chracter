import type { AutosaveStatus } from "./autosaveStatus";

/** 저장 상태 글자 한 줄이 그릴 것. */
export type SaveStatusView = {
  text: string;
  /** [내용 복사]를 곁에 둘지 — 마지막 편집이 서버에 없을 수 있고, 그 상태가 저절로 풀린다고 장담할 수 없을 때다. */
  offersCopy: boolean;
  /** 실패 색으로 그릴지. */
  isFailure: boolean;
};

/**
 * 저장 시각(`오후 11:42`)을 보는 사람의 로컬 시각으로 적는다.
 *
 * `Intl.DateTimeFormat("ko-KR")` 이 아니라 손으로 조립하는 이유: 로캘을 `ko-KR` 로 줘도 오전·오후 표기가 런타임의 ICU
 * 데이터에 따라 갈린다 — 이 저장소 CI 의 Node 20(ICU 78.2)에서는 `PM 11:42` 로 나왔다. 실행 환경과 무관하게 같은 글자를 쓴다.
 */
function formatSavedTime(epochMs: number): string {
  const date = new Date(epochMs);
  const hours = date.getHours();
  const period = hours < 12 ? "오전" : "오후";
  const hour12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${period} ${hour12}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/**
 * 저장 상태와 연결 상태를 글자 한 줄로 바꾼다. 순수 함수.
 *
 * 연결 상태를 먼저 본다. 오프라인이면 저장 요청이 멈춰 저장 상태가 "저장 중"에 남으므로, 저장 상태로만 그리면 끝없는 "저장 중"이
 * 된다. 오프라인과 실패에는 복사를 낸다 — 연결이 길게 끊기거나 저장이 계속 실패하면 편집이 이 탭 메모리에만 있다.
 *
 * 아직 저장한 적 없는 화면(`idle`)은 상태 대신 저장 계약을 말한다. 작가가 "자동저장"이라는 말을 처음 만나는 자리가 실패 알림이
 * 되지 않게 한다.
 */
export function saveStatusView(status: AutosaveStatus, isOnline: boolean, lastSavedAt: number | undefined): SaveStatusView {
  if (!isOnline) return { text: "연결 끊김 · 연결되면 저장돼요", offersCopy: true, isFailure: false };
  switch (status) {
    case "idle":
      return { text: "변경사항은 자동으로 저장돼요.", offersCopy: false, isFailure: false };
    case "pending":
      return { text: "저장 대기 중", offersCopy: false, isFailure: false };
    case "saving":
      return { text: "저장 중", offersCopy: false, isFailure: false };
    case "saved":
      return {
        text: lastSavedAt === undefined ? "저장됨" : `저장됨 · ${formatSavedTime(lastSavedAt)}`,
        offersCopy: false,
        isFailure: false,
      };
    case "failed":
      return { text: "저장 실패", offersCopy: true, isFailure: true };
  }
}
