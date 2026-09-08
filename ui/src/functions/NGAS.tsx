/**
 * NGAS — natural gas spot (alias of BGAS on the backend).
 *
 * Same live NG=F snapshot shape as BGAS; kept as its own pane file so the
 * registry can map the NGAS code natively. See commodity-spot.tsx for the
 * shared body; the backend is engine/functions/commodity/_funcs.py
 * (NGASFunction extends BGASFunction).
 */
import { CommoditySpotPane } from "./commodity-spot";

export function NGASPane(props: { code: string; symbol?: string }) {
  return <CommoditySpotPane {...props} title="Natural Gas" />;
}
