# Prompt Selectors & Results Visualizer

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/widgets/components/results_visualizer.py](esm/widgets/components/results_visualizer.py)
- [esm/widgets/components/sasa_prompt_selector.py](esm/widgets/components/sasa_prompt_selector.py)
- [esm/widgets/components/secondary_structure_prompt_selector.py](esm/widgets/components/secondary_structure_prompt_selector.py)
- [esm/widgets/components/sequence_prompt_selector.py](esm/widgets/components/sequence_prompt_selector.py)
- [esm/widgets/components/structure_prompt_selector.py](esm/widgets/components/structure_prompt_selector.py)
- [esm/widgets/utils/drawing/colors.py](esm/widgets/utils/drawing/colors.py)
- [esm/widgets/utils/drawing/draw_category_array.py](esm/widgets/utils/drawing/draw_category_array.py)
- [esm/widgets/utils/drawing/draw_function_annotations.py](esm/widgets/utils/drawing/draw_function_annotations.py)
- [esm/widgets/utils/drawing/draw_protein_structure.py](esm/widgets/utils/drawing/draw_protein_structure.py)
- [esm/widgets/utils/indexing.py](esm/widgets/utils/indexing.py)
- [esm/widgets/utils/prompting.py](esm/widgets/utils/prompting.py)
- [esm/widgets/utils/serialization.py](esm/widgets/utils/serialization.py)
- [esm/widgets/views/esm3_prompt_preview.py](esm/widgets/views/esm3_prompt_preview.py)

</details>



The `esm.widgets` package provides a suite of interactive Jupyter components for manipulating protein data and visualizing model outputs. This section details the specialized prompt selector components—which allow users to define constraints across sequence, structure, and annotation tracks—and the visualization utilities used to render the resulting proteins, including pLDDT-colored structures and functional annotation maps.

## Overview of Prompt Selectors

Prompt selectors are interactive widgets designed to populate a `PromptManager` [esm/widgets/utils/prompting.py](). Each selector targets a specific modality (track) of the ESM3 model. They share a common pattern: providing a visual representation of the protein (e.g., a contact map or sequence string), a range selection mechanism (sliders or manual input), and a way to commit these selections as prompts for generation or prediction tasks.

### Data Flow for Prompt Selection

The following diagram illustrates how user interactions with the widgets translate into data structures used by the inference clients.

**Prompt Selection to API Payload Data Flow**

```mermaid
graph TD
    subgraph "UI Layer (esm.widgets.components)"
        A["SequencePromptSelector"] -- "Range Selection" --> PM["PromptManager"]
        B["StructurePromptSelector"] -- "Range Selection" --> PM
        C["SSPromptSelector"] -- "Range Selection" --> PM
        D["SASAPromptSelector"] -- "Range Selection" --> PM
    end

    subgraph "Logic Layer (esm.widgets.utils)"
        PM -- "get_prompts(tag)" --> P["Prompt Entries"]
        P -- "Parsing" --> PR["convert_range_string_to_list_of_ranges"]
        PR -- "Indexing" --> IX["zero_index_to_pdb_index"]
    end

    subgraph "Client Layer (esm.sdk)"
        IX -- "Map to Tracks" --> EP["ESMProtein"]
        EP -- "Inference" --> IC["InferenceClient.generate()"]
    end
```

Sources: [esm/widgets/components/sequence_prompt_selector.py:13-20](), [esm/widgets/components/structure_prompt_selector.py:19-25](), [esm/widgets/components/secondary_structure_prompt_selector.py:13-21](), [esm/widgets/components/sasa_prompt_selector.py:12-20](), [esm/widgets/utils/parsing.py:9-9](), [esm/widgets/utils/indexing.py:25-26]()

---

## Modality-Specific Selectors

