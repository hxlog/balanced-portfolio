import { redirect } from "next/navigation";

/** 旧路径永久跳转到 /otc-derivatives-pricing */
export default function OtcPricingRedirect() {
  redirect("/otc-derivatives-pricing");
}
