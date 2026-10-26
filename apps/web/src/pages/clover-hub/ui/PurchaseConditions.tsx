import { Link } from "@tanstack/react-router";

import { IdentityRequiredNotice } from "@/entities/identity";
import { SUPPORT_DESTINATIONS } from "@/shared/config/supportDestinations";

import { PURCHASE_CONDITION_SENTENCES } from "../model/cloverPolicy";
import type { PurchaseSection } from "../model/purchaseSection";
import { HubSection, INLINE_LINK_CLASS } from "./HubSection";

/** 구매 조건 — 결제 직전 판단에 드는 것만 펼쳐 둔다. 상품을 고르기 전에 읽혀야 해 상품보다 앞(좁은 화면에서는 위,
 * 넓은 화면에서는 왼쪽 열)에 둔다. 상품 응답을 아직 못 받았으면(`section` 이 없다) 결제가 켜졌는지 몰라 자격 문장을
 * 싣지 않는다 — 나머지 문장은 응답과 무관해 그대로 읽힌다.
 *
 * 자격 자리는 갈래마다 다르다. 본인인증 전이면 자격 문장 대신 인증하러 가는 길이 있는 안내를, 만 19세 미만이면
 * 잘못한 것이 없으므로 경고 틴트가 아닌 중립 문장을 둔다. 결제가 꺼져 있으면 살 수 없다는 말(상품 아래 줄)이 먼저라
 * 자격을 말하지 않는다. */
export function PurchaseConditions({ section }: { section: PurchaseSection | undefined }) {
  return (
    <HubSection title="구매 조건">
      {section === "identityRequired" && <IdentityRequiredNotice reason="purchase" />}
      <ul className="flex list-disc flex-col gap-2 pl-5 text-sm break-keep text-foreground marker:text-muted-foreground">
        <li>{PURCHASE_CONDITION_SENTENCES.vat}</li>
        {(section === "pending" || section === "guest" || section === "products") && (
          <li>{PURCHASE_CONDITION_SENTENCES.eligibility}</li>
        )}
        {section === "ageRestricted" && <li>{PURCHASE_CONDITION_SENTENCES.ageRestricted}</li>}
        <li>{PURCHASE_CONDITION_SENTENCES.bonusRefund}</li>
      </ul>
      <p className="text-sm break-keep text-foreground">
        자세한 기준은{" "}
        <Link to={SUPPORT_DESTINATIONS["refund-policy"].to} className={INLINE_LINK_CLASS}>
          {SUPPORT_DESTINATIONS["refund-policy"].label}
        </Link>
        에서 볼 수 있어요.
      </p>
    </HubSection>
  );
}
