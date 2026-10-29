import type { ISeriesPrimitive, SeriesAttachedParameter, IPrimitivePaneRenderer, Logical } from 'lightweight-charts';
import type { Scenario } from './types';

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];

/** A time-bounded zone, rather than an infinite horizontal price line. */
export class ScenarioOverlay implements ISeriesPrimitive {
  private attachedTo?: SeriesAttachedParameter;
  private zones: Scenario[] = [];
  private selected = false;
  constructor(private open: number, private close: number) {}
  attached(params: SeriesAttachedParameter) { this.attachedTo = params; }
  detached() { this.attachedTo = undefined; }
  setScenarios(zones: Scenario[], selected: boolean) {
    this.zones = zones; this.selected = selected; this.attachedTo?.requestUpdate();
  }
  paneViews() { return [{ zOrder: () => 'bottom' as const, renderer: () => ({ draw: (target: Target) => this.draw(target) }) }]; }
  autoscaleInfo() {
    if (!this.selected) return null;
    const prices = this.zones.flatMap(s => [s.zone.low, s.zone.high, s.target, ...s.price_invalidations.map(p => p.price)])
      .filter((p): p is number => typeof p === 'number' && Number.isFinite(p));
    return prices.length ? { priceRange: { minValue: Math.min(...prices), maxValue: Math.max(...prices) } } : null;
  }
  private x(time: number) {
    if (!this.attachedTo) return null;
    const index = (Math.max(this.open, Math.min(time, this.close)) - this.open) / 180;
    const left = Math.floor(index);
    const scale = this.attachedTo.chart.timeScale();
    // The chart accepts integer indexes. Interpolate so events between candles
    // keep their recorded times instead of snapping to the chart's left edge.
    const x1 = scale.logicalToCoordinate(left as Logical);
    const x2 = scale.logicalToCoordinate((left + 1) as Logical);
    return x1 == null || x2 == null ? null : x1 + (x2 - x1) * (index - left);
  }
  private draw(target: Target) {
    if (!this.attachedTo) return;
    target.useMediaCoordinateSpace(({ context: ctx }) => {
      for (const scenario of this.zones) this.drawScenario(ctx, scenario);
    });
  }
  private drawScenario(ctx: CanvasRenderingContext2D, s: Scenario) {
    const x1 = this.x(s.start), x2 = this.x(s.end);
    const y1 = s.zone.high == null ? null : this.attachedTo!.series.priceToCoordinate(s.zone.high);
    const y2 = s.zone.low == null ? null : this.attachedTo!.series.priceToCoordinate(s.zone.low);
    if (x1 == null || x2 == null || x2 <= x1) return;
    const color = s.direction === 'call' ? '#45c9a0' : '#ed9b77';
    ctx.save();
    if (y1 != null && y2 != null) {
      ctx.fillStyle = s.direction === 'call' ? 'rgba(69,201,160,.08)' : 'rgba(237,155,119,.08)';
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.strokeStyle = color; ctx.globalAlpha = this.selected ? .6 : .25;
      ctx.setLineDash([3, 4]); ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      if (this.selected) {
        ctx.globalAlpha = 1; ctx.fillStyle = color; ctx.font = '10px system-ui';
        ctx.fillText(`${s.direction.toUpperCase()} · TRIGGER ZONE`, Math.max(8, x1 + 6), y1 - 7);
      }
    }
    if (this.selected) {
      if (s.target != null) this.level(ctx, x1, x2, s.target, '#6fbdff', `TARGET ${s.target.toFixed(2)}`);
      for (const level of s.price_invalidations) this.level(ctx, x1, x2, level.price, '#ee788b', `INVALIDATION ${level.price.toFixed(2)}`);
    }
    ctx.restore();
  }
  private level(ctx: CanvasRenderingContext2D, x1: number, x2: number, price: number, color: string, label: string) {
    const y = this.attachedTo!.series.priceToCoordinate(price);
    if (y == null) return;
    ctx.globalAlpha = .85; ctx.strokeStyle = color; ctx.setLineDash([5, 5]);
    ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
    ctx.fillStyle = color; ctx.font = '10px system-ui'; ctx.fillText(label, Math.max(8, x1 + 6), y - 6);
  }
}
