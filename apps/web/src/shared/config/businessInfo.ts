import { CONTACT_EMAIL, SITE_NAME } from "./site";

/** 통신판매업 신고번호. 간이과세자는 신고가 면제라 지금은 없다(`null`). 일반과세자로 바뀌어 신고하면 번호를 여기
 * 넣는다 — 푸터의 표기와 공정거래위원회 사업자정보 확인 링크가 이 값 하나로 함께 바뀐다. */
const MAIL_ORDER_REPORT_NUMBER: string | null = null;

/**
 * 사이트 푸터에 싣는 운영자 정보(전자상거래법이 통신판매업자에게 요구하는 표시)의 단일 소스. 상호와 이메일은
 * `site.ts`의 상수를 그대로 쓴다 — 여기 따로 적으면 서비스 이름이나 문의 주소를 바꿀 때 한쪽만 바뀐다.
 *
 * 호스팅 제공자는 개인정보처리방침의 처리위탁 표와 같은 회사명을 쓴다. 회사를 바꾸면 그 표와 함께 고친다.
 * 주소는 동까지만 적고 호수는 공개하지 않는다.
 */
export const BUSINESS_INFO = {
  name: SITE_NAME,
  representative: "장호정",
  registrationNumber: "865-12-03163",
  mailOrderReportNumber: MAIL_ORDER_REPORT_NUMBER,
  address: "경상북도 구미시 도봉로 10, 103동",
  phone: "010-9928-3204",
  email: CONTACT_EMAIL,
  hostingProviders: [
    { name: "Google Cloud Korea LLC", role: "서버" },
    { name: "Cloudflare, Inc.", role: "웹 전송" },
  ],
} as const;

export type MailOrderReportDisplay = {
  /** 푸터의 `통신판매업` 항목 값. */
  label: string;
  /** 공정거래위원회 사업자정보 공개 페이지. 신고번호가 없으면 `null`이다 — 신고 면제 사업자는 그 페이지에 정보가
   * 없을 수 있어, 빈 조회 결과로 이어지는 링크를 두지 않는다. */
  verifyUrl: string | null;
};

/** 통신판매업 신고번호 유무로 푸터 표기와 확인 링크를 정한다. 모듈 상수를 직접 읽지 않고 인자로 받는다 — 그래야
 * 번호가 있는 갈래도 테스트할 수 있다. */
export function describeMailOrderReport(
  reportNumber: string | null,
  registrationNumber: string,
): MailOrderReportDisplay {
  if (reportNumber === null) {
    return { label: "신고 면제(간이과세자)", verifyUrl: null };
  }

  return {
    label: reportNumber,
    verifyUrl: `https://www.ftc.go.kr/bizCommPop.do?wrkr_no=${registrationNumber.replaceAll("-", "")}`,
  };
}
