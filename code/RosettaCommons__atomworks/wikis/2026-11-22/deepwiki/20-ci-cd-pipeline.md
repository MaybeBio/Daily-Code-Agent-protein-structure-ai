# CI/CD Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/release_and_docs.yaml](.github/workflows/release_and_docs.yaml)
- [.releaserc.js](.releaserc.js)
- [README.md](README.md)
- [docs/_static/atomworks_datapipelines.svg](docs/_static/atomworks_datapipelines.svg)
- [docs/_static/atomworks_logo_color.svg](docs/_static/atomworks_logo_color.svg)
- [docs/_static/atomworks_logo_dark.svg](docs/_static/atomworks_logo_dark.svg)
- [docs/_static/atomworks_logo_light.svg](docs/_static/atomworks_logo_light.svg)
- [docs/_static/atomworks_overview.png](docs/_static/atomworks_overview.png)
- [docs/_static/default_thumbnail.png](docs/_static/default_thumbnail.png)
- [docs/_static/favicon-16x16.png](docs/_static/favicon-16x16.png)
- [docs/_static/favicon-32x32.png](docs/_static/favicon-32x32.png)
- [docs/conf.py](docs/conf.py)
- [docs/index.rst](docs/index.rst)

</details>



This document covers the automated Continuous Integration and Continuous Deployment (CI/CD) pipeline that ensures code quality, runs comprehensive tests, and manages releases for the AtomWorks project. The pipeline includes automated linting, testing on multiple environments, semantic versioning, PyPI publishing, and versioned documentation deployment.

