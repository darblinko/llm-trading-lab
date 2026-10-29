// Series primitive that shades the selected scenario's trigger zone between two
// bar times and two prices, drawn beneath the candles.

class ZoneRenderer {
  constructor(geometry) {
    this._geometry = geometry;
  }

  draw(target) {
    const box = this._geometry;
    if (!box) return;
    target.useMediaCoordinateSpace(({ context }) => {
      context.fillStyle = box.fill;
      context.fillRect(box.left, box.top, box.width, box.height);
      context.strokeStyle = box.stroke;
      context.lineWidth = 1;
      context.setLineDash([4, 3]);
      context.beginPath();
      context.moveTo(box.left, box.top + 0.5);
      context.lineTo(box.left + box.width, box.top + 0.5);
      context.moveTo(box.left, box.top + box.height - 0.5);
      context.lineTo(box.left + box.width, box.top + box.height - 0.5);
      context.stroke();
      context.setLineDash([]);
    });
  }
}

class ZonePaneView {
  constructor(source) {
    this._source = source;
    this._geometry = null;
  }

  update() {
    this._geometry = this._source.computeGeometry();
  }

  renderer() {
    return new ZoneRenderer(this._geometry);
  }

  zOrder() {
    return "bottom";
  }
}

export class ZonePrimitive {
  constructor(chart) {
    this._chart = chart;
    this._series = null;
    this._requestUpdate = null;
    this._zone = null;
    this._paneViews = [new ZonePaneView(this)];
  }

  attached({ series, requestUpdate }) {
    this._series = series;
    this._requestUpdate = requestUpdate;
  }

  detached() {
    this._series = null;
    this._requestUpdate = null;
  }

  // zone: {fromTime, toTime, fromIndex, toIndex, low, high, fill, stroke, autoscalePrices}
  setZone(zone) {
    this._zone = zone;
    if (this._requestUpdate) this._requestUpdate();
  }

  updateAllViews() {
    this._paneViews.forEach((view) => view.update());
  }

  paneViews() {
    return this._zone ? this._paneViews : [];
  }

  autoscaleInfo(startLogical, endLogical) {
    const zone = this._zone;
    if (!zone || zone.toIndex < startLogical || zone.fromIndex > endLogical) return null;
    const prices = zone.autoscalePrices.filter(Number.isFinite);
    if (prices.length === 0) return null;
    return { priceRange: { minValue: Math.min(...prices), maxValue: Math.max(...prices) } };
  }

  computeGeometry() {
    const zone = this._zone;
    if (!zone || !this._series || zone.low === null || zone.high === null) return null;
    const timeScale = this._chart.timeScale();
    const x1 = timeScale.timeToCoordinate(zone.fromTime);
    const x2 = timeScale.timeToCoordinate(zone.toTime);
    const yHigh = this._series.priceToCoordinate(zone.high);
    const yLow = this._series.priceToCoordinate(zone.low);
    if ([x1, x2, yHigh, yLow].some((value) => value === null)) return null;
    const halfBar = timeScale.options().barSpacing / 2;
    const left = Math.min(x1, x2) - halfBar;
    const top = Math.min(yHigh, yLow);
    return {
      left,
      top,
      width: Math.abs(x2 - x1) + halfBar * 2,
      height: Math.max(Math.abs(yLow - yHigh), 1),
      fill: zone.fill,
      stroke: zone.stroke,
    };
  }
}
