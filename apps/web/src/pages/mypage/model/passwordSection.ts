import { SOCIAL_PROVIDER_LABELS, type MeResponse } from "@/entities/session";

/** 마이페이지의 비밀번호 자리에 무엇을 둘지. 비밀번호가 있으면(이메일 가입, 또는 이메일 가입에 구글이 이어진
 * 계정) 변경 폼이고, 소셜로만 가입해 비밀번호가 없으면 폼 대신 어떤 계정으로 들어오고 있는지 알린다 — 바꿀
 * 비밀번호가 없는데 폼을 보여 주면 "현재 비밀번호"를 영원히 맞출 수 없다. 섹션 제목도 함께 바뀐다(폼 없는
 * "비밀번호 변경" 제목이 남지 않게). */
export type PasswordSection =
  | { kind: "change-password"; heading: string }
  | { kind: "social-login"; heading: string; message: string };

export function getPasswordSection(me: Pick<MeResponse, "hasPassword" | "socialProvider">): PasswordSection {
  if (me.hasPassword) return { kind: "change-password", heading: "비밀번호 변경" };
  const accountName = me.socialProvider ? `${SOCIAL_PROVIDER_LABELS[me.socialProvider]} 계정` : "소셜 계정";
  return {
    kind: "social-login",
    heading: "로그인 방법",
    message: `${accountName}으로 로그인하고 있어요. 따로 설정한 비밀번호가 없어 변경할 비밀번호도 없어요.`,
  };
}
