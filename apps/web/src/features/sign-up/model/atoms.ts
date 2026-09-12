import { atom } from "jotai";

export type SignUpStep = "basicInfo" | "emailVerify" | "guardianConsent";

export const signUpStepAtom = atom<SignUpStep>("basicInfo");
