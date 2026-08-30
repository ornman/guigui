const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = __dirname;
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const engine = fs.readFileSync(path.join(root, 'xiaojiang-motion.js'), 'utf8');
const scenes = ['idle', 'reading', 'angry', 'alarm', 'loading', 'ingesting', 'diagnosing', 'sleep'];

assert.equal((html.match(/\{ state: '/g) || []).length, 8);
scenes.forEach((state) => assert.match(html, new RegExp(`\\{ state: '${state}'`)));
assert.match(html, /src="\.\/xiaojiang-motion\.js\?v=1"/);
assert.doesNotMatch(html, /[A-Z]:\\\\|file:\/\/\//i);
assert.ok(fs.existsSync(path.join(root, '.nojekyll')));

new vm.Script(engine, { filename: 'xiaojiang-motion.js' });
const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
assert.equal(inlineScripts.length, 1);
new vm.Script(inlineScripts[0][1], { filename: 'index-inline.js' });

console.log('xiaojiang showcase checks passed');
