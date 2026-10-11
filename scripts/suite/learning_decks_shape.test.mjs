// Flashcard decks (content/learning/flashcards/<deckId>.json): every shipped deck has the shape fixed in
// handoff/V1-FINISH-PLAN.md ("Fixed IDs"), plain-text bounded cards, unique ids, and links only to known lessons/paths.
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateCatalog } from '../../media/learning/model.mjs';
import { loadCatalogDocument } from '../learning_catalog.mjs';

const root = fileURLToPath(new URL('../..', import.meta.url));
const folder = path.join(root, 'content', 'learning', 'flashcards');
const ID = /^[a-z][a-z0-9-]{0,99}$/;
const DECK_KEYS = ['format', 'version', 'id', 'title', 'path', 'cards'];
const CARD_KEYS = ['id', 'front', 'back', 'lesson', 'tags'];
// Plain text: no HTML tags, no Markdown links or images, no control characters other than newline and tab.
const NOT_PLAIN = /<\/?[a-z][^>]*>|!?\[[^\]]*\]\([^)]*\)|[\u0000-\u0008\u000b-\u001f\u007f]/i;

const catalog = validateCatalog(loadCatalogDocument(root));
const lessons = new Set(catalog.lessons.map(l => l.id));
const paths = new Set(catalog.paths.map(p => p.id));
const files = existsSync(folder) ? readdirSync(folder).filter(n => n.endsWith('.json')).sort() : [];

function checkDeck(deck, file) {
  assert.ok(deck && typeof deck === 'object' && !Array.isArray(deck), `${file}: a deck is an object`);
  for (const key of Object.keys(deck)) assert.ok(DECK_KEYS.includes(key), `${file}: unknown deck field ${key}`);
  assert.equal(deck.format, 'datapass.flashcards', `${file}: format`);
  assert.equal(deck.version, 1, `${file}: version`);
  assert.ok(ID.test(deck.id), `${file}: deck id`);
  assert.equal(`${deck.id}.json`, file, `${file}: the file is named after the deck id`);
  assert.ok(typeof deck.title === 'string' && deck.title.trim() && deck.title.length <= 140, `${file}: title`);
  assert.ok(typeof deck.path === 'string' && paths.has(deck.path), `${file}: path ${deck.path} is a catalog path`);
  assert.ok(Array.isArray(deck.cards) && deck.cards.length >= 1 && deck.cards.length <= 80, `${file}: 1 to 80 cards`);
  const ids = new Set();
  for (const card of deck.cards) {
    const where = `${file}#${card?.id}`;
    assert.ok(card && typeof card === 'object' && !Array.isArray(card), `${where}: a card is an object`);
    for (const key of Object.keys(card)) assert.ok(CARD_KEYS.includes(key), `${where}: unknown card field ${key}`);
    assert.ok(typeof card.id === 'string' && ID.test(card.id), `${where}: card id`);
    assert.ok(!ids.has(card.id), `${where}: duplicate card id`); ids.add(card.id);
    for (const [field, max] of [['front', 300], ['back', 1200]]) {
      const value = card[field];
      assert.ok(typeof value === 'string' && value.trim() && value.length <= max, `${where}: ${field} is 1 to ${max} characters`);
      assert.doesNotMatch(value, NOT_PLAIN, `${where}: ${field} is plain text`);
    }
    if ('lesson' in card) assert.ok(lessons.has(card.lesson), `${where}: lesson ${card.lesson} is in the catalog`);
    assert.ok(Array.isArray(card.tags) && card.tags.every(t => typeof t === 'string' && ID.test(t)), `${where}: tags`);
  }
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
    { ...good, cards: [{ ...good.cards[0], back: '<b>bold</b>' }] },
    { ...good, cards: [{ ...good.cards[0], back: 'see [docs](https://example.com)' }] },
    { ...good, cards: [{ ...good.cards[0], lesson: 'no-such-lesson' }] },
    { ...good, cards: [{ ...good.cards[0], id: '../escape' }] },
    { ...good, cards: [{ ...good.cards[0], command: 'rm' }] },
  ];
  for (const deck of broken) assert.throws(() => checkDeck(deck, 'spark-platforms.json'));
  assert.throws(() => checkDeck(good, 'other-name.json'), /named after the deck id/);
});
