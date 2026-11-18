# Spectroscopic Analysis

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/interfaces/mace_interface.py](mlatom/interfaces/mace_interface.py)
- [mlatom/spectra.py](mlatom/spectra.py)

</details>



This document covers MLatom's spectroscopic analysis capabilities for generating and analyzing UV/Vis, IR, and Raman spectra from molecular simulations. The system provides tools for spectrum calculation, broadening, comparison, and visualization.

For information about molecular simulations that generate the underlying data, see [Core Simulations](#5.1). For advanced dynamics calculations, see [Advanced Dynamics](#5.3).

## System Architecture

```mermaid
graph TB
    subgraph "Data Input"
        MOL["molecule objects<br/>(excitation energies,<br/>oscillator strengths,<br/>frequencies, intensities)"]
        MOLDB["molecular_database<br/>(ensemble data)"]
    end
    
    subgraph "Core Spectrum Classes"
        SPECTRUM["spectrum<br/>Base class"]
        UVVIS["uvvis<br/>UV/Vis spectra"]
        IR["ir<br/>IR spectra"] 
        RAMAN["raman<br/>Raman spectra"]
    end
    
    subgraph "Analysis Methods"
        SPC["spc()<br/>Single-point convolution"]
        NEA["nea()<br/>Nuclear ensemble approach"]
        LORENTZ["lorentzian()<br/>Lorentzian broadening"]
    end
    
    subgraph "Processing & Comparison"
        BROADEN["broaden()<br/>Spectral broadening"]
        COMPARE["spectrum_comparison<br/>Similarity metrics"]
        NORMALIZE["normalize()<br/>Normalization"]
    end
    
    subgraph "Output & Visualization"
        PLOT["plot_spectra()<br/>plot_uvvis()<br/>plot_ir()"]
        SAVE["dump()<br/>save spectra"]
    end
    
    MOL --> SPC
    MOLDB --> NEA
    MOL --> LORENTZ
    
    SPC --> UVVIS
    NEA --> UVVIS
    LORENTZ --> IR
    LORENTZ --> RAMAN
    
    SPECTRUM --> UVVIS
    SPECTRUM --> IR
    SPECTRUM --> RAMAN
    
    UVVIS --> BROADEN
    IR --> BROADEN
    RAMAN --> BROADEN
    
    BROADEN --> NORMALIZE
    NORMALIZE --> COMPARE
    COMPARE --> PLOT
    NORMALIZE --> SAVE
```

**Spectrum Data Flow and Processing Pipeline**

The spectroscopic analysis system processes molecular properties through several stages to generate and analyze spectra.

Sources: [mlatom/spectra.py:1-1371]()

## Core Data Structures

The `spectrum` class serves as the foundation for all spectroscopic data in MLatom, providing essential data management and processing capabilities.

### Spectrum Base Class

```mermaid
classDiagram
    class spectrum {
        +x: ndarray
        +y: ndarray  
        +xy_pairs: ndarray
        +xy: ndarray
        +set_data(x, y, xy_pairs, xy, sort)
        +interpolate(method)
        +normalize(method)
        +sample(list, method)
        +broaden(line_spectrum, spectrum_range, broadening_func)
        +plot(filename, xaxis_caption, yaxis_caption)
        +dump(filename, format)
        +load(filename, format)
    }
    
    class uvvis {
        +wavelengths_nm: ndarray
        +energies_eV: ndarray
        +molar_absorbance: ndarray
        +cross_section: ndarray
        +meta_data: str
        +spc(molecule, band_width, shift, refractive_index)
        +nea(molecular_database, wavelengths_nm, broadening_width)
    }
    
    class ir {
        +frequencies: ndarray
        +infrared_intensities: ndarray
        +meta_data: str
        +lorentzian(molecule, fwhm, spectrum_range)
    }
    
    class raman {
        +frequencies: ndarray
        +raman_intensities: ndarray
        +meta_data: str
        +lorentzian(molecule, fwhm, spectrum_range)
    }
    
    spectrum <|-- uvvis
    spectrum <|-- ir
    spectrum <|-- raman
```

**Core Spectrum Class Hierarchy**

The spectrum classes provide specialized functionality for different types of spectroscopy while sharing common data management operations.

Sources: [mlatom/spectra.py:17-216](), [mlatom/spectra.py:217-451](), [mlatom/spectra.py:452-490](), [mlatom/spectra.py:494-532]()

### Data Management Features

| Method | Purpose | Key Parameters |
|--------|---------|----------------|
| `set_data()` | Initialize spectral data | `x`, `y`, `xy_pairs`, `sort` |
| `interpolate()` | Create interpolation function | `method` ("linear", "cubic") |
| `sample()` | Resample spectrum at new points | `list`, `method` |
| `normalize()` | Normalize spectral intensities | `method` ("average", "max", "sqrt", "msc") |
| `broaden()` | Apply broadening functions | `broadening_func`, `broadening_func_kwargs` |

Sources: [mlatom/spectra.py:21-41](), [mlatom/spectra.py:42-49](), [mlatom/spectra.py:52-80](), [mlatom/spectra.py:82-87](), [mlatom/spectra.py:90-111]()

## UV/Vis Spectroscopy Methods

The UV/Vis analysis system provides two primary approaches for generating absorption spectra from molecular excited state calculations.

### Single-Point Convolution (SPC)

The SPC method generates UV/Vis spectra from single-geometry excited state calculations using Gaussian broadening.

```mermaid
flowchart TD
    MOL["molecule with:<br/>excitation_energies<br/>oscillator_strengths"]
    
    CONVERT["Convert energies<br/>Hartree → eV → nm"]
    
    AUTORANGE["Auto-determine<br/>wavelength range"]
    
    BROADEN["spc_broadening_func()<br/>Gaussian convolution"]
    
    UNITS["Unit conversions:<br/>molar_absorbance<br/>cross_section<br/>wavelengths_nm<br/>energies_eV"]
    
    OUTPUT["uvvis spectrum object"]
    
    MOL --> CONVERT
    CONVERT --> AUTORANGE
    AUTORANGE --> BROADEN
    BROADEN --> UNITS
    UNITS --> OUTPUT
```

**SPC Method Processing Flow**

The SPC implementation follows the methodology described in DOI: 10.1007/s00894-020-04355-y for efficient single-point spectrum generation.

Sources: [mlatom/spectra.py:284-341](), [mlatom/spectra.py:342-363]()

### Nuclear Ensemble Approach (NEA)

The NEA method generates spectra from molecular ensembles using statistical sampling of nuclear configurations.

```mermaid
flowchart TD
    MOLDB["molecular_database<br/>ensemble geometries<br/>with excited states"]
    
    COLLECT["Collect excitation data<br/>from all geometries"]
    
    CLIB["Call C library cs.so<br/>for efficient computation"]
    
    PREFACTOR["Calculate physical<br/>prefactors and constants"]
    
    CONVOLVE["Statistical convolution<br/>with broadening"]
    
    CONVERT["Convert to standard units<br/>cross_section → molar_absorbance"]
    
    SPECTRUM["uvvis spectrum object"]
    
    MOLDB --> COLLECT
    COLLECT --> CLIB
    COLLECT --> PREFACTOR
    PREFACTOR --> CONVOLVE
    CLIB --> CONVOLVE
    CONVOLVE --> CONVERT
    CONVERT --> SPECTRUM
```

**NEA Method Processing Flow**

The NEA implementation uses a compiled C library for efficient statistical calculations over molecular ensembles.

Sources: [mlatom/spectra.py:366-450](), [mlatom/spectra.py:440-445]()

## Vibrational Spectroscopy

The IR and Raman analysis capabilities provide broadening and visualization for vibrational spectra.

### IR Spectroscopy

```python
# Example IR spectrum generation
ir_spectrum = ir.lorentzian(
    molecule=mol,           # molecule with frequencies and infrared_intensities
    fwhm=30,               # Full width at half maximum
    spectrum_range=np.arange(500, 4001)  # wavenumber range
)
```

The IR class handles infrared spectra with Lorentzian line shape broadening. The `lorentzian()` method applies the `Lorentzian_line_shape_function` to convert discrete vibrational frequencies into continuous spectra.

Sources: [mlatom/spectra.py:479-489](), [mlatom/spectra.py:148-161]()

### Raman Spectroscopy

The Raman class provides identical functionality to IR spectra but works with Raman intensities instead of IR intensities. The same Lorentzian broadening approach applies to generate continuous Raman spectra from discrete vibrational modes.

Sources: [mlatom/spectra.py:521-531]()

## Spectrum Comparison and Analysis

The `spectrum_comparison` class provides comprehensive tools for quantitative spectral analysis and similarity assessment.

```mermaid
graph TD
    SPEC1["spectrum 1<br/>(reference)"]
    SPEC2["spectrum 2<br/>(predicted)"]
    
    ALIGN["line_up_spectra()<br/>Interpolation alignment"]
    
    METRICS{{"Available Metrics"}}
    
    PCC["pearson_coefficient()<br/>Pearson correlation"]
    SCC["spearman_coefficient()<br/>Spearman correlation"] 
    TANI["tanimoto_coefficient()<br/>Tanimoto similarity"]
    KLD["KL_divergence_transformed()<br/>Kullback-Leibler"]
    EMD["earth_mover_distance_transformed()<br/>Wasserstein distance"]
    MSE["mse_transformed()<br/>Mean squared error"]
    COSINE["cosine()<br/>Cosine similarity"]
    
    RESULT["Similarity/distance score"]
    
    SPEC1 --> ALIGN
    SPEC2 --> ALIGN
    ALIGN --> METRICS
    
    METRICS --> PCC
    METRICS --> SCC
    METRICS --> TANI
    METRICS --> KLD
    METRICS --> EMD
    METRICS --> MSE
    METRICS --> COSINE
    
    PCC --> RESULT
    SCC --> RESULT
    TANI --> RESULT
    KLD --> RESULT
    EMD --> RESULT
    MSE --> RESULT
    COSINE --> RESULT
```

**Spectrum Comparison Workflow**

The comparison system aligns spectra and applies various similarity metrics for quantitative analysis.

### Available Comparison Metrics

| Metric | Method | Range | Purpose |
|--------|--------|-------|---------|
| Pearson Correlation | `pearson_coefficient()` | [-1, 1] | Linear correlation |
| Spearman Correlation | `spearman_coefficient()` | [-1, 1] | Rank correlation |
| Tanimoto Coefficient | `tanimoto_coefficient()` | [0, 1] | Molecular similarity |
| Kullback-Leibler | `KL_divergence_transformed()` | [0, 1] | Information divergence |
| Jensen-Shannon | `JS_divergence_transformed()` | [0, 1] | Symmetric divergence |
| Earth Mover Distance | `earth_mover_distance_transformed()` | [0, 1] | Wasserstein distance |
| Mean Squared Error | `mse_transformed()` | [0, 1] | Point-wise error |
| Cosine Similarity | `cosine()` | [-1, 1] | Angular similarity |

Sources: [mlatom/spectra.py:540-602](), [mlatom/spectra.py:636-1012]()

## Visualization and Plotting

The plotting system provides specialized visualization for different spectral types with interactive capabilities.

### General Spectrum Plotting

The `plot_spectra()` function handles generic spectral visualization with extensive customization options including normalization, shifting, and range selection.

Sources: [mlatom/spectra.py:1017-1116]()

### UV/Vis Plotting Features

```python
# UV/Vis plotting with interactive broadening
plot_uvvis(
    spectra=[uvvis_spectrum],
    molecule=mol,                    # for oscillator strength display
    spc=True,                       # enable SPC calculation
    band_width_slider=True,         # interactive broadening control
    shift=True,                     # align spectra maxima
    normalize=True                  # normalize intensities
)
```

The UV/Vis plotting system includes interactive widgets for real-time parameter adjustment and dual-axis display of both continuous spectra and discrete oscillator strengths.

Sources: [mlatom/spectra.py:1118-1202]()

### IR Plotting Features

```python
# IR plotting with peak highlighting
plot_ir(
    spectra=[ir_spectrum],
    molecule=mol,
    lorentzian=True,               # apply Lorentzian broadening
    band_width_slider=True,        # interactive FWHM control
    peak_highlight_slider=True,    # highlight individual peaks
    scaling_factor=0.95            # frequency scaling
)
```

The IR plotting system provides peak highlighting with molecular visualization and interactive broadening parameter control.

Sources: [mlatom/spectra.py:1204-1366]()

---