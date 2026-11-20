// Runs interaction tests against the real components in jsdom.
//
// The components are bundled with esbuild; the two context hooks are replaced
// by stubs (see ./stubs) so no server or provider tree is needed.
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');

const dom = new JSDOM('<!doctype html><html dir="rtl"><body></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
});
const { window } = dom;
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent']) {
  Object.defineProperty(globalThis, key, { value: window[key] ?? window, configurable: true });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);

const stubContexts = {
  name: 'stub-contexts',
  setup(b) {
    b.onResolve({ filter: /context\/(Clinic|Auth)Context$/ }, (args) => ({
      path: path.join(here, args.path.includes('Clinic') ? 'stubs/clinic.ts' : 'stubs/auth.ts'),
    }));
  },
};

const outfile = path.join(root, 'node_modules/.cache/dom-tests/bundle.mjs');
await build({
  entryPoints: [path.join(here, process.argv[2] || 'booking-flow.test.tsx')],
  outfile,
  bundle: true,
  format: 'esm',
  platform: 'node',
  jsx: 'automatic',
  external: ['node:*'],
  // Vite injects import.meta.env at build time; tests run with no overrides.
  define: { 'import.meta.env': '{}' },
  plugins: [stubContexts],
  logLevel: 'error',
  banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
});
await import(pathToFileURL(outfile).href);
