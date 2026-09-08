/**
 * BOIL — WTI / Brent oil spot + spread.
 *
 * Live CL=F + BZ=F front-month snapshots with the computed Brent−WTI
 * spread card and a daily history sparkline. See commodity-spot.tsx for
 * the shared body; the backend is engine/functions/commodity/_funcs.py
 * (BOILFunction).
 */
import { CommoditySpotPane } from "./commodity-spot";

export function BOILPane(props: { code: string; symbol?: string }) {
  return <CommoditySpotPane {...props} title="Oil Spot" />;
}
