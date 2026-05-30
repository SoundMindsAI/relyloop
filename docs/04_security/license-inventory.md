# Dependency License Inventory

> **Generated file — do not edit by hand.** Regenerate with `python scripts/gen_license_inventory.py`. Per-package adjudications and license overrides live in that script (`ADJUDICATIONS` / `PY_LICENSE_OVERRIDES`).

RelyLoop is distributed under **Apache-2.0**. Apache-2.0 is incompatible with **strong copyleft (GPL / AGPL)** in a *shipped* dependency. This inventory is derived from the locked dependency closure (`uv tree` + `pnpm licenses`), so it is identical in CI and locally regardless of ambient virtualenv state. Versions are omitted on purpose — they live in `uv.lock` / `ui/pnpm-lock.yaml`, and excluding them keeps routine bumps from churning this file.

The `license-inventory` CI job runs `python scripts/gen_license_inventory.py --check`, which fails if (a) this file is stale, or (b) any **shipped** dependency carries a forbidden or unclassified license.

## Flagged licenses (non-permissive)

| Package | Ecosystem | License | Scope | Apache-2.0 compatible? | Decided action |
|---|---|---|---|---|---|
| certifi | Python | Mozilla Public License 2.0 (MPL 2.0) | runtime | Yes — weak copyleft (file-level), flagged | **Accept.** MPL-2.0 is file-level (weak) copyleft and is explicitly compatible with Apache-2.0 for mere aggregation/distribution; we ship certifi unmodified, so no source-disclosure obligation attaches to RelyLoop's own Apache-2.0 code. |
| pathspec | Python | Mozilla Public License 2.0 (MPL 2.0) | dev | Yes — weak copyleft (file-level), flagged | **Accept.** Dev-only (pulled by the `reuse`/pre-commit toolchain). MPL-2.0 file-level copyleft; never shipped in the runtime artifact. |
| psycopg2-binary | Python | GNU Library or Lesser General Public License (LGPL) | runtime | Yes — weak copyleft (file-level), flagged | **Accept.** LGPL-3.0 (with the OpenSSL exception). LGPL's copyleft is library-level: we use psycopg2 as an unmodified, dynamically-imported PostgreSQL driver and never modify its source, so no obligation attaches to RelyLoop's Apache-2.0 code. Shipping an unmodified LGPL library alongside permissive code is the canonical allowed case. |
| python-debian | Python | DFSG approved; GNU General Public License v2 or later (GPLv2+) | dev | **NO — strong copyleft** | **Accept.** Dev-only (transitive dep of the `reuse` SPDX linter). GPL-2.0+, but a build-time tool that is never imported, linked, or bundled into the distributed artifact — its copyleft does not reach shipped code. |
| reuse | Python | Apache Software License; CC0 1.0 Universal (CC0 1.0) Public Domain Dedication; DFSG approved; GNU General Public License v3 or later (GPLv3+); Other/Proprietary License | dev | **NO — strong copyleft** | **Accept.** Dev-only (the SPDX-header linter run by pre-commit + the `license-headers` CI job). GPL-3.0, but `reuse` is never imported, linked, or bundled into the distributed RelyLoop artifact — it is a build-time tool, so its copyleft does not reach distributed code. |
| tqdm | Python | MPL-2.0 AND MIT | runtime | Yes — weak copyleft (file-level), flagged | **Accept.** Dual-licensed MPL-2.0 AND MIT — the MIT grant alone is fully Apache-2.0-compatible, so we take it under MIT. (tqdm is a transitive progress-bar dep; shipped unmodified regardless.) |
| @img/sharp-libvips-<platform> | npm | LGPL-3.0-or-later | runtime | Yes — weak copyleft (file-level), flagged | **Accept.** LGPL-3.0 platform binary for `sharp` (image processing, transitively via Next.js). Shipped unmodified as a dynamically-loaded library; LGPL library-level copyleft imposes no obligation on RelyLoop's own Apache-2.0 code. Replaceable if ever needed. |
| axe-core | npm | MPL-2.0 | dev | Yes — weak copyleft (file-level), flagged | **Accept.** Dev-only (accessibility testing, transitive via the test tooling). MPL-2.0 file-level copyleft; never shipped. |
| lightningcss | npm | MPL-2.0 | dev | Yes — weak copyleft (file-level), flagged | **Accept.** Dev-only (CSS build tooling). MPL-2.0 file-level copyleft; never shipped in the runtime artifact. |

## Full inventory