### Sequence Prompt Selector
The `create_sequence_prompt_selector` function [esm/widgets/components/sequence_prompt_selector.py:13-20]() renders the protein sequence with HTML-based highlighting. It supports:
*   **Highlighting**: Uses `apply_highlighting` [esm/widgets/components/sequence_prompt_selector.py:96-130]() to wrap residues in `<span>` tags with background colors derived from the `PromptManager`.
*   **Line Breaking**: Automatically wraps sequences based on `line_length` [esm/widgets/components/sequence_prompt_selector.py:88-94]().
*   **Masking Options**: A toggle between "Custom range" and "Fully masked" [esm/widgets/components/sequence_prompt_selector.py:39-44]().

### Structure Prompt Selector
The `create_structure_prompt_selector` function [esm/widgets/components/structure_prompt_selector.py:19-25]() provides a dual-view interface for structural prompting:
1.  **Contact Map**: An `imshow` plot of the $C\beta$ adjacency matrix (8Å threshold) [esm/widgets/components/structure_prompt_selector.py:26-27]().
2.  **3D Visualization**: An interactive `py3Dmol` view rendered via `draw_protein_structure` [esm/widgets/utils/drawing/draw_protein_structure.py:8-12]().

It handles coordinate conversion between zero-based indexing and PDB residue indexing using `pdb_range_to_zero_range` [esm/widgets/utils/indexing.py:38-44]().

### Secondary Structure & SASA Selectors
Both `create_secondary_structure_prompt_selector` [esm/widgets/components/secondary_structure_prompt_selector.py:13-21]() and `create_sasa_prompt_selector` [esm/widgets/components/sasa_prompt_selector.py:12-20]() utilize the `draw_data_array` utility [esm/widgets/utils/drawing/draw_category_array.py]() to render 1D tracks.
*   **SS3**: Uses `pydssp` to assign secondary structure (Helix, Strand, Coil) from coordinates [esm/widgets/components/secondary_structure_prompt_selector.py:143-147]().
*   **SASA**: Computes Solvent Accessible Surface Area using the `ProteinChain.sasa()` method [esm/widgets/components/sasa_prompt_selector.py:133-135]().

Sources: [esm/widgets/components/sequence_prompt_selector.py:13-175](), [esm/widgets/components/structure_prompt_selector.py:19-195](), [esm/widgets/components/secondary_structure_prompt_selector.py:13-163](), [esm/widgets/components/sasa_prompt_selector.py:12-135]()

---

## Results Visualization Utilities

The visualization subsystem converts model outputs (tensors or `ESMProtein` objects) into human-readable plots and 3D structures.

### `create_results_visualizer` Dispatch Pattern
The `create_results_visualizer` function [esm/widgets/components/results_visualizer.py:21-36]() acts as a central dispatcher for rendering generated `ESMProtein` samples. It takes a `modality` string (e.g., "sequence", "structure", "sasa", "secondary_structure", "function") and a list of `ESMProtein` objects. Based on the modality, it calls a specific `create_*_results_page` function to generate the appropriate visualization.

For example, if `modality` is "structure", it sorts samples by pTM score [esm/widgets/components/results_visualizer.py:38-43]() and then calls `create_structure_results_page` [esm/widgets/components/results_visualizer.py:85-90](). This function then uses `draw_protein_structure` to render the 3D models.

**`create_results_visualizer` Dispatch Flow**
```mermaid
graph TD
    CRV["create_results_visualizer(modality, samples)"] --> |modality == "sequence"| CSR["create_sequence_results_page"]
    CRV --> |modality == "sasa"| CSRS["create_sasa_results_page"]
    CRV --> |modality == "secondary_structure"| CSRSS["create_secondary_structure_results_page"]
    CRV --> |modality == "structure"| CSRT["create_structure_results_page"]
    CRV --> |modality == "function"| CSRF["create_function_annotations_results_page"]

    CSR --> ADD["add_line_breaks"]
    CSRS --> DDA["draw_data_array"]
    CSRSS --> DDA
    CSRT --> DPS["draw_protein_structure"]
    CSRF --> DFA["draw_function_annotations"]

    subgraph "Common Utilities"
        ADD["add_line_breaks"]
        DDA["draw_data_array"]
        DPS["draw_protein_structure"]
        DFA["draw_function_annotations"]
    end
```
Sources: [esm/widgets/components/results_visualizer.py:21-132]()

