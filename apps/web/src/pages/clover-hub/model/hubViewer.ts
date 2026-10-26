import type { MeResponse } from "@/entities/session";

/** 이 화면을 보는 사람. 허브는 로그인 없이 열리므로 세션을 세 갈래로 가른다 — 아직 묻는 중(대기), 로그인하지 않음
 * (비로그인), 로그인함(회원). 대기와 비로그인을 한데 접으면 로그인한 사람에게도 첫 프레임에 로그인 안내나 "0"이 그려진다.
 *
 * 세션 응답이 있으면 회원이다. 없고 아직 묻는 중이면 대기, 물었는데 없으면(401·실패) 비로그인이다 — 세션을 잃은 401 은
 * 전역 처리가 옛 값을 비우므로 그때도 비로그인으로 떨어진다. */
export type HubViewer = { kind: "pending" } | { kind: "guest" } | { kind: "member"; me: MeResponse };

export function toHubViewer(session: { data: MeResponse | undefined; isPending: boolean }): HubViewer {
  if (session.data) return { kind: "member", me: session.data };
  return session.isPending ? { kind: "pending" } : { kind: "guest" };
}
