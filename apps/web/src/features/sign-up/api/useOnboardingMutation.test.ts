import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SocialProvider } from "@/entities/session";

import { postSocialOnboarding } from "./useOnboardingMutation";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("@/shared/api/client", () => ({ apiClient: { post } }));

const PAYLOAD = {
  nickname: "닉",
  birthDate: "2000-01-01",
  termsAgreed: true,
  privacyAgreed: true,
  transferAgreed: true,
};

describe("postSocialOnboarding", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ data: { email: "a@example.com" } });
  });

  it.each<SocialProvider>(["google", "kakao"])("%s 는 자기 제공자의 /auth/onboarding/{provider} 로 보낸다", async (provider) => {
    await postSocialOnboarding({ provider, payload: PAYLOAD });

    expect(post).toHaveBeenCalledWith(`/auth/onboarding/${provider}`, PAYLOAD);
  });

  it("본문에 가입 대기 토큰을 싣지 않는다 — 토큰은 HttpOnly 쿠키로 간다", async () => {
    await postSocialOnboarding({ provider: "kakao", payload: PAYLOAD });

    expect(post.mock.calls[0]?.[1]).not.toHaveProperty("token");
  });

  it("응답 본문을 돌려준다", async () => {
    await expect(postSocialOnboarding({ provider: "google", payload: PAYLOAD })).resolves.toEqual({
      email: "a@example.com",
    });
  });
});
