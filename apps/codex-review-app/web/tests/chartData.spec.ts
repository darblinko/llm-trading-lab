import { expect, test } from '@playwright/test';
import { observations } from '../src/chartData';

test('a gap marker preserves the last recorded observation in its interval', () => {
  expect(observations([
    { time: 1080, value: 40 }, { time: 1100, value: 45 }, { time: 1101 },
    { time: 1620, value: 60 },
  ], { open: 1080, close: 1800 })).toEqual([
    { time: 1080, value: 45 }, { time: 1260 }, { time: 1440 }, { time: 1620, value: 60 },
  ]);
});

test('missing readings stay empty and observations outside session bounds are excluded', () => {
  expect(observations([
    { time: 900, value: 20 }, { time: 1080 }, { time: 1260, value: 0 }, { time: 1440, value: 70 },
  ], { open: 1080, close: 1440 })).toEqual([{ time: 1080 }, { time: 1260, value: 0 }]);
});
