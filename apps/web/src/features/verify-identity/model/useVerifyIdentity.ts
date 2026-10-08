import { useState } from "react";

import { requestPortOneIdentityVerification } from "@/shared/lib/portone/portoneSdk";

import { useCompleteIdentityVerificationMutation } from "../api/useCompleteIdentityVerificationMutation";
import {
  useStartIdentityVerificationMutation,
  type StartIdentityVerificationResponse,
} from "../api/useStartIdentityVerificationMutation";
import {
  IDENTITY_NOT_COMPLETED,
  IDENTITY_REQUEST_FAILED,
  IDENTITY_SDK_UNAVAILABLE,
  toIdentityErrorResult,
  type IdentityResult,
} from "./identityResult";

/** 휴대폰 본인인증: 시작(인증 id 발급) → 포트원 인증창 → 서버 저장. 끝난 모양만 돌려주고 던지지 않는다.
 *
 * 인증창이 페이지를 떠나는 경우(모바일) 돌아올 곳은 마이페이지이고, 거기서 리다이렉트 처리가 저장을 이어받는다.
 * 인증 결과(CI·생년월일)는 브라우저를 거치지 않는다 — 서버가 포트원에 직접 묻는다. */
export function useVerifyIdentity() {
  const startVerification = useStartIdentityVerificationMutation();
  const completeVerification = useCompleteIdentityVerificationMutation();
  // 인증창이 떠 있는 동안도 진행 중이라 두 뮤테이션의 `isPending` 만으로는 가운데가 빈다.
  const [isVerifying, setIsVerifying] = useState(false);

  async function run(): Promise<IdentityResult> {
    let started: StartIdentityVerificationResponse;
    try {
      started = await startVerification.mutateAsync();
    } catch (error) {
      return toIdentityErrorResult(error);
    }

    const outcome = await requestPortOneIdentityVerification({
      storeId: started.storeId,
      channelKey: started.channelKey,
      identityVerificationId: started.identityVerificationId,
      redirectUrl: `${window.location.origin}/mypage`,
    });
    switch (outcome) {
      case "redirecting":
        return { kind: "redirecting" };
      case "notCompleted":
        return IDENTITY_NOT_COMPLETED;
      case "failed":
        return IDENTITY_REQUEST_FAILED;
      case "sdkUnavailable":
        return IDENTITY_SDK_UNAVAILABLE;
      case "succeeded":
        break;
    }

    try {
      await completeVerification.mutateAsync(started.identityVerificationId);
      return { kind: "verified" };
    } catch (error) {
      return toIdentityErrorResult(error);
    }
  }

  async function verify(): Promise<IdentityResult> {
    setIsVerifying(true);
    try {
      return await run();
    } finally {
      setIsVerifying(false);
    }
  }

  return { verify, isVerifying };
}
