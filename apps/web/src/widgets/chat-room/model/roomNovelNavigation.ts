/** `소설로 보기` 응답이 왔을 때 사용자가 아직 그 방 화면에 있는지. 패널이 닫힌 채 응답을 기다리는 동안 다른 방이나
 * 홈으로 옮겼다면 소설 화면으로 끌고 가지 않는다(소설 캐시는 이미 채워져 있어 나중에 열 때 바로 그려진다). */
export function isStillInRoom(pathname: string, roomId: string): boolean {
  return pathname === `/chat/${roomId}`;
}
