import { apiClient } from "../../../shared/lib/api/client";

/** 라우트 loader에서 호출된다 — 토큰이 만료/무효(400)면 false, 유효하면(200) true. */
export async function validatePasswordResetToken(token: string): Promise<boolean> {
  try {
    await apiClient.get("/auth/password-reset/validate", { params: { token } });
    return true;
  } catch {
    return false;
  }
}
