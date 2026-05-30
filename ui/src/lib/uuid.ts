// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * UUIDv7 generator (RFC 9562 §5.7).
 *
 * Byte layout (16 bytes total):
 *   bytes 0-5  : unix_ts_ms (48 bits big-endian)
 *   byte  6    : 0x70 | (rand_a_high4 & 0x0F)   — high nibble = version 7, low = rand_a[0:4]
 *   byte  7    : rand_a[4:12]                    — low 8 bits of the 12-bit rand_a
 *   byte  8    : 0x80 | (rand_b_high6 & 0x3F)   — top 2 bits = variant `10`, bottom 6 = rand_b[0:6]
 *   bytes 9-15 : rand_b[6:62]                    — remaining 56 bits of the 62-bit rand_b
 *
 * Produces canonical hyphenated 8-4-4-4-12 hex strings. The first 12 hex chars
 * are lexicographically sortable by unix_ts_ms, which is the property we want
 * for client-side `X-Request-ID` headers (server logs sort naturally over time).
 */

function toHex(byte: number): string {
  return byte.toString(16).padStart(2, '0');
}

export function uuidv7(): string {
  const tsMs = Date.now();
  const rand = crypto.getRandomValues(new Uint8Array(10));

  const bytes = new Uint8Array(16);
  // unix_ts_ms — 48 bits big-endian. tsMs fits in a JS number (< 2**53) until year 8000.
  bytes[0] = Math.floor(tsMs / 2 ** 40) & 0xff;
  bytes[1] = Math.floor(tsMs / 2 ** 32) & 0xff;
  bytes[2] = Math.floor(tsMs / 2 ** 24) & 0xff;
  bytes[3] = Math.floor(tsMs / 2 ** 16) & 0xff;
  bytes[4] = Math.floor(tsMs / 2 ** 8) & 0xff;
  bytes[5] = tsMs & 0xff;
  // byte 6 — version 7 (high nibble) + top 4 bits of rand_a.
  bytes[6] = 0x70 | (rand[0]! & 0x0f);
  // byte 7 — low 8 bits of rand_a.
  bytes[7] = rand[1]!;
  // byte 8 — variant 10 (top 2 bits) + top 6 bits of rand_b.
  bytes[8] = 0x80 | (rand[2]! & 0x3f);
  // bytes 9-15 — remaining rand_b.
  bytes[9] = rand[3]!;
  bytes[10] = rand[4]!;
  bytes[11] = rand[5]!;
  bytes[12] = rand[6]!;
  bytes[13] = rand[7]!;
  bytes[14] = rand[8]!;
  bytes[15] = rand[9]!;

  const hex = Array.from(bytes, toHex).join('');
  return (
    hex.slice(0, 8) +
    '-' +
    hex.slice(8, 12) +
    '-' +
    hex.slice(12, 16) +
    '-' +
    hex.slice(16, 20) +
    '-' +
    hex.slice(20, 32)
  );
}
