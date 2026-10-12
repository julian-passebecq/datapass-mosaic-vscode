// Flashcard decks (content/learning/flashcards/<deckId>.json): every shipped deck has the shape fixed in
// handoff/V1-FINISH-PLAN.md ("Fixed IDs"), plain-text bounded cards, unique ids, and links only to known lessons/paths.
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateCatalog, validateDeck } from '../../media/learning/model.mjs';
import { loadCatalogDocument } from '../learning_catalog.mjs';

const root = fileURLToPath(new URL('../..', import.meta.url));
const folder = path.join(root, 'content', 'learning', 'flashcards');

const catalog = validateCatalog(loadCatalogDocument(root));
const files = existsSync(folder) ? readdirSync(folder).filter(n => n.endsWith('.json')).sort() : [];

// The engine's validator (media/learning/model.mjs validateDeck) is the single rule for deck shape.
function checkDeck(deck, file) {
  if (`${deck?.id}.json` !== file) throw new Error(`${file}: the file is named after the deck id`);
  validateDeck(deck, file.replace(/\.json$/, ''), catalog);
}

test('every shipped flashcard deck has the fixed shape', () => {
  assert.ok(files.length >= 4, `decks found: ${files.length}`);
  for (const file of files) checkDeck(JSON.parse(readFileSync(path.join(folder, file), 'utf8')), file);
});

test('the curriculum decks cover their paths', () => {
  for (const id of ['spark-platforms', 'orchestration-production', 'infra-devops', 'bi-governance']) {
    const deck = JSON.parse(readFileSync(path.join(folder, `${id}.json`), 'utf8'));
    assert.equal(deck.path, id);
    assert.ok(deck.cards.length >= 40, `${id}: ${deck.cards.length} cards`);
    const own = new Set(catalog.paths.find(p => p.id === id).lessons);
    for (const lesson of own) assert.ok(deck.cards.some(c => c.lesson === lesson), `${id}: a card for ${lesson}`);
  }
});

test('the shape check rejects broken decks', () => {
  const good = JSON.parse(readFileSync(path.join(folder, 'spark-platforms.json'), 'utf8'));
  const broken = [
    { ...good, format: 'x' },
    { ...good, extra: 1 },
    { ...good, path: 'no-such-path' },
    { ...good, cards: [] },
    { ...good, cards: Array.from({ length: 81 }, (_, i) => ({ ...good.cards[0], id: `c-${i}` })) },
    { ...good, cards: [good.cards[0], good.cards[0]] },
    { ...good, cards: [{ ...good.cards[0], front: 'x'.repeat(301) }] },
    { ...good, cards: [{ ...good.cards[0], lesson: 'no-such-lesson' }] },
    { ...good, cards: [{ ...good.cards[0], id: '../escape' }] },
    { ...good, cards: [{ ...good.cards[0], command: 'rm' }] },
  ];
  for (const deck of broken) assert.throws(() => checkDeck(deck, 'spark-platforms.json'));
  assert.throws(() => checkDeck(good, 'other-name.json'), /named after the deck id/);
});
