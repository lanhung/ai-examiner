# v0.8 Increment A Verification Results

## Scope

Increment A implements the contract boundary for versioned scenario templates:

```text
bounded YAML or JSON
-> structural validation
-> semantic validation
-> deterministic compilation
-> immutable fingerprint
-> compact built-in catalog
```

This increment does not bind templates to sessions or change active examiner
behavior.

## Versions

```text
package                 0.8.0.dev0
schema                  1.0
validator               template-validator-v1
compiler                template-compiler-v1
built-in template       academic.thesis_defense@1.0.0
built-in fingerprint    sha256:9508c3957ed73daecff120d892f291116f819d0f9d26f3896f1a7cc7ef0b7b9c
```

## Deterministic checks

- Reordered mapping keys produce the same compiled fingerprint.
- Identical source and overrides produce byte-equivalent canonical JSON.
- Accepted overrides are recorded separately from defaults.
- Unknown, locked, wrong-type and out-of-range overrides fail before runtime.
- Template weights, references, capabilities and safety invariants are validated
  without a model call.
- The thesis-defense compatibility projection matches v0.7 session defaults.

## Parser and trust checks

- YAML aliases are rejected.
- Duplicate JSON and YAML keys are rejected.
- Non-string map keys and non-finite floats are rejected.
- Source documents are bounded by byte, depth, node, collection and string limits.
- Built-in loading rejects path traversal and uses an explicit source-controlled
  filename allowlist.
- The public catalog omits compiled policy internals.
- Public import and trust promotion remain disabled.

## Packaging

`uv build --wheel` includes:

```text
ai_examiner/templates/builtin/academic.thesis_defense.v1.yaml
```

This proves a Wheel deployment can load the same reviewed built-in source as a
source checkout.

## Repository gates

```text
pytest                       76 passed
ruff                         passed
JavaScript syntax            passed
git diff --check             passed
tracked-source secret scan   passed
Docker Compose config        not run (Docker unavailable on this host)
```

The successful Windows pytest process still emits the existing asynchronous
generator cleanup `access violation` text after the final result. This is recorded
as platform shutdown noise rather than silently omitted.

## Release decision

Increment A may be committed to `develop/v0.8.0` after the full repository gates
pass. It must not be tagged as `v0.8.0`, merged to `main` or deployed as the stable
line. The next implementation unit is WP-03 persistence and immutable lifecycle
storage.
