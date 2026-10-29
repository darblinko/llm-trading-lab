import type { UTCTimestamp } from 'lightweight-charts';
import type { Point, SessionWindow } from './types';

type Window = Pick<SessionWindow, 'open' | 'close'>;

export function sessionGrid(session: Window): number[] {
  return Array.from({ length: Math.ceil((session.close - session.open) / 180) }, (_, i) => session.open + i * 180);
}

export function observations(points: Point[], session: Window) {
  const buckets = new Map<number, Point>();
  for (const point of points) {
    // Gap markers carry no observation. They must not erase a recorded value
    // from the same interval; empty intervals receive whitespace below.
    if (point.value != null) buckets.set(Math.floor(point.time / 180) * 180, point);
  }
  return sessionGrid(session).map(time => ({ time: time as UTCTimestamp,
    ...(buckets.has(time) ? { value: buckets.get(time)!.value! } : {}),
  }));
}
