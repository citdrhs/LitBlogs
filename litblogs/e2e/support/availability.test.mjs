import assert from 'node:assert/strict';
import test from 'node:test';

import { requiresAvailableEnvironment } from './availability.mjs';

test('CI is always fail closed', () => {
  assert.equal(requiresAvailableEnvironment({ CI: 'true' }), true);
  assert.equal(requiresAvailableEnvironment({ CI: 'false' }), true);
});

test('local browser journeys are fail closed only for the exact required value', () => {
  assert.equal(requiresAvailableEnvironment({ E2E_REQUIRE_AVAILABLE: 'true' }), true);
  assert.equal(requiresAvailableEnvironment({ E2E_REQUIRE_AVAILABLE: 'TRUE' }), false);
  assert.equal(requiresAvailableEnvironment({ E2E_REQUIRE_AVAILABLE: '1' }), false);
  assert.equal(requiresAvailableEnvironment({ E2E_REQUIRE_AVAILABLE: 'false' }), false);
  assert.equal(requiresAvailableEnvironment({}), false);
});
