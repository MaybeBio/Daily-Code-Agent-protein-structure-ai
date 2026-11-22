# Report Phase and Statistics

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/results.md](docs/results.md)
- [src/fastmdxplora/batch/sweep.py](src/fastmdxplora/batch/sweep.py)
- [src/fastmdxplora/deposit.py](src/fastmdxplora/deposit.py)
- [src/fastmdxplora/gui/files_page.py](src/fastmdxplora/gui/files_page.py)
- [src/fastmdxplora/gui/records_answer.py](src/fastmdxplora/gui/records_answer.py)
- [src/fastmdxplora/gui/static/files-actions.js](src/fastmdxplora/gui/static/files-actions.js)
- [src/fastmdxplora/remedies.py](src/fastmdxplora/remedies.py)
- [src/fastmdxplora/report/bundle.py](src/fastmdxplora/report/bundle.py)
- [src/fastmdxplora/report/convergence.py](src/fastmdxplora/report/convergence.py)
- [src/fastmdxplora/report/document.py](src/fastmdxplora/report/document.py)
- [src/fastmdxplora/report/methods.py](src/fastmdxplora/report/methods.py)
- [src/fastmdxplora/report/pdf.py](src/fastmdxplora/report/pdf.py)
- [src/fastmdxplora/report/run.py](src/fastmdxplora/report/run.py)
- [src/fastmdxplora/report/slides.py](src/fastmdxplora/report/slides.py)
- [src/fastmdxplora/simulation/sampling_ask.py](src/fastmdxplora/simulation/sampling_ask.py)
- [src/fastmdxplora/statistics.py](src/fastmdxplora/statistics.py)
- [src/fastmdxplora/study_files.py](src/fastmdxplora/study_files.py)
- [tests/test_a_piece_stopped_before_its_checkpoint_counts_nothing.py](tests/test_a_piece_stopped_before_its_checkpoint_counts_nothing.py)
- [tests/test_a_refusal_has_a_name.py](tests/test_a_refusal_has_a_name.py)
- [tests/test_a_run_is_held_to_what_its_plan_said.py](tests/test_a_run_is_held_to_what_its_plan_said.py)
- [tests/test_a_series_shows_how_it_converged.py](tests/test_a_series_shows_how_it_converged.py)
- [tests/test_a_stopped_run_ends_on_a_frame.py](tests/test_a_stopped_run_ends_on_a_frame.py)
- [tests/test_a_study_is_deposited_with_its_readme_and_sums.py](tests/test_a_study_is_deposited_with_its_readme_and_sums.py)
- [tests/test_a_withheld_mean_says_how_much_longer.py](tests/test_a_withheld_mean_says_how_much_longer.py)
- [tests/test_each_file_of_a_study_is_read_one_way.py](tests/test_each_file_of_a_study_is_read_one_way.py)
- [tests/test_report_wiring.py](tests/test_report_wiring.py)
- [tests/test_statistics.py](tests/test_statistics.py)
- [tests/test_the_agent_answers_from_the_records.py](tests/test_the_agent_answers_from_the_records.py)
- [tests/test_what_rerun_set_aside_is_kept_apart.py](tests/test_what_rerun_set_aside_is_kept_apart.py)

</details>



The report phase compiles analytical findings, generates publication-style Markdown documents, PowerPoint slide decks (`.pptx`), and optional PDFs [src/fastmdxplora/report/document.py:1-15,_src/fastmdxplora/report/slides.py:1-10](). It operates in conjunction with statistical modules that enforce rigor through Chodera's autocorrelation / statistical inefficiency methods [src/fastmdxplora/statistics.py:28-36](), convergence assessment [src/fastmdxplora/report/convergence.py:1-25](), withholding un-equilibrated or under-sampled data [docs/results.md:117-125](), and packaging complete project bundles for deposition [src/fastmdxplora/report/bundle.py:1-7]().

---