For information about project dependencies and build configuration, see [Dependencies and Build System](#5.1). For details about code quality tools and testing setup, see [Code Quality and Testing](#5.2).

## CI/CD Architecture Overview

The AtomWorks CI/CD pipeline is implemented through GitHub Actions workflows that automate releases and documentation deployment:

```mermaid
graph TD
    subgraph "Trigger Events"
        A["Push to production branch"]
    end
    
    subgraph "release_and_docs Workflow"
        B["checkout_repository"]
        C["setup_node_js"]
        D["setup_python"]
        E["build_python_package"]
        F["install_node_dependencies"]
        G["run_semantic_release"]
        H["build_documentation"]
        I["checkout_gh_pages"]
        J["deploy_versioned_docs"]
        K["deploy_to_github_pages"]
    end
    
    subgraph "External Services"
        L["PyPI Registry"]
        M["GitHub Pages"]
        N["npm Registry"]
    end
    
    subgraph "Release Outputs"
        O["Git Tags"]
        P["GitHub Releases"]
        Q["PyPI Package"]
        R["Versioned Documentation"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    
    G --> L
    G --> O
    G --> P
    G --> Q
    K --> M
    K --> R
    F --> N
```

**Sources**: [.github/workflows/release_and_docs.yaml:1-159]()

## Release Workflow Components

The `release_and_docs` workflow in [.github/workflows/release_and_docs.yaml]() orchestrates the complete release pipeline:

### Build and Release Pipeline

```mermaid
graph LR
    subgraph "Build Stage"
        A["actions/checkout@v4"]
        B["actions/setup-node@v4"]
        C["actions/setup-python@v5"]
        D["python -m build"]
    end
    
    subgraph "Release Stage"
        E["npm install semantic-release"]
        F["npx semantic-release"]
        G["semantic-release-pypi"]
        H["git describe --tags"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
```

The pipeline uses specific versions and configurations:

| Component | Version/Configuration |
|-----------|----------------------|
| Node.js | 20 |
| Python | 3.12 |
| Build tool | `python -m build` |
| Package format | Wheel and source distribution |

**Sources**: [.github/workflows/release_and_docs.yaml:19-60]()

### Semantic Release Configuration

The release process uses `semantic-release` with a modular plugin architecture defined in `.releaserc.js`:

```mermaid
graph TD
    subgraph "semantic_release_plugins"
        A["@semantic-release/commit-analyzer"]
        B["@semantic-release/release-notes-generator"]
        C["semantic-release-pypi"]
        D["@semantic-release/github"]
        E["@semantic-release/git"]
    end
    
    subgraph "Plugin_Functions"
        F["Analyze commits for version bump"]
        G["Generate changelog from commits"]
        H["Publish to PyPI"]
        I["Create GitHub release"]
        J["Commit version updates"]
    end
    
    A --> F
    B --> G
    C --> H
    D --> I
    E --> J
```

**Sources**: [.releaserc.js:1-25]()

## Release and Documentation Deployment

The `release_and_docs` workflow handles automated releases when code is pushed to the `production` branch:

### Semantic Release Implementation

The complete release automation sequence follows this execution pattern:

```mermaid
graph LR
    subgraph "Release_Execution_Flow"
        A["npx_semantic_release"]
        B["git_describe_tags"]
        C["echo_version_GITHUB_OUTPUT"]
        D["conditional_docs_deployment"]
    end
    
    subgraph "Version_Detection_Logic"
        E["VERSION=$(git describe --tags --abbrev=0 --match v* 2>/dev/null || echo no-version)"]
        F["echo version=$VERSION >> $GITHUB_OUTPUT"]
    end
    
    A --> B
    B --> C
    B --> E
    E --> F
    C --> D
```

The plugin configuration in `.releaserc.js` defines branch targeting and asset management:

```javascript
// Key configuration from .releaserc.js
branches: ['production', 'main']
pypiPublish: true
repoUrl: 'https://upload.pypi.org/legacy/'
distDir: 'dist/'
assets: ['pyproject.toml']
```

**Sources**: [.releaserc.js:2-23](), [.github/workflows/release_and_docs.yaml:51-61]()

### Documentation Deployment System

The documentation deployment creates versioned documentation sites with automated switcher generation:

```mermaid
graph TD
    subgraph "Documentation_Build_Process"
        A["pip_install_e_ml_dev"]
        B["cd_docs_pip_install_r_docs_requirements"]
        C["make_html"]
        D["actions_checkout_gh_pages"]
    end
    
    subgraph "Version_Directory_Management"
        E["mkdir_p_gh_pages_VERSION"]
        F["rsync_av_delete_docs_build_html"]
        G["mkdir_p_gh_pages_latest"]
        H["rsync_av_delete_to_latest"]
    end
    
    subgraph "Switcher_JSON_Generation"
        I["collect_version_directories"]
        J["sort_V_r_versions"]
        K["generate_switcher_content"]
        L["write_switcher_json_to_all_versions"]
    end
    
    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L
```

The version detection logic ensures proper documentation organization:

```bash
# Version directory pattern matching from workflow
if [[ "$d" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || [[ "$d" == "latest" ]]; then
```

The `switcher.json` structure enables navigation between documentation versions:

```json
{
  "version": "latest", 
  "url": "https://baker-laboratory.github.io/atomworks-dev/latest/index.html",
  "name": "latest"
}
```

**Sources**: [.github/workflows/release_and_docs.yaml:63-148](), [docs/conf.py:72-76]()

## Documentation Configuration System

The documentation system uses Sphinx with automated version management integrated into the CI/CD pipeline:

### Sphinx Configuration Integration

```mermaid
graph TD
    subgraph "docs_conf_py_Configuration"
        A["atomworks.__version__"]
        B["version_match_regex"]
        C["switcher_version_extraction"]
        D["pydata_sphinx_theme"]
    end
    
    subgraph "Theme_Configuration"
        E["navbar_start_version_switcher"]
        F["switcher_json_url"]
        G["switcher_version_match"]
        H["logo_image_light_dark"]
    end
    
    A --> B
    B --> C
    C --> E
    E --> F
    F --> G
    D --> H
```

Version extraction logic in `docs/conf.py`:

```python
# Version processing from atomworks.__version__
version_match = re.match(r"^v?(\d+\.\d+\.\d+)", str(raw_version))
switcher_version = version  # Use clean version for matching
```

The theme configuration enables dynamic version switching:

```python
"switcher": {
    "json_url": "https://baker-laboratory.github.io/atomworks-dev/latest/_static/switcher.json",
    "version_match": switcher_version,
}
```

**Sources**: [docs/conf.py:20-38](), [docs/conf.py:72-76]()

## Quality Assurance Integration

The CI/CD pipeline includes quality indicators displayed in the `README.md`:

### Badge Integration

```mermaid
graph LR
    subgraph "CI_CD_Status_Badges"
        A["ruff_badge"]
        B["pypi_version_badge"]
        C["python_versions_badge"]
        D["documentation_status_badge"]
        E["license_badge"]
    end
    
    subgraph "External_Badge_Sources"
        F["astral_sh_ruff_endpoint"]
        G["pypi_org_project_atomworks"]
        H["baker_laboratory_github_io"]
        I["opensource_org_licenses"]
    end
    
    A --> F
    B --> G
    C --> G
    D --> H
    E --> I
```

**Sources**: [README.md:1-6]()

## Environment Variables and Secrets

The CI/CD pipeline uses GitHub Secrets for secure operations:

| Secret/Variable | Purpose | Workflow Usage |
|----------------|---------|----------------|
| `GITHUB_TOKEN` | GitHub API access | Release creation, Pages deployment |
| `PYPI_TOKEN` | PyPI publishing | `process.env.PYPI_TOKEN_PROD` in semantic-release |
| `PYPI_REPO_URL` | PyPI endpoint | `https://upload.pypi.org/legacy/` |

### Secret Configuration in Workflow

```yaml
# Environment variables in release_and_docs.yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  PYPI_TOKEN: ${{ secrets.PYPI_TOKEN_PROD }}
  PYPI_REPO_URL: https://upload.pypi.org/legacy/
```

The semantic release configuration accesses these through Node.js environment variables:

```javascript
// .releaserc.js secret access
pypiToken: process.env.PYPI_TOKEN_PROD
```

**Sources**: [.github/workflows/release_and_docs.yaml:53-57](), [.releaserc.js:13]()

## Workflow Triggers and Concurrency

### Trigger Configuration

The workflows are triggered by specific events to optimize resource usage:

```yaml
# lint_and_test triggers
on:
  push:
    branches: [main, dev, production]
    paths: ['src/**', 'tests/**', '.github/workflows/**']
  pull_request:
    branches: [main, dev, production]
  pull_request_target:
    types: [ready_for_review]
```

### Concurrency Management

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

This ensures that only one workflow runs per branch at a time, canceling previous runs when new commits are pushed.

**Sources**: [.github/workflows/lint_and_test.yaml:3-31](), [.github/workflows/release_and_docs.yaml:3-7]()

---