import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

/**
 * Guards the app's type scale: readable text is never smaller than 12px and
 * sizes come from the scale tokens (text-caption / small / body / lead /
 * heading) instead of ad-hoc pixel values.
 */

const SRC = join(import.meta.dirname, '..');
const FLOOR_PX = 12;

// Deliberate, documented exceptions: file → reason.
const ALLOWED_SMALL = new Set<string>([
  // Month labels under chart bars on phones: 12px would truncate them.
  'components/common/ui.tsx:text-[11px]',
]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.(tsx|css)$/.test(name) ? [full] : [];
  });
}

const files = walk(SRC).map((full) => ({
  rel: full.slice(SRC.length + 1).replaceAll('\\', '/'),
  text: readFileSync(full, 'utf8'),
}));

test('no arbitrary text size below the 12px floor (except documented ones)', () => {
  const offenders: string[] = [];
  for (const { rel, text } of files.filter((file) => file.rel.endsWith('.tsx'))) {
    for (const match of text.matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)) {
      if (Number(match[1]) < FLOOR_PX && !ALLOWED_SMALL.has(`${rel}:${match[0]}`)) {
        offenders.push(`${rel}: ${match[0]}`);
      }
    }
  }
  assert.deepEqual(offenders, []);
});

test('no CSS font-size below the floor', () => {
  const css = files.find((file) => file.rel === 'index.css')!.text;
  const offenders = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)]
    .filter((match) => Number(match[1]) < FLOOR_PX)
    .map((match) => match[0]);
  assert.deepEqual(offenders, []);
});

test('the scale tokens are defined and none is under the floor', () => {
  const css = files.find((file) => file.rel === 'index.css')!.text;
  for (const name of ['caption', 'small', 'body', 'lead', 'heading']) {
    const match = css.match(new RegExp(`--text-${name}:\\s*([\\d.]+)rem`));
    assert.ok(match, `--text-${name} is defined`);
    assert.ok(Number(match![1]) * 16 >= FLOOR_PX, `--text-${name} >= ${FLOOR_PX}px`);
  }
});

test('form fields stay at 16px on phones so iOS does not zoom on focus', () => {
  const css = files.find((file) => file.rel === 'index.css')!.text;
  assert.match(css, /@media \(max-width:\s*639px\)\s*\{[\s\S]*?textarea\s*\{\s*font-size:\s*16px\s*!important/);
});