| Package | Ecosystem | License | Scope | Apache-2.0 compatible? |
|---|---|---|---|---|
| alembic | Python | MIT | runtime | Yes |
| annotated-doc | Python | MIT | runtime | Yes |
| annotated-types | Python | MIT License | runtime | Yes |
| anyio | Python | MIT | runtime | Yes |
| arq | Python | MIT License | runtime | Yes |
| asgi-lifespan | Python | MIT | dev | Yes |
| ast_serialize | Python | MIT | dev | Yes |
| asyncpg | Python | Apache-2.0 | runtime | Yes |
| attrs | Python | MIT | dev | Yes |
| certifi | Python | Mozilla Public License 2.0 (MPL 2.0) | runtime | Yes — weak copyleft (file-level), flagged |
| cfgv | Python | MIT | dev | Yes |
| charset-normalizer | Python | MIT | dev | Yes |
| click | Python | BSD-3-Clause | runtime | Yes |
| colorlog | Python | MIT License | runtime | Yes |
| contourpy | Python | BSD License | runtime | Yes |
| coverage | Python | Apache-2.0 | dev | Yes |
| cycler | Python | BSD License | runtime | Yes |
| distlib | Python | Python Software Foundation License | dev | Yes |
| distro | Python | Apache Software License | runtime | Yes |
| docker | Python | Apache-2.0 | dev | Yes |
| execnet | Python | MIT | dev | Yes |
| fastapi | Python | MIT | runtime | Yes |
| filelock | Python | MIT | dev | Yes |
| fonttools | Python | MIT | runtime | Yes |
| greenlet | Python | MIT AND PSF-2.0 | runtime | Yes |
| h11 | Python | MIT License | runtime | Yes |
| hiredis | Python | MIT License | runtime | Yes |
| httpcore | Python | BSD-3-Clause | runtime | Yes |
| httptools | Python | MIT | runtime | Yes |
| httpx | Python | BSD License | runtime | Yes |
| identify | Python | MIT | dev | Yes |
| idna | Python | BSD-3-Clause | runtime | Yes |
| iniconfig | Python | MIT | dev | Yes |
| ir_measures | Python | Apache Software License | runtime | Yes |
| Jinja2 | Python | BSD License | runtime | Yes |
| jiter | Python | MIT | runtime | Yes |
| joblib | Python | BSD-3-Clause | runtime | Yes |
| kiwisolver | Python | BSD License | runtime | Yes |
| librt | Python | MIT | dev | Yes |
| license-expression | Python | Apache-2.0 | dev | Yes |
| Mako | Python | MIT License | runtime | Yes |
| MarkupSafe | Python | BSD-3-Clause | runtime | Yes |
| matplotlib | Python | Python Software Foundation License | runtime | Yes |
| mypy | Python | MIT | dev | Yes |
| mypy_extensions | Python | MIT | dev | Yes |
| nodeenv | Python | BSD License | dev | Yes |
| numpy | Python | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | runtime | Yes |
| openai | Python | Apache Software License | runtime | Yes |
| optuna | Python | MIT License | runtime | Yes |
| packaging | Python | Apache-2.0 OR BSD-2-Clause | runtime | Yes |
| pathspec | Python | Mozilla Public License 2.0 (MPL 2.0) | dev | Yes — weak copyleft (file-level), flagged |
| pillow | Python | MIT-CMU | runtime | Yes |
| platformdirs | Python | MIT | dev | Yes |
| pluggy | Python | MIT License | dev | Yes |
| pre_commit | Python | MIT | dev | Yes |
| psycopg2-binary | Python | GNU Library or Lesser General Public License (LGPL) | runtime | Yes — weak copyleft (file-level), flagged |
| pydantic | Python | MIT | runtime | Yes |
| pydantic_core | Python | MIT | runtime | Yes |
| pydantic-settings | Python | MIT | runtime | Yes |
| Pygments | Python | BSD-2-Clause | dev | Yes |
| PyJWT | Python | MIT | runtime | Yes |
| pyparsing | Python | MIT | runtime | Yes |
| pytest | Python | MIT | dev | Yes |
| pytest-asyncio | Python | Apache-2.0 | dev | Yes |
| pytest-cov | Python | MIT | dev | Yes |
| pytest-mock | Python | MIT License | dev | Yes |
| pytest-recording | Python | MIT | dev | Yes |
| pytest-xdist | Python | MIT | dev | Yes |
| python-dateutil | Python | Apache Software License; BSD License | runtime | Yes |
| python-debian | Python | DFSG approved; GNU General Public License v2 or later (GPLv2+) | dev | **NO — strong copyleft** |
| python-discovery | Python | MIT License | dev | Yes |
| python-dotenv | Python | BSD-3-Clause | runtime | Yes |
| python-magic | Python | MIT License | dev | Yes |
| pytrec_eval-terrier | Python | MIT License | runtime | Yes |
| PyYAML | Python | MIT License | runtime | Yes |
| redis | Python | MIT License | runtime | Yes |
| relyloop | Python | Apache Software License | runtime | Yes |
| requests | Python | Apache Software License | dev | Yes |
| reuse | Python | Apache Software License; CC0 1.0 Universal (CC0 1.0) Public Domain Dedication; DFSG approved; GNU General Public License v3 or later (GPLv3+); Other/Proprietary License | dev | **NO — strong copyleft** |
| ruff | Python | MIT | dev | Yes |
| scikit-learn | Python | BSD-3-Clause | runtime | Yes |
| scipy | Python | BSD License | runtime | Yes |
| six | Python | MIT License | runtime | Yes |
| sniffio | Python | Apache Software License; MIT License | runtime | Yes |
| SQLAlchemy | Python | MIT | runtime | Yes |
| starlette | Python | BSD-3-Clause | runtime | Yes |
| structlog | Python | MIT OR Apache-2.0 | runtime | Yes |
| testcontainers | Python | Apache-2.0 | dev | Yes |
| threadpoolctl | Python | BSD License | runtime | Yes |
| tomlkit | Python | MIT License | dev | Yes |
| tqdm | Python | MPL-2.0 AND MIT | runtime | Yes — weak copyleft (file-level), flagged |
| types-PyYAML | Python | Apache-2.0 | dev | Yes |
| typing_extensions | Python | PSF-2.0 | runtime | Yes |
| typing-inspection | Python | MIT | runtime | Yes |
| urllib3 | Python | MIT | dev | Yes |
| uuid_utils | Python | BSD-3-Clause | runtime | Yes |
| uvloop | Python | Apache Software License; MIT License | runtime | Yes |
| vcrpy | Python | MIT License | dev | Yes |
| virtualenv | Python | MIT | dev | Yes |
| watchfiles | Python | MIT License | runtime | Yes |
| websockets | Python | BSD-3-Clause | runtime | Yes |
| wrapt | Python | BSD-2-Clause | dev | Yes |
| @adobe/css-tools | npm | MIT | dev | Yes |
| @alloc/quick-lru | npm | MIT | dev | Yes |
| @asamuzakjp/css-color | npm | MIT | dev | Yes |
| @asamuzakjp/dom-selector | npm | MIT | dev | Yes |
| @asamuzakjp/generational-cache | npm | MIT | dev | Yes |
| @asamuzakjp/nwsapi | npm | MIT | dev | Yes |
| @babel/code-frame | npm | MIT | runtime | Yes |
| @babel/compat-data | npm | MIT | runtime | Yes |
| @babel/core | npm | MIT | runtime | Yes |
| @babel/generator | npm | MIT | runtime | Yes |
| @babel/helper-compilation-targets | npm | MIT | runtime | Yes |
| @babel/helper-globals | npm | MIT | runtime | Yes |
| @babel/helper-module-imports | npm | MIT | runtime | Yes |
| @babel/helper-module-transforms | npm | MIT | runtime | Yes |
| @babel/helper-string-parser | npm | MIT | runtime | Yes |
| @babel/helper-validator-identifier | npm | MIT | runtime | Yes |
| @babel/helper-validator-option | npm | MIT | runtime | Yes |
| @babel/helpers | npm | MIT | runtime | Yes |
| @babel/parser | npm | MIT | runtime | Yes |
| @babel/runtime | npm | MIT | dev | Yes |
| @babel/template | npm | MIT | runtime | Yes |
| @babel/traverse | npm | MIT | runtime | Yes |
| @babel/types | npm | MIT | runtime | Yes |
| @bramus/specificity | npm | MIT | dev | Yes |
| @csstools/color-helpers | npm | MIT-0 | dev | Yes |
| @csstools/css-calc | npm | MIT | dev | Yes |
| @csstools/css-color-parser | npm | MIT | dev | Yes |
| @csstools/css-parser-algorithms | npm | MIT | dev | Yes |
| @csstools/css-syntax-patches-for-csstree | npm | MIT-0 | dev | Yes |
| @csstools/css-tokenizer | npm | MIT | dev | Yes |
| @eslint-community/eslint-utils | npm | MIT | dev | Yes |
| @eslint-community/regexpp | npm | MIT | dev | Yes |
| @eslint/config-array | npm | Apache-2.0 | dev | Yes |
| @eslint/config-helpers | npm | Apache-2.0 | dev | Yes |
| @eslint/core | npm | Apache-2.0 | dev | Yes |
| @eslint/eslintrc | npm | MIT | dev | Yes |
| @eslint/js | npm | MIT | dev | Yes |
| @eslint/object-schema | npm | Apache-2.0 | dev | Yes |
| @eslint/plugin-kit | npm | Apache-2.0 | dev | Yes |
| @exodus/bytes | npm | MIT | dev | Yes |
| @floating-ui/core | npm | MIT | runtime | Yes |
| @floating-ui/dom | npm | MIT | runtime | Yes |
| @floating-ui/react-dom | npm | MIT | runtime | Yes |
| @floating-ui/utils | npm | MIT | runtime | Yes |
| @hookform/resolvers | npm | MIT | runtime | Yes |
| @humanfs/core | npm | Apache-2.0 | dev | Yes |
| @humanfs/node | npm | Apache-2.0 | dev | Yes |
| @humanfs/types | npm | Apache-2.0 | dev | Yes |
| @humanwhocodes/module-importer | npm | Apache-2.0 | dev | Yes |
| @humanwhocodes/retry | npm | Apache-2.0 | dev | Yes |
| @img/colour | npm | MIT | runtime | Yes |
| @img/sharp-<platform> | npm | Apache-2.0 | runtime | Yes |
| @img/sharp-libvips-<platform> | npm | LGPL-3.0-or-later | runtime | Yes — weak copyleft (file-level), flagged |
| @inquirer/ansi | npm | MIT | dev | Yes |
| @inquirer/confirm | npm | MIT | dev | Yes |
| @inquirer/core | npm | MIT | dev | Yes |
| @inquirer/figures | npm | MIT | dev | Yes |
| @inquirer/type | npm | MIT | dev | Yes |
| @jridgewell/gen-mapping | npm | MIT | runtime | Yes |
| @jridgewell/remapping | npm | MIT | runtime | Yes |
| @jridgewell/resolve-uri | npm | MIT | runtime | Yes |
| @jridgewell/sourcemap-codec | npm | MIT | runtime | Yes |
| @jridgewell/trace-mapping | npm | MIT | runtime | Yes |
| @mswjs/interceptors | npm | MIT | dev | Yes |
| @next/env | npm | MIT | runtime | Yes |
| @next/eslint-plugin-next | npm | MIT | dev | Yes |
| @next/swc-<platform> | npm | MIT | runtime | Yes |
| @nodelib/fs.scandir | npm | MIT | dev | Yes |
| @nodelib/fs.stat | npm | MIT | dev | Yes |
| @nodelib/fs.walk | npm | MIT | dev | Yes |
| @nolyfill/is-core-module | npm | MIT | dev | Yes |
| @open-draft/deferred-promise | npm | MIT | dev | Yes |
| @open-draft/logger | npm | MIT | dev | Yes |
| @open-draft/until | npm | MIT | dev | Yes |
| @oxc-project/types | npm | MIT | dev | Yes |
| @playwright/test | npm | Apache-2.0 | runtime | Yes |
| @radix-ui/number | npm | MIT | runtime | Yes |
| @radix-ui/primitive | npm | MIT | runtime | Yes |
| @radix-ui/react-alert-dialog | npm | MIT | runtime | Yes |
| @radix-ui/react-arrow | npm | MIT | runtime | Yes |
| @radix-ui/react-collection | npm | MIT | runtime | Yes |
| @radix-ui/react-compose-refs | npm | MIT | runtime | Yes |
| @radix-ui/react-context | npm | MIT | runtime | Yes |
| @radix-ui/react-dialog | npm | MIT | runtime | Yes |
| @radix-ui/react-direction | npm | MIT | runtime | Yes |
| @radix-ui/react-dismissable-layer | npm | MIT | runtime | Yes |
| @radix-ui/react-focus-guards | npm | MIT | runtime | Yes |
| @radix-ui/react-focus-scope | npm | MIT | runtime | Yes |
| @radix-ui/react-id | npm | MIT | runtime | Yes |
| @radix-ui/react-label | npm | MIT | runtime | Yes |
| @radix-ui/react-popover | npm | MIT | runtime | Yes |
| @radix-ui/react-popper | npm | MIT | runtime | Yes |
| @radix-ui/react-portal | npm | MIT | runtime | Yes |
| @radix-ui/react-presence | npm | MIT | runtime | Yes |
| @radix-ui/react-primitive | npm | MIT | runtime | Yes |
| @radix-ui/react-roving-focus | npm | MIT | runtime | Yes |
| @radix-ui/react-select | npm | MIT | runtime | Yes |
| @radix-ui/react-slot | npm | MIT | runtime | Yes |
| @radix-ui/react-tabs | npm | MIT | runtime | Yes |
| @radix-ui/react-tooltip | npm | MIT | runtime | Yes |
| @radix-ui/react-use-callback-ref | npm | MIT | runtime | Yes |
| @radix-ui/react-use-controllable-state | npm | MIT | runtime | Yes |
| @radix-ui/react-use-effect-event | npm | MIT | runtime | Yes |
| @radix-ui/react-use-escape-keydown | npm | MIT | runtime | Yes |
| @radix-ui/react-use-layout-effect | npm | MIT | runtime | Yes |
| @radix-ui/react-use-previous | npm | MIT | runtime | Yes |
| @radix-ui/react-use-rect | npm | MIT | runtime | Yes |
| @radix-ui/react-use-size | npm | MIT | runtime | Yes |
| @radix-ui/react-visually-hidden | npm | MIT | runtime | Yes |
| @radix-ui/rect | npm | MIT | runtime | Yes |
| @redocly/ajv | npm | MIT | dev | Yes |
| @redocly/config | npm | MIT | dev | Yes |
| @redocly/openapi-core | npm | MIT | dev | Yes |
| @reduxjs/toolkit | npm | MIT | runtime | Yes |
| @rolldown/pluginutils | npm | MIT | dev | Yes |
| @rtsao/scc | npm | MIT | dev | Yes |
| @standard-schema/spec | npm | MIT | runtime | Yes |
| @standard-schema/utils | npm | MIT | runtime | Yes |
| @swc/helpers | npm | Apache-2.0 | runtime | Yes |
| @tailwindcss/node | npm | MIT | dev | Yes |
| @tailwindcss/oxide | npm | MIT | dev | Yes |
| @tailwindcss/postcss | npm | MIT | dev | Yes |
| @tailwindcss/typography | npm | MIT | dev | Yes |
| @tanstack/query-core | npm | MIT | runtime | Yes |
| @tanstack/query-devtools | npm | MIT | runtime | Yes |
| @tanstack/react-query | npm | MIT | runtime | Yes |
| @tanstack/react-query-devtools | npm | MIT | runtime | Yes |
| @tanstack/react-table | npm | MIT | runtime | Yes |
| @tanstack/table-core | npm | MIT | runtime | Yes |
| @testing-library/dom | npm | MIT | dev | Yes |
| @testing-library/jest-dom | npm | MIT | dev | Yes |
| @testing-library/react | npm | MIT | dev | Yes |
| @testing-library/user-event | npm | MIT | dev | Yes |
| @types/aria-query | npm | MIT | dev | Yes |
| @types/chai | npm | MIT | dev | Yes |
| @types/d3-array | npm | MIT | runtime | Yes |
| @types/d3-color | npm | MIT | runtime | Yes |
| @types/d3-ease | npm | MIT | runtime | Yes |
| @types/d3-interpolate | npm | MIT | runtime | Yes |
| @types/d3-path | npm | MIT | runtime | Yes |
| @types/d3-scale | npm | MIT | runtime | Yes |
| @types/d3-shape | npm | MIT | runtime | Yes |
| @types/d3-time | npm | MIT | runtime | Yes |
| @types/d3-timer | npm | MIT | runtime | Yes |
| @types/debug | npm | MIT | runtime | Yes |
| @types/deep-eql | npm | MIT | dev | Yes |
| @types/estree | npm | MIT | runtime | Yes |
| @types/estree-jsx | npm | MIT | runtime | Yes |
| @types/hast | npm | MIT | runtime | Yes |
| @types/json-schema | npm | MIT | dev | Yes |
| @types/json5 | npm | MIT | dev | Yes |
| @types/mdast | npm | MIT | runtime | Yes |
| @types/ms | npm | MIT | runtime | Yes |
| @types/node | npm | MIT | dev | Yes |
| @types/prismjs | npm | MIT | runtime | Yes |
| @types/react | npm | MIT | runtime | Yes |
| @types/react-dom | npm | MIT | runtime | Yes |
| @types/set-cookie-parser | npm | MIT | dev | Yes |
| @types/statuses | npm | MIT | dev | Yes |
| @types/unist | npm | MIT | runtime | Yes |
| @types/use-sync-external-store | npm | MIT | runtime | Yes |
| @typescript-eslint/eslint-plugin | npm | MIT | dev | Yes |
| @typescript-eslint/parser | npm | MIT | dev | Yes |
| @typescript-eslint/project-service | npm | MIT | dev | Yes |
| @typescript-eslint/scope-manager | npm | MIT | dev | Yes |
| @typescript-eslint/tsconfig-utils | npm | MIT | dev | Yes |
| @typescript-eslint/type-utils | npm | MIT | dev | Yes |
| @typescript-eslint/types | npm | MIT | dev | Yes |
| @typescript-eslint/typescript-estree | npm | MIT | dev | Yes |
| @typescript-eslint/utils | npm | MIT | dev | Yes |
| @typescript-eslint/visitor-keys | npm | MIT | dev | Yes |
| @ungap/structured-clone | npm | ISC | runtime | Yes |
| @vitejs/plugin-react | npm | MIT | dev | Yes |
| @vitest/expect | npm | MIT | dev | Yes |
| @vitest/mocker | npm | MIT | dev | Yes |
| @vitest/pretty-format | npm | MIT | dev | Yes |
| @vitest/runner | npm | MIT | dev | Yes |
| @vitest/snapshot | npm | MIT | dev | Yes |
| @vitest/spy | npm | MIT | dev | Yes |
| @vitest/utils | npm | MIT | dev | Yes |
| acorn | npm | MIT | dev | Yes |
| acorn-jsx | npm | MIT | dev | Yes |
| agent-base | npm | MIT | dev | Yes |
| ajv | npm | MIT | dev | Yes |
| ansi-colors | npm | MIT | dev | Yes |
| ansi-regex | npm | MIT | dev | Yes |
| ansi-styles | npm | MIT | dev | Yes |
| argparse | npm | Python-2.0 | dev | Yes |
| aria-hidden | npm | MIT | runtime | Yes |
| aria-query | npm | Apache-2.0 | dev | Yes |
| array-buffer-byte-length | npm | MIT | dev | Yes |
| array-includes | npm | MIT | dev | Yes |
| array.prototype.findlast | npm | MIT | dev | Yes |
| array.prototype.findlastindex | npm | MIT | dev | Yes |
| array.prototype.flat | npm | MIT | dev | Yes |
| array.prototype.flatmap | npm | MIT | dev | Yes |
| array.prototype.tosorted | npm | MIT | dev | Yes |
| arraybuffer.prototype.slice | npm | MIT | dev | Yes |
| assertion-error | npm | MIT | dev | Yes |
| ast-types-flow | npm | MIT | dev | Yes |
| async-function | npm | MIT | dev | Yes |
| autoprefixer | npm | MIT | dev | Yes |
| available-typed-arrays | npm | MIT | dev | Yes |
| axe-core | npm | MPL-2.0 | dev | Yes — weak copyleft (file-level), flagged |
| axobject-query | npm | Apache-2.0 | dev | Yes |
| bail | npm | MIT | runtime | Yes |
| balanced-match | npm | MIT | dev | Yes |
| baseline-browser-mapping | npm | Apache-2.0 | runtime | Yes |
| bidi-js | npm | MIT | dev | Yes |
| brace-expansion | npm | MIT | dev | Yes |
| braces | npm | MIT | dev | Yes |
| browserslist | npm | MIT | runtime | Yes |
| call-bind | npm | MIT | dev | Yes |
| call-bind-apply-helpers | npm | MIT | dev | Yes |
| call-bound | npm | MIT | dev | Yes |
| callsites | npm | MIT | dev | Yes |
| caniuse-lite | npm | CC-BY-4.0 | runtime | Yes |
| ccount | npm | MIT | runtime | Yes |
| chai | npm | MIT | dev | Yes |
| chalk | npm | MIT | dev | Yes |
| change-case | npm | MIT | dev | Yes |
| character-entities | npm | MIT | runtime | Yes |
| character-entities-html4 | npm | MIT | runtime | Yes |
| character-entities-legacy | npm | MIT | runtime | Yes |
| character-reference-invalid | npm | MIT | runtime | Yes |
| class-variance-authority | npm | Apache-2.0 | runtime | Yes |
| cli-width | npm | ISC | dev | Yes |
| client-only | npm | MIT | runtime | Yes |
| cliui | npm | ISC | dev | Yes |
| clsx | npm | MIT | runtime | Yes |
| color-convert | npm | MIT | dev | Yes |
| color-name | npm | MIT | dev | Yes |
| colorette | npm | MIT | dev | Yes |
| comma-separated-tokens | npm | MIT | runtime | Yes |
| concat-map | npm | MIT | dev | Yes |
| convert-source-map | npm | MIT | runtime | Yes |
| cookie | npm | MIT | dev | Yes |
| cross-spawn | npm | MIT | dev | Yes |
| css-tree | npm | MIT | dev | Yes |
| css.escape | npm | MIT | dev | Yes |
| cssesc | npm | MIT | dev | Yes |
| csstype | npm | MIT | runtime | Yes |
| d3-array | npm | ISC | runtime | Yes |
| d3-color | npm | ISC | runtime | Yes |
| d3-ease | npm | BSD-3-Clause | runtime | Yes |
| d3-format | npm | ISC | runtime | Yes |
| d3-interpolate | npm | ISC | runtime | Yes |
| d3-path | npm | ISC | runtime | Yes |
| d3-scale | npm | ISC | runtime | Yes |
| d3-shape | npm | ISC | runtime | Yes |
| d3-time | npm | ISC | runtime | Yes |
| d3-time-format | npm | ISC | runtime | Yes |
| d3-timer | npm | ISC | runtime | Yes |
| damerau-levenshtein | npm | BSD-2-Clause | dev | Yes |
| data-urls | npm | MIT | dev | Yes |
| data-view-buffer | npm | MIT | dev | Yes |
| data-view-byte-length | npm | MIT | dev | Yes |
| data-view-byte-offset | npm | MIT | dev | Yes |
| debug | npm | MIT | runtime | Yes |
| decimal.js | npm | MIT | dev | Yes |
| decimal.js-light | npm | MIT | runtime | Yes |
| decode-named-character-reference | npm | MIT | runtime | Yes |
| deep-is | npm | MIT | dev | Yes |
| define-data-property | npm | MIT | dev | Yes |
| define-properties | npm | MIT | dev | Yes |
| dequal | npm | MIT | runtime | Yes |
| detect-libc | npm | Apache-2.0 | runtime | Yes |
| detect-node-es | npm | MIT | runtime | Yes |
| devlop | npm | MIT | runtime | Yes |
| doctrine | npm | Apache-2.0 | dev | Yes |
| dom-accessibility-api | npm | MIT | dev | Yes |
| dunder-proto | npm | MIT | dev | Yes |
| electron-to-chromium | npm | ISC | runtime | Yes |
| emoji-regex | npm | MIT | dev | Yes |
| enhanced-resolve | npm | MIT | dev | Yes |
| entities | npm | BSD-2-Clause | dev | Yes |
| es-abstract | npm | MIT | dev | Yes |
| es-define-property | npm | MIT | dev | Yes |
| es-errors | npm | MIT | dev | Yes |
| es-iterator-helpers | npm | MIT | dev | Yes |
| es-module-lexer | npm | MIT | dev | Yes |
| es-object-atoms | npm | MIT | dev | Yes |
| es-set-tostringtag | npm | MIT | dev | Yes |
| es-shim-unscopables | npm | MIT | dev | Yes |
| es-to-primitive | npm | MIT | dev | Yes |
| es-toolkit | npm | MIT | runtime | Yes |
| escalade | npm | MIT | runtime | Yes |
| escape-string-regexp | npm | MIT | runtime | Yes |
| eslint | npm | MIT | dev | Yes |
| eslint-config-next | npm | MIT | dev | Yes |
| eslint-import-resolver-node | npm | MIT | dev | Yes |
| eslint-import-resolver-typescript | npm | ISC | dev | Yes |
| eslint-module-utils | npm | MIT | dev | Yes |
| eslint-plugin-import | npm | MIT | dev | Yes |
| eslint-plugin-jsx-a11y | npm | MIT | dev | Yes |
| eslint-plugin-react | npm | MIT | dev | Yes |
| eslint-plugin-react-hooks | npm | MIT | dev | Yes |
| eslint-plugin-security | npm | Apache-2.0 | dev | Yes |
| eslint-scope | npm | BSD-2-Clause | dev | Yes |
| eslint-visitor-keys | npm | Apache-2.0 | dev | Yes |
| espree | npm | BSD-2-Clause | dev | Yes |
| esquery | npm | BSD-3-Clause | dev | Yes |
| esrecurse | npm | BSD-2-Clause | dev | Yes |
| estraverse | npm | BSD-2-Clause | dev | Yes |
| estree-util-is-identifier-name | npm | MIT | runtime | Yes |
| estree-walker | npm | MIT | dev | Yes |
| esutils | npm | BSD-2-Clause | dev | Yes |
| eventemitter3 | npm | MIT | runtime | Yes |
| expect-type | npm | Apache-2.0 | dev | Yes |
| extend | npm | MIT | runtime | Yes |
| fast-deep-equal | npm | MIT | dev | Yes |
| fast-glob | npm | MIT | dev | Yes |
| fast-json-stable-stringify | npm | MIT | dev | Yes |
| fast-levenshtein | npm | MIT | dev | Yes |
| fast-string-truncated-width | npm | MIT | dev | Yes |
| fast-string-width | npm | MIT | dev | Yes |
| fast-wrap-ansi | npm | MIT | dev | Yes |
| fastq | npm | ISC | dev | Yes |
| fdir | npm | MIT | dev | Yes |
| file-entry-cache | npm | MIT | dev | Yes |
| fill-range | npm | MIT | dev | Yes |
| find-up | npm | MIT | dev | Yes |
| flat-cache | npm | MIT | dev | Yes |
| flatted | npm | ISC | dev | Yes |
| for-each | npm | MIT | dev | Yes |
| fraction.js | npm | MIT | dev | Yes |
| function-bind | npm | MIT | dev | Yes |
| function.prototype.name | npm | MIT | dev | Yes |
| functions-have-names | npm | MIT | dev | Yes |
| generator-function | npm | MIT | dev | Yes |
| gensync | npm | MIT | runtime | Yes |
| get-caller-file | npm | ISC | dev | Yes |
| get-intrinsic | npm | MIT | dev | Yes |
| get-nonce | npm | MIT | runtime | Yes |
| get-proto | npm | MIT | dev | Yes |
| get-symbol-description | npm | MIT | dev | Yes |
| get-tsconfig | npm | MIT | dev | Yes |
| glob-parent | npm | ISC | dev | Yes |
| globals | npm | MIT | dev | Yes |
| globalthis | npm | MIT | dev | Yes |
| gopd | npm | MIT | dev | Yes |
| graceful-fs | npm | ISC | dev | Yes |
| graphql | npm | MIT | dev | Yes |
| has-bigints | npm | MIT | dev | Yes |
| has-flag | npm | MIT | dev | Yes |
| has-property-descriptors | npm | MIT | dev | Yes |
| has-proto | npm | MIT | dev | Yes |
| has-symbols | npm | MIT | dev | Yes |
| has-tostringtag | npm | MIT | dev | Yes |
| hasown | npm | MIT | dev | Yes |
| hast-util-to-jsx-runtime | npm | MIT | runtime | Yes |
| hast-util-whitespace | npm | MIT | runtime | Yes |
| headers-polyfill | npm | MIT | dev | Yes |
| hermes-estree | npm | MIT | dev | Yes |
| hermes-parser | npm | MIT | dev | Yes |
| html-encoding-sniffer | npm | MIT | dev | Yes |
| html-url-attributes | npm | MIT | runtime | Yes |
| https-proxy-agent | npm | MIT | dev | Yes |
| ignore | npm | MIT | dev | Yes |
| immer | npm | MIT | runtime | Yes |
| import-fresh | npm | MIT | dev | Yes |
| imurmurhash | npm | MIT | dev | Yes |
| indent-string | npm | MIT | dev | Yes |
| index-to-position | npm | MIT | dev | Yes |
| inline-style-parser | npm | MIT | runtime | Yes |
| internal-slot | npm | MIT | dev | Yes |
| internmap | npm | ISC | runtime | Yes |
| is-alphabetical | npm | MIT | runtime | Yes |
| is-alphanumerical | npm | MIT | runtime | Yes |
| is-array-buffer | npm | MIT | dev | Yes |
| is-async-function | npm | MIT | dev | Yes |
| is-bigint | npm | MIT | dev | Yes |
| is-boolean-object | npm | MIT | dev | Yes |
| is-bun-module | npm | MIT | dev | Yes |
| is-callable | npm | MIT | dev | Yes |
| is-core-module | npm | MIT | dev | Yes |
| is-data-view | npm | MIT | dev | Yes |
| is-date-object | npm | MIT | dev | Yes |
| is-decimal | npm | MIT | runtime | Yes |
| is-extglob | npm | MIT | dev | Yes |
| is-finalizationregistry | npm | MIT | dev | Yes |
| is-fullwidth-code-point | npm | MIT | dev | Yes |
| is-generator-function | npm | MIT | dev | Yes |
| is-glob | npm | MIT | dev | Yes |
| is-hexadecimal | npm | MIT | runtime | Yes |
| is-map | npm | MIT | dev | Yes |
| is-negative-zero | npm | MIT | dev | Yes |
| is-node-process | npm | MIT | dev | Yes |
| is-number | npm | MIT | dev | Yes |
| is-number-object | npm | MIT | dev | Yes |
| is-plain-obj | npm | MIT | runtime | Yes |
| is-potential-custom-element-name | npm | MIT | dev | Yes |
| is-regex | npm | MIT | dev | Yes |
| is-set | npm | MIT | dev | Yes |
| is-shared-array-buffer | npm | MIT | dev | Yes |
| is-string | npm | MIT | dev | Yes |
| is-symbol | npm | MIT | dev | Yes |
| is-typed-array | npm | MIT | dev | Yes |
| is-weakmap | npm | MIT | dev | Yes |
| is-weakref | npm | MIT | dev | Yes |
| is-weakset | npm | MIT | dev | Yes |
| isarray | npm | MIT | dev | Yes |
| isexe | npm | ISC | dev | Yes |
| iterator.prototype | npm | MIT | dev | Yes |
| jiti | npm | MIT | dev | Yes |
| js-levenshtein | npm | MIT | dev | Yes |
| js-tokens | npm | MIT | runtime | Yes |
| js-yaml | npm | MIT | dev | Yes |
| jsdom | npm | MIT | dev | Yes |
| jsesc | npm | MIT | runtime | Yes |
| json-buffer | npm | MIT | dev | Yes |
| json-schema-traverse | npm | MIT | dev | Yes |
| json-stable-stringify-without-jsonify | npm | MIT | dev | Yes |
| json5 | npm | MIT | runtime | Yes |
| jsx-ast-utils | npm | MIT | dev | Yes |
| keyv | npm | MIT | dev | Yes |
| language-subtag-registry | npm | CC0-1.0 | dev | Yes |
| language-tags | npm | MIT | dev | Yes |
| levn | npm | MIT | dev | Yes |
| lightningcss | npm | MPL-2.0 | dev | Yes — weak copyleft (file-level), flagged |
| locate-path | npm | MIT | dev | Yes |
| lodash.merge | npm | MIT | dev | Yes |
| longest-streak | npm | MIT | runtime | Yes |
| loose-envify | npm | MIT | dev | Yes |
| lru-cache | npm | ISC | runtime | Yes |
| lucide-react | npm | ISC | runtime | Yes |
| lz-string | npm | MIT | dev | Yes |
| magic-string | npm | MIT | dev | Yes |
| markdown-table | npm | MIT | runtime | Yes |
| math-intrinsics | npm | MIT | dev | Yes |
| mdast-util-find-and-replace | npm | MIT | runtime | Yes |
| mdast-util-from-markdown | npm | MIT | runtime | Yes |
| mdast-util-gfm | npm | MIT | runtime | Yes |
| mdast-util-gfm-autolink-literal | npm | MIT | runtime | Yes |
| mdast-util-gfm-footnote | npm | MIT | runtime | Yes |
| mdast-util-gfm-strikethrough | npm | MIT | runtime | Yes |
| mdast-util-gfm-table | npm | MIT | runtime | Yes |
| mdast-util-gfm-task-list-item | npm | MIT | runtime | Yes |
| mdast-util-mdx-expression | npm | MIT | runtime | Yes |
| mdast-util-mdx-jsx | npm | MIT | runtime | Yes |
| mdast-util-mdxjs-esm | npm | MIT | runtime | Yes |
| mdast-util-phrasing | npm | MIT | runtime | Yes |
| mdast-util-to-hast | npm | MIT | runtime | Yes |
| mdast-util-to-markdown | npm | MIT | runtime | Yes |
| mdast-util-to-string | npm | MIT | runtime | Yes |
| mdn-data | npm | CC0-1.0 | dev | Yes |
| merge2 | npm | MIT | dev | Yes |
| micromark | npm | MIT | runtime | Yes |
| micromark-core-commonmark | npm | MIT | runtime | Yes |
| micromark-extension-gfm | npm | MIT | runtime | Yes |
| micromark-extension-gfm-autolink-literal | npm | MIT | runtime | Yes |
| micromark-extension-gfm-footnote | npm | MIT | runtime | Yes |
| micromark-extension-gfm-strikethrough | npm | MIT | runtime | Yes |
| micromark-extension-gfm-table | npm | MIT | runtime | Yes |
| micromark-extension-gfm-tagfilter | npm | MIT | runtime | Yes |
| micromark-extension-gfm-task-list-item | npm | MIT | runtime | Yes |
| micromark-factory-destination | npm | MIT | runtime | Yes |
| micromark-factory-label | npm | MIT | runtime | Yes |
| micromark-factory-space | npm | MIT | runtime | Yes |
| micromark-factory-title | npm | MIT | runtime | Yes |
| micromark-factory-whitespace | npm | MIT | runtime | Yes |
| micromark-util-character | npm | MIT | runtime | Yes |
| micromark-util-chunked | npm | MIT | runtime | Yes |
| micromark-util-classify-character | npm | MIT | runtime | Yes |
| micromark-util-combine-extensions | npm | MIT | runtime | Yes |
| micromark-util-decode-numeric-character-reference | npm | MIT | runtime | Yes |
| micromark-util-decode-string | npm | MIT | runtime | Yes |
| micromark-util-encode | npm | MIT | runtime | Yes |
| micromark-util-html-tag-name | npm | MIT | runtime | Yes |
| micromark-util-normalize-identifier | npm | MIT | runtime | Yes |
| micromark-util-resolve-all | npm | MIT | runtime | Yes |
| micromark-util-sanitize-uri | npm | MIT | runtime | Yes |
| micromark-util-subtokenize | npm | MIT | runtime | Yes |
| micromark-util-symbol | npm | MIT | runtime | Yes |
| micromark-util-types | npm | MIT | runtime | Yes |
| micromatch | npm | MIT | dev | Yes |
| min-indent | npm | MIT | dev | Yes |
| minimatch | npm | BlueOak-1.0.0 | dev | Yes |
| minimist | npm | MIT | dev | Yes |
| ms | npm | MIT | runtime | Yes |
| msw | npm | MIT | dev | Yes |
| mute-stream | npm | ISC | dev | Yes |
| nanoid | npm | MIT | runtime | Yes |
| napi-postinstall | npm | MIT | dev | Yes |
| natural-compare | npm | MIT | dev | Yes |
| next | npm | MIT | runtime | Yes |
| next-themes | npm | MIT | runtime | Yes |
| node-exports-info | npm | MIT | dev | Yes |
| node-releases | npm | MIT | runtime | Yes |
| object-assign | npm | MIT | dev | Yes |
| object-inspect | npm | MIT | dev | Yes |
| object-keys | npm | MIT | dev | Yes |
| object.assign | npm | MIT | dev | Yes |
| object.entries | npm | MIT | dev | Yes |
| object.fromentries | npm | MIT | dev | Yes |
| object.groupby | npm | MIT | dev | Yes |
| object.values | npm | MIT | dev | Yes |
| obug | npm | MIT | dev | Yes |
| openapi-typescript | npm | MIT | dev | Yes |
| optionator | npm | MIT | dev | Yes |
| outvariant | npm | MIT | dev | Yes |
| own-keys | npm | MIT | dev | Yes |
| p-limit | npm | MIT | dev | Yes |
| p-locate | npm | MIT | dev | Yes |
| parent-module | npm | MIT | dev | Yes |
| parse-entities | npm | MIT | runtime | Yes |
| parse-json | npm | MIT | dev | Yes |
| parse5 | npm | MIT | dev | Yes |
| path-exists | npm | MIT | dev | Yes |
| path-key | npm | MIT | dev | Yes |
| path-parse | npm | MIT | dev | Yes |
| path-to-regexp | npm | MIT | dev | Yes |
| pathe | npm | MIT | dev | Yes |
| picocolors | npm | ISC | runtime | Yes |
| picomatch | npm | MIT | dev | Yes |
| playwright | npm | Apache-2.0 | runtime | Yes |
| playwright-core | npm | Apache-2.0 | runtime | Yes |
| pluralize | npm | MIT | dev | Yes |
| possible-typed-array-names | npm | MIT | dev | Yes |
| postcss | npm | MIT | runtime | Yes |
| postcss-selector-parser | npm | MIT | dev | Yes |
| postcss-value-parser | npm | MIT | dev | Yes |
| prelude-ls | npm | MIT | dev | Yes |
| prettier | npm | MIT | dev | Yes |
| pretty-format | npm | MIT | dev | Yes |
| prism-react-renderer | npm | MIT | runtime | Yes |
| prop-types | npm | MIT | dev | Yes |
| property-information | npm | MIT | runtime | Yes |
| punycode | npm | MIT | dev | Yes |
| queue-microtask | npm | MIT | dev | Yes |
| react | npm | MIT | runtime | Yes |
| react-dom | npm | MIT | runtime | Yes |
| react-hook-form | npm | MIT | runtime | Yes |
| react-is | npm | MIT | runtime | Yes |
| react-markdown | npm | MIT | runtime | Yes |
| react-redux | npm | MIT | runtime | Yes |
| react-remove-scroll | npm | MIT | runtime | Yes |
| react-remove-scroll-bar | npm | MIT | runtime | Yes |
| react-style-singleton | npm | MIT | runtime | Yes |
| recharts | npm | MIT | runtime | Yes |
| redent | npm | MIT | dev | Yes |
| redux | npm | MIT | runtime | Yes |
| redux-thunk | npm | MIT | runtime | Yes |
| reflect.getprototypeof | npm | MIT | dev | Yes |
| regexp-tree | npm | MIT | dev | Yes |
| regexp.prototype.flags | npm | MIT | dev | Yes |
| remark-gfm | npm | MIT | runtime | Yes |
| remark-parse | npm | MIT | runtime | Yes |
| remark-rehype | npm | MIT | runtime | Yes |
| remark-stringify | npm | MIT | runtime | Yes |
| require-directory | npm | MIT | dev | Yes |
| require-from-string | npm | MIT | dev | Yes |
| reselect | npm | MIT | runtime | Yes |
| resolve | npm | MIT | dev | Yes |
| resolve-from | npm | MIT | dev | Yes |
| resolve-pkg-maps | npm | MIT | dev | Yes |
| rettime | npm | MIT | dev | Yes |
| reusify | npm | MIT | dev | Yes |
| rolldown | npm | MIT | dev | Yes |
| run-parallel | npm | MIT | dev | Yes |
| safe-array-concat | npm | MIT | dev | Yes |
| safe-push-apply | npm | MIT | dev | Yes |
| safe-regex | npm | MIT | dev | Yes |
| safe-regex-test | npm | MIT | dev | Yes |
| saxes | npm | ISC | dev | Yes |
| scheduler | npm | MIT | runtime | Yes |
| semver | npm | ISC | runtime | Yes |
| set-cookie-parser | npm | MIT | dev | Yes |
| set-function-length | npm | MIT | dev | Yes |
| set-function-name | npm | MIT | dev | Yes |
| set-proto | npm | MIT | dev | Yes |
| sharp | npm | Apache-2.0 | runtime | Yes |
| shebang-command | npm | MIT | dev | Yes |
| shebang-regex | npm | MIT | dev | Yes |
| side-channel | npm | MIT | dev | Yes |
| side-channel-list | npm | MIT | dev | Yes |
| side-channel-map | npm | MIT | dev | Yes |
| side-channel-weakmap | npm | MIT | dev | Yes |
| siginfo | npm | ISC | dev | Yes |
| signal-exit | npm | ISC | dev | Yes |
| sonner | npm | MIT | runtime | Yes |
| source-map-js | npm | BSD-3-Clause | runtime | Yes |
| space-separated-tokens | npm | MIT | runtime | Yes |
| stable-hash | npm | MIT | dev | Yes |
| stackback | npm | MIT | dev | Yes |
| statuses | npm | MIT | dev | Yes |
| std-env | npm | MIT | dev | Yes |
| stop-iteration-iterator | npm | MIT | dev | Yes |
| strict-event-emitter | npm | MIT | dev | Yes |
| string-width | npm | MIT | dev | Yes |
| string.prototype.includes | npm | MIT | dev | Yes |
| string.prototype.matchall | npm | MIT | dev | Yes |
| string.prototype.repeat | npm | MIT | dev | Yes |
| string.prototype.trim | npm | MIT | dev | Yes |
| string.prototype.trimend | npm | MIT | dev | Yes |
| string.prototype.trimstart | npm | MIT | dev | Yes |
| stringify-entities | npm | MIT | runtime | Yes |
| strip-ansi | npm | MIT | dev | Yes |
| strip-bom | npm | MIT | dev | Yes |
| strip-indent | npm | MIT | dev | Yes |
| strip-json-comments | npm | MIT | dev | Yes |
| style-to-js | npm | MIT | runtime | Yes |
| style-to-object | npm | MIT | runtime | Yes |
| styled-jsx | npm | MIT | runtime | Yes |
| supports-color | npm | MIT | runtime | Yes |
| supports-preserve-symlinks-flag | npm | MIT | dev | Yes |
| symbol-tree | npm | MIT | dev | Yes |
| tagged-tag | npm | MIT | dev | Yes |
| tailwind-merge | npm | MIT | runtime | Yes |
| tailwindcss | npm | MIT | dev | Yes |
| tapable | npm | MIT | dev | Yes |
| tiny-invariant | npm | MIT | runtime | Yes |
| tinybench | npm | MIT | dev | Yes |
| tinyexec | npm | MIT | dev | Yes |
| tinyglobby | npm | MIT | dev | Yes |
| tinyrainbow | npm | MIT | dev | Yes |
| tldts | npm | MIT | dev | Yes |
| tldts-core | npm | MIT | dev | Yes |
| to-regex-range | npm | MIT | dev | Yes |
| tough-cookie | npm | BSD-3-Clause | dev | Yes |
| tr46 | npm | MIT | dev | Yes |
| trim-lines | npm | MIT | runtime | Yes |
| trough | npm | MIT | runtime | Yes |
| ts-api-utils | npm | MIT | dev | Yes |
| tsconfig-paths | npm | MIT | dev | Yes |
| tslib | npm | 0BSD | runtime | Yes |
| type-check | npm | MIT | dev | Yes |
| type-fest | npm | (MIT OR CC0-1.0) | dev | Yes |
| typed-array-buffer | npm | MIT | dev | Yes |
| typed-array-byte-length | npm | MIT | dev | Yes |
| typed-array-byte-offset | npm | MIT | dev | Yes |
| typed-array-length | npm | MIT | dev | Yes |
| typescript | npm | Apache-2.0 | dev | Yes |
| typescript-eslint | npm | MIT | dev | Yes |
| unbox-primitive | npm | MIT | dev | Yes |
| undici | npm | MIT | dev | Yes |
| undici-types | npm | MIT | dev | Yes |
| unified | npm | MIT | runtime | Yes |
| unist-util-is | npm | MIT | runtime | Yes |
| unist-util-position | npm | MIT | runtime | Yes |
| unist-util-stringify-position | npm | MIT | runtime | Yes |
| unist-util-visit | npm | MIT | runtime | Yes |
| unist-util-visit-parents | npm | MIT | runtime | Yes |
| unrs-resolver | npm | MIT | dev | Yes |
| until-async | npm | MIT | dev | Yes |
| update-browserslist-db | npm | MIT | runtime | Yes |
| uri-js | npm | BSD-2-Clause | dev | Yes |
| uri-js-replace | npm | MIT | dev | Yes |
| use-callback-ref | npm | MIT | runtime | Yes |
| use-sidecar | npm | MIT | runtime | Yes |
| use-sync-external-store | npm | MIT | runtime | Yes |
| util-deprecate | npm | MIT | dev | Yes |
| vfile | npm | MIT | runtime | Yes |
| vfile-message | npm | MIT | runtime | Yes |
| victory-vendor | npm | MIT AND ISC | runtime | Yes |
| vite | npm | MIT | dev | Yes |
| vitest | npm | MIT | dev | Yes |
| w3c-xmlserializer | npm | MIT | dev | Yes |
| webidl-conversions | npm | BSD-2-Clause | dev | Yes |
| whatwg-mimetype | npm | MIT | dev | Yes |
| whatwg-url | npm | MIT | dev | Yes |
| which | npm | ISC | dev | Yes |
| which-boxed-primitive | npm | MIT | dev | Yes |
| which-builtin-type | npm | MIT | dev | Yes |
| which-collection | npm | MIT | dev | Yes |
| which-typed-array | npm | MIT | dev | Yes |
| why-is-node-running | npm | MIT | dev | Yes |
| word-wrap | npm | MIT | dev | Yes |
| wrap-ansi | npm | MIT | dev | Yes |
| xml-name-validator | npm | Apache-2.0 | dev | Yes |
| xmlchars | npm | MIT | dev | Yes |
| y18n | npm | ISC | dev | Yes |
| yallist | npm | ISC | runtime | Yes |
| yaml-ast-parser | npm | Apache-2.0 | dev | Yes |
| yargs | npm | MIT | dev | Yes |
| yargs-parser | npm | ISC | dev | Yes |
| yocto-queue | npm | MIT | dev | Yes |
| zod | npm | MIT | runtime | Yes |
| zod-validation-error | npm | MIT | dev | Yes |
| zwitch | npm | MIT | runtime | Yes |

## Summary

- Total dependencies in locked closure: **782** (323 shipped, 459 dev-only).
- Non-permissive licenses: **9** (all adjudicated above).
