/**
 * BGAS — Henry Hub natural gas spot.
 *
 * Live NG=F front-month snapshot (last/change headline cards) + daily
 * history sparkline + honest source pills. See commodity-spot.tsx for the
 * shared body; the backend is engine/functions/commodity/_funcs.py
 * (BGASFunction).
 */
import { CommoditySpotPane } from "./commodity-spot";

export function BGASPane(props: { code: string; symbol?: string }) {
  return <CommoditySpotPane {...props} title="Natural Gas Spot" />;
}
