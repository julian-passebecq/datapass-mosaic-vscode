import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateCatalog, validateDeck } from '../../media/learning/model.mjs';
import { loadCatalogDocument } from '../learning_catalog.mjs';

const root = fileURLToPath(new URL('../..', import.meta.url));
const dir = path.join(root, 'content/learning/flashcards');
const catalog = validateCatalog(loadCatalogDocument(root));
const read = name => JSON.parse(readFileSync(path.join(dir, name), 'utf8'));

test('every shipped deck validates against the catalog, names its file and links real lessons', () => {
  let cards = 0;
  for (const name of readdirSync(dir)) {
    assert.match(name, /^[a-z0-9-]+\.json$/);
    const deck = validateDeck(read(name), name.slice(0, -5), catalog);
    cards += deck.cards.length;
  }
  assert.ok(cards >= 200, `${cards} cards`);
});

test('any valid deck in the same format loads, for any existing path', () => {
  const other = catalog.paths.at(-1);
  const deck = { format: 'datapass.flashcards', version: 1, id: 'extra-deck', title: 'Extra', path: other.id,
    cards: [{ id: 'one', front: 'Front?', back: 'Back.', lesson: other.lessons[0], tags: ['t'] }, { id: 'two', front: 'Q', back: 'A', tags: [] }] };
  assert.equal(validateDeck(deck, 'extra-deck', catalog), deck);
});

test('a malformed deck is refused', () => {
  const base = () => structuredClone(read('sql.json'));
  const cases = [
    [d => { d.format = 'anki'; }, /unsupported/],
    [d => { d.version = 2; }, /unsupported/],
    [d => { d.id = 'other'; }, /match its file name/],
    [d => { d.path = 'no-such-path'; }, /unknown learning path/],
    [d => { d.extra = 1; }, /unknown field/],
    [d => { d.cards = []; }, /empty/],
    [d => { d.cards = Array.from({ length: 81 }, (_, i) => ({ id: `c${i}`, front: 'f', back: 'b', tags: [] })); }, /invalid list/],
    [d => { d.cards[1].id = d.cards[0].id; }, /duplicate card id/],
    [d => { d.cards[0].id = '../x'; }, /card id/],
    [d => { d.cards[0].front = 'x'.repeat(301); }, /card front/],
    [d => { d.cards[0].back = 'a\u0000b'; }, /card back/],
    [d => { d.cards[0].lesson = 'no-such-lesson'; }, /unknown lesson/],
    [d => { d.cards[0].tags = Array(9).fill('t'); }, /invalid list/],
    [d => { d.cards[0].html = '<b>x</b>'; }, /unknown field/]
  ];
  for (const [change, pattern] of cases) { const d = base(); change(d); assert.throws(() => validateDeck(d, 'sql', catalog), pattern, String(change)); }
});
