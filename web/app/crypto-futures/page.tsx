import { redirect } from "next/navigation";

/** v3：加密合约看板并入 /crypto（合约监控在上、相关性在下）。 */
export default function CryptoFuturesLegacyPage() {
  redirect("/crypto");
}
