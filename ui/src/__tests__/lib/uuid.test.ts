// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { uuidv7 } from '@/lib/uuid';

describe('uuidv7', () => {
  it('produces a canonical 8-4-4-4-12 hyphenated hex string', () => {
    const id = uuidv7();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  });

  it('encodes the unix_ts_ms timestamp in the first 12 hex chars (big-endian)', () => {
    // Freeze time. Date.now() reads the same ms for both the test and uuidv7().
    const fixedMs = 0x017f_5e1c_3a40; // arbitrary 48-bit ts
    const originalNow = Date.now;
    Date.now = () => fixedMs;
    try {
      const id = uuidv7();
      const tsHex = id.slice(0, 8) + id.slice(9, 13); // first 8 hex + 4 hex past the first `-`
      expect(tsHex).toBe(fixedMs.toString(16).padStart(12, '0'));
    } finally {
      Date.now = originalNow;
    }
  });

  it('sets the version nibble to 7 (RFC 9562 §5.7)', () => {
    const id = uuidv7();
    // Byte 6 is the 13th-14th hex char (after the second `-` removes 2 separators);
    // simpler: the third hyphen-segment starts with the version nibble.
    const versionNibble = id[14]; // position of byte-6-high-nibble after hyphens at idx 8 and 13
    expect(versionNibble).toBe('7');
  });

  it('sets the variant high 2 bits to `10` (RFC 9562)', () => {
    const id = uuidv7();
    // Byte 8 is the start of the fourth hyphen-segment (idx 19 in the string).
    const variantHex = id[19];
    // First hex char of byte 8 must be in {8, 9, a, b} — top 2 bits = 10.
    expect(['8', '9', 'a', 'b']).toContain(variantHex);
  });

  it('returns distinct IDs across rapid calls', () => {
    const ids = new Set([uuidv7(), uuidv7(), uuidv7(), uuidv7(), uuidv7()]);
    expect(ids.size).toBe(5);
  });
});
