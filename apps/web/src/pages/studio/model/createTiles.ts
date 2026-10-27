export type CreateTileKey = "character" | "story" | "novel" | "image";

/** 새로 만들기 칸의 순서. 내 채팅으로 소설 칸은 소설화가 열린 계정에만 있다 — 닫힌 계정에 잠김 칸을 대신 두지 않는다.
 * 만드는 것(캐릭터·스토리·소설) 다음에 그것을 꾸미는 그림이 온다. */
export function toCreateTileKeys(isNovelAreaVisible: boolean): CreateTileKey[] {
  return isNovelAreaVisible ? ["character", "story", "novel", "image"] : ["character", "story", "image"];
}
