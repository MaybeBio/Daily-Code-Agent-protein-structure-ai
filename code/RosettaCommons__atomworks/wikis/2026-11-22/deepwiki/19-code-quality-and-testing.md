# Code Quality and Testing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/lint_and_test.yaml](.github/workflows/lint_and_test.yaml)
- [.gitignore](.gitignore)
- [pyproject.toml](pyproject.toml)
- [src/atomworks/io/utils/ccd.py](src/atomworks/io/utils/ccd.py)
- [src/atomworks/io/utils/sequence.py](src/atomworks/io/utils/sequence.py)
- [src/atomworks/ml/encoding_definitions.py](src/atomworks/ml/encoding_definitions.py)
- [src/atomworks/ml/transforms/msa/_msa_constants.py](src/atomworks/ml/transforms/msa/_msa_constants.py)
- [tests/io/utils/test_sequence_maps.py](tests/io/utils/test_sequence_maps.py)
- [tests/io/utils/test_sequence_utils.py](tests/io/utils/test_sequence_utils.py)

</details>



This document covers the code quality standards, testing practices, and automated validation workflows used in AtomWorks. It explains the linting, formatting, testing frameworks, and continuous integration processes that ensure code reliability and maintainability.

For information about the CI/CD pipeline deployment and release processes, see [CI/CD Pipeline](#5.3). For details about project dependencies and build configuration, see [Dependencies and Build System](#5.1).

## Code Quality Standards

AtomWorks maintains code quality through automated linting, formatting, and comprehensive testing. The project uses modern Python tooling configured through `pyproject.toml` to enforce consistent code style and catch potential issues.

### Ruff Configuration

The project uses `ruff` as the primary tool for both code linting and formatting, providing a fast, unified approach to code quality enforcement.

```mermaid
graph TB
    subgraph "ruff_config"["Ruff Configuration"]
        A["pyproject.toml<br/>[tool.ruff]"] --> B["line-length: 120<br/>target-version: py312"]
        A --> C["[tool.ruff.lint]<br/>select rules"]
        A --> D["[tool.ruff.format]<br/>formatting options"]
        
        C --> E["pycodestyle (E, W)<br/>pyflakes (F)<br/>isort (I)"]
        C --> F["pep8-naming (N)<br/>pyupgrade (UP)<br/>flake8-bugbear (B)"]
        C --> G["flake8-comprehensions (C4)<br/>flake8-simplify (SIM)<br/>type annotations (ANN)"]
        
        D --> H["quote-style: double<br/>indent-style: space<br/>docstring-code-format: true"]
    end
    
    subgraph "excluded_dirs"["Excluded Directories"]
        I[".git, .pytest_cache<br/>.ruff_cache, .venv<br/>build, dist, data"]
    end
    
    A --> I
```

**Ruff Linting Rules**

The linting configuration enables a comprehensive set of rules for code quality:

| Rule Category | Code | Description |
|---------------|------|-------------|
| pycodestyle | E, W | Style guide enforcement |
| pyflakes | F | Logical errors and unused imports |
| isort | I | Import sorting and organization |
| pep8-naming | N | Naming convention enforcement |
| pyupgrade | UP | Modern Python syntax usage |
| flake8-bugbear | B | Bug-prone pattern detection |
| flake8-comprehensions | C4 | List/dict comprehension improvements |
| flake8-simplify | SIM | Code simplification suggestions |
| type annotations | ANN | Type hint enforcement |

**Sources:** [pyproject.toml:108-220]()

### Per-File Linting Exceptions

The configuration includes targeted exceptions for specific file types:

```mermaid
graph LR
    subgraph "per_file_ignores"["Per-File Ignore Rules"]
        A["__init__.py"] --> B["F401: unused imports"]
        C["tests/*"] --> D["D: docstring rules<br/>E: style errors<br/>ANN: type annotations"]
        E["docs/**/*.py"] --> F["E402: import positioning"]
        G["docs/**/*.ipynb"] --> H["E402: import positioning"]
    end
```

**Sources:** [pyproject.toml:204-208]()

## Testing Framework

AtomWorks uses `pytest` as the primary testing framework with several plugins to enhance testing capabilities and performance.

### Test Dependencies and Plugins

```mermaid
graph TB
    subgraph "pytest_ecosystem"["pytest Testing Ecosystem"]
        A["pytest>=8.2.0"] --> B["pytest-testmon<br/>Run changed tests only"]
        A --> C["pytest-xdist<br/>Parallel test execution"]
        A --> D["pytest-dotenv<br/>Environment variables"]
        A --> E["pytest-cov<br/>Coverage reporting"]
        A --> F["pytest-benchmark<br/>Performance testing"]
    end
    
    subgraph "test_config"["Test Configuration"]
        G["[tool.pytest.ini_options]"] --> H["testpaths = tests"]
        G --> I["addopts = --import-mode=importlib"]
        G --> J["pythonpath = src/atomworks, tests"]
    end
    
    A --> G
```

**Sources:** [pyproject.toml:58-68](), [pyproject.toml:222-233]()

### Test Markers and Categories

The project defines custom pytest markers to categorize and selectively run tests:

| Marker | Purpose |
|--------|---------|
| `requires_internet` | Tests needing internet connectivity |
| `requires_pymol_remote` | Tests requiring PyMOL remote connection |
| `requires_x3dna` | Tests requiring X3DNA software |
| `requires_digs` | Tests for IPD DIGS infrastructure |
| `slow` | Long-running tests |

**Sources:** [pyproject.toml:227-232]()

## Test Organization and Patterns

### Directory Structure

```mermaid
graph TB
    subgraph "test_structure"["Test Directory Structure"]
        A["tests/"] --> B["io/"]
        A --> C["ml/"]
        
        B --> D["utils/"]
        B --> E["test_parser.py"]
        
        D --> F["test_sequence_maps.py"]
        D --> G["test_sequence_utils.py"]
        D --> H["test_ccd.py"]
        
        C --> I["transforms/"]
        C --> J["test_datasets.py"]
    end
    
    subgraph "test_patterns"["Common Test Patterns"]
        K["parametrized tests<br/>@pytest.mark.parametrize"]
        L["fixture-based setup<br/>@pytest.fixture"]
        M["assertion patterns<br/>assert statements"]
    end
```

**Sources:** [tests/io/utils/test_sequence_maps.py:1-171](), [tests/io/utils/test_sequence_utils.py:1-304]()

### Parametrized Testing Examples

The codebase uses extensive parametrized testing for validation across multiple inputs:

```mermaid
graph LR
    subgraph "sequence_testing"["Sequence Conversion Testing"]
        A["PROTEIN_TEST_CASES<br/>21 amino acid mappings"] --> D["test_get_3_from_1_letter_code"]
        B["DNA_TEST_CASES<br/>5 nucleotide mappings"] --> D
        C["RNA_TEST_CASES<br/>5 nucleotide mappings"] --> D
        
        E["SEQUENCE_TEST_CASES<br/>11 PDB structures"] --> F["test_parser_one_letter_sequence_outputs"]
    end
```

**Sources:** [tests/io/utils/test_sequence_maps.py:14-171]()

### Test Data Management

```mermaid
graph TB
    subgraph "test_data_flow"["Test Data Flow"]
        A["atomworks setup tests<br/>CLI command"] --> B["tests/data/pdb<br/>Local test structures"]
        A --> C["tests/data/ccd<br/>Chemical component data"]
        
        D["Environment Variables"] --> E["PDB_MIRROR_PATH=tests/data/pdb"]
        D --> F["CCD_MIRROR_PATH=tests/data/ccd"]
        
        B --> G["Test execution"]
        C --> G
        E --> G
        F --> G
    end
```

**Sources:** [.github/workflows/lint_and_test.yaml:106-125]()

## Coverage Reporting

### Coverage Configuration

Coverage tracking focuses on the source code while excluding test files and generated content:

```mermaid
graph TB
    subgraph "coverage_config"["Coverage Configuration"]
        A["[tool.coverage.run]"] --> B["parallel = true<br/>source = src/atomworks"]
        A --> C["omit patterns"]
        
        C --> D["src/atomworks/version.py<br/>tests/*<br/>*/__init__.py"]
        C --> E["setup.py<br/>*/version.py"]
        
        F["[tool.coverage.report]"] --> G["exclude_lines"]
        G --> H["pragma: no cover<br/>def __repr__<br/>raise NotImplementedError"]
        G --> I["if __name__ == .__main__.:<br/>pass<br/>raise ImportError"]
    end
```

**Sources:** [pyproject.toml:235-253]()

## Continuous Integration Pipeline

### Lint and Test Workflow

The CI pipeline implements a two-stage approach with linting as a prerequisite for testing:

```mermaid
graph TB
    subgraph "ci_workflow"["CI/CD Lint and Test Workflow"]
        A["GitHub Push/PR"] --> B["lint job<br/>ruff check & format"]
        
        B --> C["test_github job<br/>Ubuntu latest"]
        B --> D["test_digs job<br/>jojo runner"]
        
        C --> E["Setup Python 3.12<br/>Install dependencies with uv"]
        C --> F["atomworks setup tests<br/>Download test data"]
        C --> G["pytest execution<br/>Parallel with xdist"]
        
        D --> H["SLURM execution<br/>srun with 8 CPUs"]
        
        G --> I["Coverage report<br/>Upload artifact"]
        H --> I
    end
```

**Sources:** [.github/workflows/lint_and_test.yaml:1-132]()

### Test Execution Strategy

```mermaid
graph LR
    subgraph "test_execution"["Test Execution Patterns"]
        A["Single CPU"] --> B["Sequential execution<br/>io and ml tests separately"]
        C["Multi CPU"] --> D["Parallel execution<br/>pytest -n auto --maxprocesses"]
        
        E["Test Filtering"] --> F["-m 'not benchmark'<br/>Skip performance tests"]
        E --> G["-m 'not slow'<br/>Skip long-running tests"]
    end
```

The CI system adapts test execution based on available resources, running tests sequentially on single-CPU systems and in parallel on multi-CPU systems.

**Sources:** [.github/workflows/lint_and_test.yaml:110-125]()

### Environment Setup

```mermaid
graph TB
    subgraph "ci_environment"["CI Environment Setup"]
        A["Ubuntu Latest"] --> B["Python 3.12 setup"]
        B --> C["System dependencies<br/>rsync installation"]
        C --> D["uv package manager<br/>Fast dependency resolution"]
        D --> E["Install atomworks[ml,openbabel,dev]"]
        E --> F["Test data setup<br/>atomworks setup tests"]
        F --> G["Environment variables<br/>OPENBLAS_NUM_THREADS=1<br/>OMP_NUM_THREADS=1"]
    end
```

**Sources:** [.github/workflows/lint_and_test.yaml:74-108]()

---