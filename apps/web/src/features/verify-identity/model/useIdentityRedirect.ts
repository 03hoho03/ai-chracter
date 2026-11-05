import { useEffect, useEffectEvent, useRef } from "react";
import { toast } from "sonner";

import { assertNever } from "@/shared/lib/assertNever";

import { useCompleteIdentityVerificationMutation } from "../api/useCompleteIdentityVerificationMutation";
import { resolveIdentityRedirect, type IdentityRedirectSearch } from "./identityRedirect";
import { IDENTITY_NOT_COMPLETED, IDENTITY_VERIFIED_MESSAGE, toIdentityErrorResult, type IdentityResult } from "./identityResult";

/** 본인인증창이 페이지를 떠났다가(모바일) 마이페이지로 돌아왔을 때 쿼리를 읽어 저장을 이어받고, 끝나면 쿼리를 지운다.
 * 결제 복귀(`features/purchase-clover`의 같은 이름 훅)와 같은 구조다 — 마운트 시 뮤테이션이라 `mutateAsync` + `await`,
 * 같은 복귀를 두 번 처리하지 않게 처리한 키를 ref 로 기억하고, effect 는 키가 바뀔 때만 돈다(렌더마다 새로 만들어지는
 * `redirect` 객체와 콜백은 effect 이벤트로 읽는다). */
export function useIdentityRedirect(search: IdentityRedirectSearch, onHandled: () => void) {
  const { mutateAsync } = useCompleteIdentityVerificationMutation();
  const handledKey = useRef<string | null>(null);
  const redirect = resolveIdentityRedirect(search);
  const key = redirect.kind === "complete" ? `complete:${redirect.identityVerificationId}` : redirect.kind;

  const handleRedirect = useEffectEvent(() => {
    if (redirect.kind === "none" || handledKey.current === key) return;
    handledKey.current = key;

    void (async () => {
      if (redirect.kind === "notCompleted") {
        announceIdentityResult(IDENTITY_NOT_COMPLETED);
      } else {
        try {
          await mutateAsync(redirect.identityVerificationId);
          announceIdentityResult({ kind: "verified" });
        } catch (error) {
          announceIdentityResult(toIdentityErrorResult(error));
        }
      }
      onHandled();
    })();
  });

  useEffect(() => {
    handleRedirect();
  }, [key]);
}

function announceIdentityResult(result: IdentityResult) {
  switch (result.kind) {
    case "verified":
      toast.success(IDENTITY_VERIFIED_MESSAGE);
      return;
    case "notice":
      if (result.tone === "error") toast.error(result.message);
      else toast(result.message);
      return;
    // 복귀 처리에서는 인증창을 다시 띄우지 않아 이 결과가 오지 않는다. 와도 알릴 것이 없다.
    case "redirecting":
      return;
    default:
      assertNever(result);
  }
}
