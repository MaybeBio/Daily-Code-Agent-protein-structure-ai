# MolSysMT Developer Guide

`devguide/` contains the maintained engineering and scientific-development
contract for MolSysMT. It is not a session log and it is not a claim that every
described capability is implemented.

## How to interpret this directory

Documents have one of four roles:

1. **Normative** documents define current invariants, interfaces, or policies.
2. **Operational** documents describe maintained development and validation
   workflows.
3. **Pending** documents record unresolved bugs or proposals. They are not part
   of the implemented contract.
4. **Archived** documents preserve dated assessments and release planning. They
   provide historical context only.

When documents disagree, use this order of authority:

1. repository-wide and local `AGENTS.md` instructions;
2. current code plus executable tests;
3. normative documents listed below;
4. operational documents;
5. pending and archived material.

An implementation-status statement is trustworthy only when it points to code,
tests, or reproducible validation evidence. Dated benchmark numbers are
observations from a particular environment, not timeless performance guarantees.

See [DOCUMENT_POLICY.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/DOCUMENT_POLICY.md) for maintenance and status rules.

## Start here

For a new session on the path to 1.0, start at
[Resume from here](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_1_0_status.md#resume-from-here). That section
identifies the next decision, its owner and the evidence needed to proceed.

- Find the reviewed source SHAs, provisional builds and proposed dispatch
  refs in the [candidate-input packet](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pre_1_0_contract_closeout.md#molsysviewer-confirmation).
- Check whether a new finding belongs in 1.0 against the
  [frozen scope](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_1_0_scope.md).
- Verify the required checks and the conditions for Diego's review in the
  [exact-commit release gate](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_gate.md) and
  [technical handoff plan](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/technical_handoff_for_1_0_documentation_review.md).

The [Python 3.14 paired-support checkpoint](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/python_3_14_checkpoint.md)
preserves the earlier published pair and development baseline. For
MolSysViewer-owned Qt and user-workflow gates, see `uibcdf/molsysviewer#109`,
`uibcdf/molsysviewer#112` and `uibcdf/molsysviewer#315`.

For the correction sequence following the 6 November review, use the
[pre-1.0 robustness audit and action plan](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pre_1_0_robustness_audit_20261106.md).
It retains the dated findings and tracks bounded work under #334; candidate
selection and release qualification remain in the execution ledger.

Read these documents in order when first working on MolSysMT:

1. [Core specification](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/CORE_SPECIFICATION.md) — native model, hierarchy, and
   package boundaries.
2. [Public API surface](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/api_surface.md) — stability classification and public
   contract.
3. [Interfaces](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/INTERFACES.md) — form-agnostic behavior and I/O boundaries.
4. [Forms and conversions](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/forms_and_conversions.md) — adapter and conversion
   semantics.
5. [Testing strategy](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/testing_strategy.md) — evidence required for a supported
   claim.
6. [Scientific validation](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/scientific_validation.md) — independent evidence,
   conventions, and tolerance governance.
7. [Diagnostics](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/DIAGNOSTICS.md) and [error policy](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/error_policy.md) — failure
   and observability behavior.
8. [Performance and JIT](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/performance_and_jit.md) and
   [scalability](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/SCALABILITY.md) — trusted kernels and heavy trajectories.

## Maintained normative documents

### Architecture and data model

- [CORE_SPECIFICATION.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/CORE_SPECIFICATION.md)
- [ALGORITHMS.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/ALGORITHMS.md)
- [INTERFACES.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/INTERFACES.md)
- [api_surface.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/api_surface.md)
- [BUILDER_API.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/BUILDER_API.md)
- [BUILD_ECOSYSTEM.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/BUILD_ECOSYSTEM.md)
- [declarative_serialization_forms.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/declarative_serialization_forms.md)
- [h5msm_format.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/h5msm_format.md)
- [forms_and_conversions.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/forms_and_conversions.md)
- [native_binding_site_membership_contract.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/native_binding_site_membership_contract.md)
  — checked molecular membership/maps offered to BindingMT and caller preconditions.
- [form_adapter_implementation.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/form_adapter_implementation.md)

### Scientific construction and analysis

- [physchem_query_contract.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/physchem_query_contract.md) — tabulated property axes, selection syntax and output contracts.
- [scientific_validation.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/scientific_validation.md)
- [scientific_evidence_matrix.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/scientific_evidence_matrix.md) — generated
  status view backed by the executable Scientific Truth evidence registry.
- [structure_preparation_pipeline.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/structure_preparation_pipeline.md)
- [chemical_group_database_generation.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/chemical_group_database_generation.md)
  — explicit CCD/RTP/JSON inputs, reader schemas and regeneration provenance.
- [performance_and_jit.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/performance_and_jit.md)
- [rust_kernel_optimization_guide.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/rust_kernel_optimization_guide.md) — the
  measured method for optimising the Rust kernels, including what was tried and
  did not work, and why the wheel stays a portable baseline build.
- [SCALABILITY.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/SCALABILITY.md)
- [gpu_acceleration.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/gpu_acceleration.md) — design and capability map; each
  backend claim must still be confirmed by its tests.

### Reliability and governance

- [testing_strategy.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/testing_strategy.md)
- [testing_form_adapters.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/testing_form_adapters.md)
- [parallel_test_warning_counts.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/parallel_test_warning_counts.md)
- [devtools_and_ci.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/devtools_and_ci.md)
- [DIAGNOSTICS.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/DIAGNOSTICS.md)
- [error_policy.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/error_policy.md)
- [deprecation_policy.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/deprecation_policy.md)
- [digestion_and_dependencies.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/digestion_and_dependencies.md)
- [dependency_contract_audit.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/dependency_contract_audit.md) — authoritative
  runtime floors, secondary-route audit, and the dependency-change procedure.
- [support_tier_protocol.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/support_tier_protocol.md)
- [support_tiers.ipynb](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/support_tiers.ipynb) — executable report, not a second
  tier registry.

### Documentation, education, and visualization

- [documentation_sync.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/documentation_sync.md)
- [notebook_compilation_and_visualization.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/notebook_compilation_and_visualization.md) — normative specification for notebook pre-execution, timestamp tracking, and MolSysViewer integration.
- [course_structure.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/course_structure.md)
- [viewers_and_visualization.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/viewers_and_visualization.md)
- [Native MolSysViewer integration](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/molsysviewer_addon.md)
- [Receiving the independent chemical domains](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/chemical_states_migration.md) — unreleased source-cutover guidance for clients; installed qualification remains separate.

### Strategy and measurements

- [competitive_landscape_and_vision.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/competitive_landscape_and_vision.md)
- [roadmap.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/roadmap.md)
- [benchmarking/README.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/benchmarking/README.md)
- [stabilization_handoff_2026-09-19.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/stabilization_handoff_2026-09-19.md) — dated
  operational ordering of the active installability, CI, form-contract and Ruff work;
  the linked issues remain authoritative for state.

### Release operations

- [Python 3.14 paired-support checkpoint](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/python_3_14_checkpoint.md) — dated
  evidence, missing gates, and the next handoff for MolSysMT, MolSysViewer,
  and their Qt-family dependency stack.
- [release_1_0_status.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_1_0_status.md) — live phase/stage status and
  evidence ledger for the remaining 1.0 work.
- [pre_1_0_contract_closeout.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pre_1_0_contract_closeout.md) — owner returns,
  exact candidate inputs and installed-pair evidence requirements.
- [release_1_0_scope.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_1_0_scope.md) — accepted feature freeze, finite
  stabilization queue and preserved post-1.0 issues.
- [technical_handoff_for_1_0_documentation_review.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/technical_handoff_for_1_0_documentation_review.md)
  — accepted destination, finite work order and criteria for leaving only the
  maintainer's documentation review before the final release decision.
- [release_gate.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_gate.md) — exact-commit checklist required before
  tagging.
- [release_and_citation.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/release_and_citation.md) — GitHub Release, Zenodo,
  concept/version DOI, citation metadata, and post-release verification contract.
- [release_1_0_execution_plan.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pending_proposals/release_1_0_execution_plan.md)
  — accepted ordering, weights, exit gates, and stop conditions.

Strategic documents describe direction. They do not override the API, testing,
dependency, or scientific contracts above.

## Work queues

[reporting_protocol.md](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/reporting_protocol.md) governs how an entry enters these
queues, how it is tracked on the issue board, and how it closes. Every entry carries
front matter that the validator checks and the queue indexes are generated from.

- [Pending bugs](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pending_bugs/README.md) contain reproduced or suspected defects.
- [Pending proposals](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pending_proposals/README.md) contain ideas awaiting a
  decision or implementation.
- [Documentation bugs](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pending_bugs/docs/README.md) and
  [documentation proposals](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/pending_proposals/docs/README.md) contain the same two
  kinds of entry for work whose deliverable is user-facing documentation rather
  than code.
- [Archived material](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/archive/README.md) contains dated audits, assessments, and
  release checkpoints.
- [Library engineering and scientific audit — 4 November 2026](https://github.com/uibcdf/molsysmt/blob/HEAD/devguide/archive/assessments/library_engineering_and_scientific_audit_20261104.md)
  preserves a dated review of architecture, scientific evidence and improvement
  priorities; it is not the live implementation or release-status ledger.

Moving a document into a pending or archived directory changes its documentary
status; it does not close a bug, accept a proposal, or certify an implementation.

## Essential external guides

The repository root contains required integration guidance that complements this
directory:

- [`SMONITOR_GUIDE.md`](https://github.com/uibcdf/molsysmt/blob/HEAD/SMONITOR_GUIDE.md)
- [`ARGDIGEST_GUIDE.md`](https://github.com/uibcdf/molsysmt/blob/HEAD/ARGDIGEST_GUIDE.md)
- [`PYUNITWIZARD_GUIDE.md`](https://github.com/uibcdf/molsysmt/blob/HEAD/PYUNITWIZARD_GUIDE.md)
- [`DEPDIGEST_GUIDE.md`](https://github.com/uibcdf/molsysmt/blob/HEAD/DEPDIGEST_GUIDE.md)

## Maintenance check

Run the developer-guide validator after changing this directory:

```bash
python devtools/scripts/validate_devguide.py
```

The validator checks local Markdown targets, forbidden machine-specific links,
and references to retired document names. It does not prove that scientific or
implementation claims are true; those require tests and reproducible evidence.
