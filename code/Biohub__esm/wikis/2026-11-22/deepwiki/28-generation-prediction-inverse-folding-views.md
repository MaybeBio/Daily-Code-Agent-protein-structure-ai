# Generation, Prediction & Inverse Folding Views

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/widgets/components/function_annotator.py](esm/widgets/components/function_annotator.py)
- [esm/widgets/utils/protein_import.py](esm/widgets/utils/protein_import.py)
- [esm/widgets/views/esm3_prompt_selector.py](esm/widgets/views/esm3_prompt_selector.py)
- [esm/widgets/views/generation.py](esm/widgets/views/generation.py)
- [esm/widgets/views/inverse_folding.py](esm/widgets/views/inverse_folding.py)

</details>



The `esm.widgets` package provides a suite of interactive Jupyter-based interfaces for interacting with ESM3 models. These views encapsulate complex orchestration logic, including batch generation, multi-track prediction pipelines, and specialized tasks like inverse folding.

## ESM3 Generation Launcher

The `create_esm3_generation_launcher` function is the primary entry point for triggering protein generation tasks within the UI [esm/widgets/views/esm3_generation_launcher.py:21-35](). It orchestrates the flow between user-defined parameters, the `ESM3InferenceClient`, and the visualization of results.

### Implementation Details
The launcher manages several generation parameters through `ipywidgets`:
*   **Track Selection**: Users choose between `sequence`, `structure`, `secondary_structure`, `sasa`, or `function` [esm/widgets/views/esm3_generation_launcher.py:49-53]().
*   **Sampling Controls**: Includes `num_steps` (denoising steps), `temperature`, `top_p`, and `num_samples` [esm/widgets/views/esm3_generation_launcher.py:54-101]().
*   **Batch Execution**: The launcher calls `client_.batch_generate` to process multiple samples in parallel, passing a list of `ESMProtein` objects and corresponding `GenerationConfig` instances [esm/widgets/views/esm3_generation_launcher.py:171-173]().

### Data Flow: Generation Launcher
The following diagram shows how the UI components map to SDK entities during a generation request.

**UI to SDK Generation Mapping**
```mermaid
graph TD
    subgraph "Jupyter UI (Natural Language Space)"
        A["Track Dropdown"] -- "modality" --> B["GenerationConfig"]
        C["Num Steps Slider"] -- "num_steps" --> B
        D["Temperature Slider"] -- "temperature" --> B
        E["Generate Button"] -- "on_click" --> F["Launcher Callback"]
    end

    subgraph "Code Entity Space (SDK/Models)"
        F --> G["ESM3InferenceClient.batch_generate()"]
        B --> G
        H["ESMProtein (Prompt)"] --> G
        G --> I["list[ESMProtein] (Results)"]
        I --> J["create_results_visualizer()"]
    end
    
    style G stroke-width:2px
    style B stroke-width:2px
```
Sources: [esm/widgets/views/esm3_generation_launcher.py:49-101](), [esm/widgets/views/esm3_generation_launcher.py:139-144](), [esm/widgets/views/esm3_generation_launcher.py:171-173]()

## Prediction UI

The `create_prediction_ui` provides a sequential track prediction pipeline [esm/widgets/views/prediction.py:14](). Unlike the generation launcher which focuses on a single track, the prediction view typically follows a fixed pipeline to fill in all missing modalities for a given sequence or structure.

### Sequential Track Pipeline
When a user clicks "Predict", the UI executes a loop across multiple tracks:
1.  **Input**: Accepts raw sequence via `Textarea` or a `ProteinChain` via `ProteinImporter` [esm/widgets/views/prediction.py:18-30]().
2.  **Orchestration**: Iterates through `["structure", "secondary_structure", "sasa", "function"]` [esm/widgets/views/prediction.py:89]().
3.  **Inference**: For each track, it calls `client.generate(protein, config=GenerationConfig(track=track))` [esm/widgets/views/prediction.py:94-96]().
4.  **Result Aggregation**: The final `ESMProtein` containing all predicted tracks is passed to `create_results_visualizer` and displayed in a `widgets.Tab` [esm/widgets/views/prediction.py:104-139]().

