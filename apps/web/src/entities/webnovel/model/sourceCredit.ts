import type { WebnovelSource } from "../api/useWebnovelListQuery";

/** 노벨 작품 정보에서 원작자를 어떻게 표기할지.
 *
 * - `creatorNickname`: "원작자 · 닉네임" 줄에 쓸 이름. 원작자가 게시자 자신이면 게시자 줄이 이미 그 사람을 말하므로 줄을
 *   따로 내지 않는다(`undefined`). 원작자가 탈퇴했거나 원작 행이 없어 이름이 비면 줄을 통째로 생략한다.
 * - `publisherIsCreator`: 게시자가 원작자 본인이라 게시자 줄 끝에 "· 원작자"를 붙인다.
 * - `isUnofficial`: 원작자가 아닌 사람이 공개한 소설이라 "비공식 2차 창작" 배지를 붙인다.
 *
 * 옛 서버가 두 칸 없이 응답해도(`undefined`) 글자로 새지 않게 값이 있을 때만 그리고, 참·거짓은 엄격 비교로 읽는다 — 근거
 * 없이 공식으로도, 비공식으로도 표시하지 않는다. */
export function toSourceCredit(source: Pick<WebnovelSource, "creatorNickname" | "unofficial">): {
  creatorNickname: string | undefined;
  publisherIsCreator: boolean;
  isUnofficial: boolean;
} {
  const nickname = source.creatorNickname ? source.creatorNickname : undefined;
  const publisherIsCreator = source.unofficial === false && nickname !== undefined;
  return {
    creatorNickname: publisherIsCreator ? undefined : nickname,
    publisherIsCreator,
    isUnofficial: source.unofficial === true,
  };
}
