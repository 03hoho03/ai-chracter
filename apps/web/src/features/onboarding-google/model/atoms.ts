import { atom } from "jotai";

export type OnboardingGoogleStep = "basicInfo" | "guardianConsent";

export const onboardingGoogleStepAtom = atom<OnboardingGoogleStep>("basicInfo");
