---
id: annotation_transformer
kind: model_family
status: active
aliases:
- annotation_transformer
converted: true
depends_on:
- foundry.layers
tests:
  unit:
  - tests
---

# annotation_transformer

The annotation transformer (AT) encodes a protein's annotations as tokens of the Annotation
Vocabulary. It is the B-side encoder of Atlas's CAMP model, published as `Synthyra/AT-Base` with
`model_type: annotation_transformer`. Its layers are `foundry.layers`'; this family is the model
around them.

## Public surface

- `annotation_transformer`: `AnnotationTransformerConfig` with its presets (`PRESETS`, and
  `AnnotationTransformerConfig.from_preset`: `at_base`, `camp_at`, `camp_at_large`),
  `AnnotationTransformer` with its output class `AnnotationTransformerOutput`, and
  `register_with_auto_classes`, which lets `AutoModel.from_pretrained("Synthyra/AT-Base")` find
  the classes, since the repository has no `auto_map`.
- `forward(input_ids, attention_mask)` returns `last_hidden_state` `(b, l, d)`,
  `pooler_output` `(b, d)`, and, with `return_lm_logits=True`, `logits` `(b, l, v)`.

Loading under Transformers 5 depends on `_init_weights` rebuilding the rotary tables, which no
checkpoint holds. The tests guard it.

## Who imports it

- `sequence_gradient`: `models.atlas.runtime.annotation_transformer` re-exports this family, so
  its Atlas adapter and reproducibility audit keep their import path.
- `atlas` re-exports this family from `models/annotation_transformer/`, since 2026-09-26, and synth
  reaches it through the Atlas it vendors. Both list `annotation_transformer` in
  `github.includes`. Atlas's own `config.py` and `modeling.py` are retired, and its four layer
  modules were already shims onto `foundry.layers`, so nothing of the model was duplicated twice.
  The switch was checked before the files were retired: from the same seed, both build 29
  parameters under the same names and shapes, the family loads Atlas's state dict, and with a
  padded mask the two return `last_hidden_state` and `pooler_output` that differ by exactly zero.
  That is what keeps `Synthyra/AT-Base` loading with unchanged keys. Atlas's
  `tests/test_pretrained_loading.py` no longer repeats this family's round trip; it checks that its
  shim re-exports the family and registers the model type, which is the part that is Atlas's.
- embedding_translation's `models/annotation_transformer.py` is a variant it trains jointly with
  its translator, whose model returns the pooled vector. It stays its own, as
  [the decision](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/docs/decisions/interaction/atlas/2026-09-24_annotation_transformer_model_family.md) says.

Each projection that imports the family vendors this directory through `github.includes`. Edit it
here, not in a projection.

## Tests

`ws test --projects annotation_transformer` runs `tests/` on CPU: the loading round trip against
NaN-filled allocations, the rebuilt rotary tables, the forward's shapes in both return forms, the
Auto-class registration, and the presets.

## Pretraining

`pretrain.py` trains the family on the token lists of an Annotation Vocabulary release (`python -m annotation_transformer.pretrain
--release <dir> --output <dir> --experiment <id>`): masked-token prediction at 15 percent (80/10/10), the language-model head run
only at hidden positions, AdamW with warmup and cosine decay, bf16. The checkpoint is chosen on validation loss (`best/`), and when
training ends `best/` is scored once on validation and once on test at the same fixed hidden positions, beside the train-frequency
prior and a random-weight control, with 95 percent cluster-bootstrap intervals, into `evaluation.json`; a second evaluation of a run
is refused, so test is read once. `--evaluate-only` scores an existing `best/`, and `--hub-repo` pushes `best/` to the root of a
private repository with the card files in one commit (`--push-only` repeats the push). The vocabulary size, the `<pad>` and the
`<mask>` ids come from the release's `vocabulary.parquet`, because in a release made by `annotation_vocabulary.experimental` token zero
is a real term and the special tokens follow the biological ones. It never reads `calibration`. `Synthyra/AT-Base` was trained on the earlier vocabulary
(88,282 tokens) and does not load against a release's tokens.
