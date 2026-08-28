import type { ApiError } from "@ai-character-chat/api-types";
import axios, { type AxiosError } from "axios";

export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const baseURL = apiBaseUrl;

/**
 * 인증은 httpOnly 세션 쿠키로 처리되어 브라우저가 요청마다 자동으로 쿠키를
 * 첨부하므로(techspec-overview.md §6.1), 별도의 요청 인터셉터에서 토큰을
 * 붙일 필요는 없다 — `withCredentials: true`만으로 인증 로직이 이 인스턴스에 격리된다.
 */
export const apiClient = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

type ValidationErrorItem = {
  loc?: unknown[];
  msg?: string;
}

/** FastAPI는 에러를 항상 `{"detail": ...}` 하나의 키로 내려준다 — HTTPException은 string,
 * 422 검증 실패는 `ValidationErrorItem[]`, 일부 엔드포인트는 구조화된 dict(예: 429의
 * retryAfterSeconds)를 detail로 쓴다. 셋 다 여기서 ApiError로 정규화한다. */
function normalizeError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0;
  const data = error.response?.data as { detail?: unknown } | undefined;
  const detail = data?.detail;

  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const item of detail as ValidationErrorItem[]) {
      const field = item.loc?.at(-1);
      if (typeof field === "string" && typeof item.msg === "string") {
        fields[field] = item.msg;
      }
    }
    return { status, detail: undefined, fields, message: Object.values(fields)[0] ?? error.message };
  }

  if (typeof detail === "string") {
    return { status, detail, message: detail };
  }

  if (detail && typeof detail === "object") {
    return { status, detail: detail as Record<string, unknown>, message: error.message };
  }

  return { status, detail: undefined, message: error.message };
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => Promise.reject(normalizeError(error)),
);