## 1. Document Generation and Phase Context

The report generator synthesizes setup parameters, simulation logs, and analysis manifestations into a single structured Markdown file (`report/report.md`) [src/fastmdxplora/report/document.py:1-15](). 

### Figure Resolution and Relative Paths
Because Markdown documents and PDF renderers resolve paths relative to the folder containing the document (`report/`), figure links must be transformed to point upward into analysis directories [src/fastmdxplora/report/document.py:67-77](). Functions like `_link_from` compute relative paths (e.g., `../analysis/rmsd/rmsd.png`) to ensure compatibility across GUI views, offline HTML dashboards, and standalone viewers [src/fastmdxplora/report/document.py:67-77, docs/results.md:61-64]().

```mermaid
graph TD
    Root[""project_root""` --> Sim[""simulation/simulation_parameters.json""`
    Root --> Setup[""setup/setup_parameters.json""`
    Root --> Analysis[""analysis/analysis_manifest.json""`
    
    Analysis --> Context[""src/fastmdxplora/report/context.py:load_phase_context()""`
    Sim --> Context
    Setup --> Context
    
    Context --> DocGen[""src/fastmdxplora/report/document.py""`
    Context --> SlideGen[""src/fastmdxplora/report/slides.py""`
    Context --> ConvGen[""src/fastmdxplora/report/convergence.py""`
    
    DocGen --> MD[""report/report.md""`
    DocGen --> PDF[""report/report.pdf""`
    SlideGen --> PPTX[""report/slides.pptx""`
```
Sources: `src/fastmdxplora/report/document.py:30-77`, `src/fastmdxplora/report/slides.py:17-22`

---

## 2. Automated Methods Prose Generation

To satisfy journal requirements (such as the Journal of Chemical Information and Modeling guidelines or Communications Biology checklists), FastMDXplora automatically extracts protocol parameters and constructs formal methods paragraphs [src/fastmdxplora/report/methods.py:1-23]().

### The Checklist and Parameter Mapping
The `CHECKLIST` tuple defines mandatory reporting items, mapping conceptual fields to manifest keys [src/fastmdxplora/report/methods.py:45-66](). `missing_from_methods()` audits setup and simulation dictionaries, reporting explicit gaps rather than substituting undocumented default values [src/fastmdxplora/report/methods.py:126-158](). Integrator identifiers are translated into standard nomenclature via `_INTEGRATOR_NAMES` (e.g., mapping `"langevin_middle"` to `"Langevin middle-scheme"`) [src/fastmdxplora/report/methods.py:34-42]().

```mermaid
graph TD
    SubSpace[""Natural Language Space: 'Methods Checklist & Protocol'""` --> CodeSpace[""Code Entity Space: src/fastmdxplora/report/methods.py""`
    
    SubSpaceVal1[""Starting Coordinates & Water Model""` --> Code1[""missing_from_methods() / _get()""`
    SubSpaceVal2[""Integrator & Barostat Terms""` --> Code2[""_INTEGRATOR_NAMES / _steps_to_ns()""`
    SubSpaceVal3[""Software Versions & Provenance""` --> Code3[""_made_with_sentence()""`
```
Sources: `src/fastmdxplora/report/methods.py:34-158`

---

## 3. Statistical Inefficiency, Equilibration, and Convergence

Averaging observables across an entire production run without assessing equilibration or sample correlation produces statistically invalid error bars [src/fastmdxplora/statistics.py:1-26](). The statistics engine computes Chodera's statistical inefficiency `g` to determine independent sample counts and equilibration discard points [src/fastmdxplora/statistics.py:28-36]().

```mermaid
graph TD
    NL_Stats[""Natural Language Space: 'Statistical Rigor & Autocorrelation'""` --> CE_Stats[""Code Entity Space: src/fastmdxplora/statistics.py""`
    
    NL1[""Statistical Inefficiency (g)"` --> CE1[""statistical_inefficiency(series)""`
    NL2[""Equilibration Detection""` --> CE2[""detect_equilibration(series)""`
    NL3[""Effective Sample Count""` --> CE3[""independent_samples_said()""`
    NL4[""Drift & Spread Validation""` --> CE4[""drift_across_segments() / SUMMARISE""`
```
Sources: `src/fastmdxplora/statistics.py:1-70`, `src/fastmdxplora/statistics.py:95-149`

### Key Statistical Thresholds and Constants
* `MINIMUM_EFFECTIVE_SAMPLES = 10.0`: The minimum independent observations required for a mean and standard error to be reported [src/fastmdxplora/statistics.py:72-76]().
* `RESOLVED_SAMPLES = 25.0`: The number of inefficiencies a series must span to reliably resolve its correlation time [src/fastmdxplora/statistics.py:78-85]().
* `EQUILIBRATION_TOLERANCE = 0.1`: The tolerance share used when determining the latest start index that preserves independent samples while discarding initial relaxation [src/fastmdxplora/statistics.py:114-118]().
* `DRIFT_IN_SPREAD = 2.0`: The threshold ratio between the first and last thirds of averaged frames. Exceeding this indicates the observable is still drifting [src/fastmdxplora/statistics.py:120-127]().

---

## 4. Withholding and Remediation

When a trajectory lacks sufficient length or has unresolved correlation times, the reporting pipeline withholds the calculated mean rather than laundering bad data [docs/results.md:117-125]().

### Withholding Flags
* `analysis.sampling.correlation_unresolved`: The run is too short relative to its correlation time.
* `analysis.sampling.too_few_frames`: Effective sample count falls below `MINIMUM_EFFECTIVE_SAMPLES`.
* `analysis.sampling.drifting`: The observable fails the trend test across thirds of the run [docs/results.md:117-125]().

Where analyses are withheld, `sampling_shortfall()` calculates the additional simulation time required, translating frame counts into nanoseconds and wall-clock estimates via `simulation/cost.json` [docs/results.md:126-137](). Remediation pathways link directly to CLI resumption flags (e.g., `fastmdx resume` or `fastmdx explore --simulate-extra-ns`) [src/fastmdxplora/remedies.py:40-43]().

Sources: `src/fastmdxplora/statistics.py:1-153`, `docs/results.md:67-138`, `src/fastmdxplora/remedies.py:1-128`

---

## 5. Slide Decks and Project Bundles

Beyond Markdown reports, FastMDXplora generates PowerPoint slide decks and shareable ZIP bundles [src/fastmdxplora/report/slides.py:1-10, src/fastmdxplora/report/bundle.py:1-7]().

### Slide Deck Generation (`src/fastmdxplora/report/slides.py`)
If `python-pptx` is available, a 16:9 presentation (`report/slides.pptx`) is constructed, embedding key analysis figures, workflow summaries, and parameter highlights [src/fastmdxplora/report/slides.py:158-176](). If the dependency is missing, a structured Markdown outline fallback is generated [src/fastmdxplora/report/slides.py:1-8, 88-155]().

### Project Bundles (`src/fastmdxplora/report/bundle.py`)
`build_bundle()` archives the entire study directory into `report/project_bundle.zip` [src/fastmdxplora/report/bundle.py:81-107](). It automatically excludes:
* Temporary scratch spaces and live-view snapshot caches (`is_scratch()`) [src/fastmdxplora/report/bundle.py:70-74]()
* Superseded/previous run outputs (`PREVIOUS`, `superseded`) [src/fastmdxplora/report/bundle.py:64-69]()
* Process locks and carrying-on indicators (`.fastmdxplora-carrying-on`) [src/fastmdxplora/report/bundle.py:31-36]()

Sources: `src/fastmdxplora/report/slides.py:1-177`, `src/fastmdxplora/report/bundle.py:1-108`

---