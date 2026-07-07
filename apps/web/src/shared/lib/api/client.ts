import type { ApiError } from "@ai-character-chat/api-types";
import axios, { type AxiosError } from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** 401 응답 발생 시 호출될 핸들러를 등록한다. 실제 로그인 라우트 연결(US-011/019)은 이후 단계에서 이 훅을 통해 구현한다. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

function normalizeError(error: AxiosError): ApiError {
  const data = error.response?.data as
    | { code?: string; message?: string; fields?: Record<string, string> }
    | undefined;

  return {
    status: error.response?.status ?? 0,
    code: data?.code ?? "UNKNOWN_ERROR",
    message: data?.message ?? error.message,
    fields: data?.fields,
  };
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const normalized = normalizeError(error);

    if (normalized.status === 401) {
      unauthorizedHandler?.();
    }

    return Promise.reject(normalized);
  },
);
