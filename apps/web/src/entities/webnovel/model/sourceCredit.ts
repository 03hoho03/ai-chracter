import type { WebnovelListItem, WebnovelSource } from "../api/useWebnovelListQuery";
import type { WebnovelDetailResponse } from "../api/useWebnovelQuery";

/** 노벨 화면에서 탈퇴한 원작자·게시자를 가리키는 말. 괄호 없이 쓴다 — 이름 자리에 그대로 들어가 "원작자 · 탈퇴한 사용자"
 * 처럼 읽힌다. */
export const WITHDRAWN_USER_LABEL = "탈퇴한 사용자";

/** "원작자 · …" 줄에 무엇을 쓸지. 줄이 없으면 `undefined`. */
export type CreatorCredit = { kind: "nickname"; nickname: string } | { kind: "withdrawn" } | undefined;

/** 노벨 작품 정보에서 원작자를 어떻게 표기할지.
 *
 * - `creator`: "원작자 · …" 줄. 원작자가 게시자 자신이면 게시자 줄이 이미 그 사람을 말하므로 줄을 따로 내지 않는다.
 *   원작자가 탈퇴했으면 이름 대신 "탈퇴한 사용자"다. 원작 행이 없거나 닉네임이 비어 있으면 줄을 통째로 생략한다.
 * - `publisherIsCreator`: 게시자가 원작자 본인이라 게시자 줄 끝에 "· 원작자"를 붙인다. 두 사람이 같은데 탈퇴했으면
 *   게시자도 탈퇴한 것이라 게시자 줄이 "탈퇴한 사용자 · 원작자"가 된다.
 * - `isUnofficial`: 원작자가 아닌 사람이 공개한 소설이라 "또나 채팅 기반 파생 소설" 배지를 붙인다.
 *
 * 옛 서버가 칸 없이 응답해도(`undefined`) 글자로 새지 않게 값이 있을 때만 그리고, 참·거짓은 엄격 비교로 읽는다 — 근거
 * 없이 공식으로도, 비공식으로도, 탈퇴로도 표시하지 않는다. */
export function toSourceCredit(source: Pick<WebnovelSource, "creatorNickname" | "unofficial" | "creatorWithdrawn">): {
  creator: CreatorCredit;
  publisherIsCreator: boolean;
  isUnofficial: boolean;
} {
  const creator = toCreatorCredit(source);
  const publisherIsCreator = source.unofficial === false && creator !== undefined;
  return {
    creator: publisherIsCreator ? undefined : creator,
    publisherIsCreator,
    isUnofficial: source.unofficial === true,
  };
}

function toCreatorCredit(source: Pick<WebnovelSource, "creatorNickname" | "creatorWithdrawn">): CreatorCredit {
  if (source.creatorWithdrawn === true) return { kind: "withdrawn" };
  if (source.creatorNickname) return { kind: "nickname", nickname: source.creatorNickname };
  return undefined;
}

/** 작품 정보의 "게시자 · …" 줄. 탈퇴한 게시자는 서버가 회원 id·닉네임을 비우므로 글자만 쓰고 프로필로 걸지 않는다. 둘 중
 * 하나라도 비면(탈퇴가 아닌데) 걸 곳이 없어 줄을 내지 않는다. */
export type PublisherCredit = { kind: "profile"; userId: string; nickname: string } | { kind: "withdrawn" } | undefined;

export function toPublisherCredit(
  novel: Pick<WebnovelDetailResponse, "publisherUserId" | "publisherNickname" | "publisherWithdrawn">,
): PublisherCredit {
  if (novel.publisherWithdrawn === true) return { kind: "withdrawn" };
  if (novel.publisherNickname === null || novel.publisherUserId === null) return undefined;
  return { kind: "profile", userId: novel.publisherUserId, nickname: novel.publisherNickname };
}

/** 목록·소장 목록 행의 게시자 이름. 탈퇴했으면 "탈퇴한 사용자", 이름이 없으면 `null`(그 자리를 비운다). */
export function toPublisherName(item: Pick<WebnovelListItem, "publisherNickname" | "publisherWithdrawn">): string | null {
  return item.publisherWithdrawn === true ? WITHDRAWN_USER_LABEL : item.publisherNickname;
}
