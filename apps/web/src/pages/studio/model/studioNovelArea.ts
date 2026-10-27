import { hasEnabledFeature, type EnabledFeature } from "@/entities/session";

/**
 * 스튜디오의 소설 영역(소설 유형 칩·"심사 중" 상태 항목·소설 행)을 보일지. 소설화가 열린 계정에만 보인다 — 닫힌 계정에
 * 잠김 안내나 자격 문구를 대신 그리지 않고 영역 자체가 없다. 서버 통합 목록도 같은 판정으로 소설을 빼므로 화면과 목록이
 * 갈리는 때는 탭을 띄워 둔 사이 허용이 회수된 경우뿐이고, 그때는 소설 칩이 빈 목록을 보일 뿐 오류는 없다.
 *
 * 입력은 세션 조회(`useSessionQuery`)의 값이다. 라우트 컨텍스트의 세션은 진입 때 찍은 사본이라 세션을 다시 받아도
 * 따라오지 않는다. 아직 못 읽었거나 허용 기능 필드가 없는 옛 `/me` 응답이면 닫힌 것으로 본다.
 */
export function isStudioNovelAreaVisible(enabledFeatures: readonly EnabledFeature[] | undefined): boolean {
  return hasEnabledFeature(enabledFeatures, "novelize");
}
