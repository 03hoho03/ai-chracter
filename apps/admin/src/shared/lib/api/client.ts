import { z } from "zod";
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

/** FastAPI 에러 봉투. `detail`은 셋 중 하나다 — HTTPException의 string, 422 검증 실패의
 * `[{loc, msg, type}]`, 일부 엔드포인트가 쓰는 구조화 dict(예: 429의 retryAfterSeconds).
 *
 * 단언 대신 스키마로 파싱하는 이유(TS-03): 이건 **서버가 주는 외부 데이터**라 모양을 우리가
 * 보장할 수 없다. 프록시가 끼워 넣은 HTML 에러 페이지나 형태가 바뀐 응답이 오면 단언은 그걸
 * 통과시켜 `detail.loc?.at(-1)`에서 터지지만, 파싱은 `undefined`로 떨어져 아래 폴백이 받는다. */
const validationErrorItemSchema = z.object({
  loc: z.array(z.unknown()).optional(),
  msg: z.string().optional(),
});

export const errorEnvelopeSchema = z.object({
  detail: z
    .union([z.string(), z.array(validationErrorItemSchema), z.record(z.string(), z.unknown())])
    .optional(),
});

/** FastAPI는 에러를 항상 `{"detail": ...}` 하나의 키로 내려준다 — HTTPException은 string,
 * 422 검증 실패는 `ValidationErrorItem[]`, 일부 엔드포인트는 구조화된 dict(예: 429의
 * retryAfterSeconds)를 detail로 쓴다. 셋 다 여기서 ApiError로 정규화한다. */
/**
 * `ApiError` 모양을 그대로 가지면서 `Error`이기도 한 클래스.
 *
 * plain 객체를 reject하면 **스택 트레이스가 없다** — 어느 호출부에서 난 실패인지 콘솔에서
 * 추적할 수 없고, unhandled rejection이 났을 때 브라우저가 위치를 못 찍는다. 필드 구성은
 * `ApiError`와 동일하므로 catch에서 `.status`/`.detail`/`.fields`를 읽는 16곳은 그대로다.
 *
 * `isApiError`는 계속 **구조적으로** 검사한다 — `instanceof`로 바꾸면 번들이 갈리거나
 * 프레임을 넘어온 에러에서 false가 되는데, 여기서 얻을 게 없다.
 *
 * plain 객체와 딱 하나 다른 점: 클래스 필드는 선언만으로 정의되므로 422가 아닐 때도
 * `fields` 키가 `undefined`로 **존재한다**(이전엔 키 자체가 없었다). `fields`를 읽는 코드가
 * 저장소에 없고 `isApiError`도 `status`/`message`만 보므로 무해하지만, 사실이라 적어 둔다.
 */
export class ApiErrorObject extends Error implements ApiError {
  readonly status: number;
  readonly detail: ApiError["detail"];
  readonly fields?: ApiError["fields"];

  constructor(shape: ApiError) {
    super(shape.message);
    this.name = "ApiError";
    this.status = shape.status;
    this.detail = shape.detail;
    this.fields = shape.fields;
  }
}

function normalizeError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0;
  const parsed = errorEnvelopeSchema.safeParse(error.response?.data);
  const detail = parsed.success ? parsed.data.detail : undefined;

  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const item of detail) {
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
    return { status, detail, message: error.message };
  }

  return { status, detail: undefined, message: error.message };
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => Promise.reject(new ApiErrorObject(normalizeError(error))),
);

/** 이 인스턴스의 실패는 위 인터셉터가 전부 ApiError로 정규화해 reject하므로, catch한
 * `unknown`은 단언 대신 이 가드로 좁힌다(fe-typescript TS-03). apps/web의 동형 구현이다. */
export function isApiError(error: unknown): error is ApiError {
  return typeof error === "object" && error !== null && "status" in error && "message" in error;
}