### Structural Rendering
The `draw_protein_structure` function [esm/widgets/utils/drawing/draw_protein_structure.py:8-12]() is the primary utility for 3D visualization. It takes a `ProteinChain` and a list of `highlighted_ranges` (start, end, color).
*   **Implementation**: It initializes a `py3Dmol.view` [esm/widgets/utils/drawing/draw_protein_structure.py:16-17]() and applies styles using the `cartoon` representation [esm/widgets/utils/drawing/draw_protein_structure.py:18-23]().
*   **pLDDT Coloring**: When rendering structures from model predictions, `create_structure_results_page` [esm/widgets/components/results_visualizer.py:250-259]() can color the protein by pLDDT scores, providing a visual indication of prediction confidence. It uses a colormap from blue (low confidence) to red (high confidence) [esm/widgets/components/results_visualizer.py:254-255]().

### Functional Annotation Visualization
Functional annotations are visualized as a linear map of features using the `dna_features_viewer` library.
*   **`draw_function_annotations`**: Converts a list of `FunctionAnnotation` objects into a `GraphicRecord` [esm/widgets/utils/drawing/draw_function_annotations.py:25-27]().
*   **Color Mapping**: Annotations are colored by their InterPro entry type (e.g., Domain, Family, Site) using a predefined `type_colors` mapping [esm/widgets/utils/drawing/draw_function_annotations.py:28-30]().
*   **Backend Management**: Uses a `use_backend("agg")` context manager [esm/widgets/utils/drawing/draw_function_annotations.py:15-22]() to ensure thread-safe headless rendering of matplotlib figures into `ipywidgets.Image` objects [esm/widgets/utils/drawing/draw_function_annotations.py:77-81]().

### 1D Track Visualization
The `draw_data_array` function [esm/widgets/utils/drawing/draw_category_array.py]() provides a flexible way to render categorical or continuous 1D data.

| Feature | Description |
| :--- | :--- |
| **Categorical** | Maps discrete integers to colors via `category_color_mapping` [esm/widgets/utils/drawing/draw_category_array.py:27-55](). |
| **Continuous** | Uses a `matplotlib` colormap and `Normalize` for values like SASA [esm/widgets/utils/drawing/draw_category_array.py:103-109](). |
| **Highlights** | Draws bounding boxes around specific ranges to indicate selected prompts [esm/widgets/utils/drawing/draw_category_array.py:82-92](). |

Sources: [esm/widgets/components/results_visualizer.py:21-36](), [esm/widgets/components/results_visualizer.py:250-259](), [esm/widgets/utils/drawing/draw_protein_structure.py:8-27](), [esm/widgets/utils/drawing/draw_function_annotations.py:25-83](), [esm/widgets/utils/drawing/draw_category_array.py]()

---

## Implementation Details

### Coordinate and Indexing Utilities
The system relies on `esm/widgets/utils/indexing.py` to bridge the gap between model-centric zero-indexing and biologist-centric PDB indexing.

*   **`zero_index_to_pdb_index`**: Retrieves the original residue number from the `ProteinChain.residue_index` array [esm/widgets/utils/indexing.py:25-26]().
*   **`pdb_index_to_zero_index`**: Uses `np.argwhere` to find the array position corresponding to a PDB residue number [esm/widgets/utils/indexing.py:17-22]().

### Visualizer Component Architecture

```mermaid
graph LR
    subgraph "Visualizer Components"
        DDA["draw_data_array"]
        DPS["draw_protein_structure"]
        DFA["draw_function_annotations"]
    end

    subgraph "Helper Modules"
        IX["indexing.py"]
        CL["colors.py"]
        PR["parsing.py"]
        SER["serialization.py"]
    end

    DDA --> IX
    DPS --> IX
    DFA --> IX
    DDA --> CL
    DPS --> CL
    DFA --> CL
    SER --> DPS
```

Sources: [esm/widgets/utils/indexing.py:1-45](), [esm/widgets/utils/drawing/draw_category_array.py](), [esm/widgets/utils/drawing/draw_protein_structure.py:8-12](), [esm/widgets/utils/serialization.py:18-23]()

---