Sources: [esm/widgets/views/prediction.py:80-147]()

## Inverse Folding View

The Inverse Folding view is a specialized configuration of the generation pipeline focused on predicting a protein sequence given a fixed backbone structure [esm/widgets/views/inverse_folding.py:14]().

### Implementation
*   **Input Handling**: Uses `ProteinImporter` to load a structure, then strips all attributes except the structure coordinates (`protein.sequence = None`, etc.) [esm/widgets/views/inverse_folding.py:27-37]().
*   **Generation Configuration**: Executes a single-step generation on the `sequence` track [esm/widgets/views/inverse_folding.py:67-70]():
    ```python
    client.generate(input=protein, config=GenerationConfig(track="sequence", num_steps=1))
    ```
*   **Output**: Displays the generated sequence using the `sequence` modality of the results visualizer [esm/widgets/views/inverse_folding.py:74-79]().

Sources: [esm/widgets/views/inverse_folding.py:27-37](), [esm/widgets/views/inverse_folding.py:67-70]()

## Results Visualization Dispatch

The `create_results_visualizer` function acts as a central dispatcher that selects the appropriate drawing utility based on the modality of the generated data [esm/widgets/components/results_visualizer.py:21-36]().

| Modality | Visualization Logic | Code Reference |
| :--- | :--- | :--- |
| **Structure** | Renders 3D structure with pLDDT coloring. | [esm/widgets/components/results_visualizer.py:85-90]() |
| **Sequence** | Displays monospace text with line breaks. | [esm/widgets/components/results_visualizer.py:61-67]() |
| **SASA** | Draws a 1D heat map using `draw_data_array`. | [esm/widgets/components/results_visualizer.py:68-74]() |
| **Function** | Renders InterPro/Keyword labels. | [esm/widgets/components/results_visualizer.py:91-97]() |

### Visualization System Mapping
This diagram bridges the visual components seen by the user to the underlying drawing functions and data models.

**Visualization Component Mapping**
```mermaid
graph LR
    subgraph "Visual UI Component"
        V1["Structure Tab"]
        V2["SASA Heatmap"]
        V3["Function Labels"]
    end

    subgraph "Code Dispatcher"
        D["create_results_visualizer()"]
    end

    subgraph "Logic & Drawing Entities"
        F1["draw_protein_structure()"]
        F2["draw_data_array()"]
        F3["draw_function_annotations()"]
        P["ESMProtein"]
    end

    V1 -- "modality='structure'" --> D
    V2 -- "modality='sasa'" --> D
    V3 -- "modality='function'" --> D

    D --> F1
    D --> F2
    D --> F3
    F1 & F2 & F3 --> P
```
Sources: [esm/widgets/components/results_visualizer.py:21-36](), [esm/widgets/components/results_visualizer.py:61-97]()

## Function Annotation UI

The `create_function_annotator` provides a searchable interface for adding InterPro tags and keywords to a generation prompt [esm/widgets/components/function_annotator.py:26-30]().

*   **Trie-based Search**: It uses a `pygtrie.CharTrie` populated from the `InterProQuantizedTokenizer` vocabulary to provide autocomplete suggestions for valid function tokens [esm/widgets/components/function_annotator.py:12-23]().
*   **Range Selection**: An `IntRangeSlider` allows users to specify the residue range (start/end) where the function annotation should apply [esm/widgets/components/function_annotator.py:54-65]().
*   **Callback Integration**: Validated annotations are passed back to the `PromptManagerCollection` via `add_annotation_callback` [esm/widgets/components/function_annotator.py:100-102]().

Sources: [esm/widgets/components/function_annotator.py:12-23](), [esm/widgets/components/function_annotator.py:31-66]()

---