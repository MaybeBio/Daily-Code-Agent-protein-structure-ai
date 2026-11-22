

PLUMED employs a sophisticated multi-layered documentation architecture that integrates automatic code extraction with structured manual generation. The documentation system serves dual audiences: end-users requiring practical guidance for collective variable calculations and developers extending the framework through new actions and modules. This dual-track approach ensures that documentation evolves synchronously with code changes while maintaining clear separation between user-facing and developer-facing content.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L1-L20), [user-doc/Makefile](user-doc/Makefile#L1-L34)

## Documentation Architecture Overview

The documentation infrastructure comprises three interconnected documentation systems operating at different abstraction levels. The user documentation leverages Doxygen with custom processing to generate HTML pages that describe all available actions, collective variables, and command-line tools. Parallel to this, the developer documentation targets the C++ API and internal architecture for contributors extending PLUMED functionality. The new manual system represents an evolution toward Mkdocs-based documentation with modern theming and interactive features, designed to supersede the legacy Doxygen-based approach while maintaining compatibility with existing workflows.

This architecture implements a critical design principle: documentation is embedded directly within source code through specially formatted comment blocks, enabling automatic extraction and synchronization. When developers implement new actions, they are required to provide documentation through structured keyword registration and descriptive blocks, eliminating the possibility of undocumented functionality reaching users.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L20-L60), [new-manual/mkdocs.yml](new-manual/mkdocs.yml#L1-L57)

```mermaid
graph TB
    subgraph "Source Code"
        A[Action .cpp files<br/>with //+PLUMEDOC blocks]
        B[registerKeywords()<br/>method definitions]
        C[module.yml files<br/>with metadata]
    end

    subgraph "User Documentation Pipeline"
        D[extract script<br/>scans source files]
        E[Doxygen processing<br/>user-doc/Doxyfile]
        F[HTML generation<br/>with custom styling]
        G[Manual website<br/>plumed.org/doc]
    end

    subgraph "Developer Documentation Pipeline"
        H[go-doxygen<br/>developer-doc/]
        I[Developer Doxyfile<br/>API documentation]
        J[Developer HTML<br/>internal architecture]
    end

    subgraph "New Manual Pipeline"
        K[build_manual.py<br/>Python extraction]
        L[Mkdocs processing<br/>Material theme]
        M[Modern documentation<br/>with interactive features]
    end

    A --> D
    B --> D
    C --> D
    D --> E
    E --> F
    F --> G

    A --> H
    B --> H
    H --> I
    I --> J

    A --> K
    B --> K
    K --> L
    L --> M

    style G fill:#e1f5ff
    style J fill:#fff4e1
    style M fill:#f0e1ff
```

## Building User Documentation

The user documentation generation process begins with source code scanning through the `extract` script located in the `user-doc` directory. This script iterates through all C++ source files in `../src/*/*.cpp`, identifying actions registered with the `PLUMED_REGISTER_ACTION` macro and validating that each provides corresponding documentation through `PLUMEDOC` comment blocks. The extraction process generates intermediate files in an `automatic/` directory, creating glossary listings, module groupings, and individual action documentation pages that serve as input to Doxygen.

The `go-doxygen` shell script orchestrates the actual documentation generation by constructing a customized Doxygen configuration that incorporates the automatically extracted content with manually written pages. The script injects version information by querying the compiled PLUMED executable, ensuring that generated documentation accurately reflects the specific codebase version. Post-processing steps apply custom CSS styling through `plumed.css`, execute JavaScript transformations for interactive features via `plumed-syntax.awk`, and optionally generate PDF documentation through LaTeX compilation. The resulting HTML documentation provides comprehensive coverage of all PLUMED actions organized by module, with search capabilities and cross-references between related concepts.

Sources: [user-doc/extract](user-doc/extract#L1-L200), [user-doc/go-doxygen](user-doc/go-doxygen#L1-L146)

### Documentation Build Commands

Building the complete user documentation requires compilation of PLUMED itself, as the `extract` script queries the compiled executable for version information and available patch configurations. The standard build process executes through `make docs` when the `make_doc` configuration variable is enabled. This triggers the extraction pipeline followed by Doxygen generation, with optional PDF documentation controlled by the `make_pdfdoc` variable. Developers can check for broken examples or documentation errors using `make showerrors`, which executes the `report_errors` script to analyze generated documentation against the source code.

The build system validates documentation completeness by checking that every registered action has corresponding documentation, reporting violations to an errors file. It also extracts documentation for command-line tools by invoking each tool's `--description` and `--help` flags, automatically generating user-facing documentation for shell scripts and utilities. This comprehensive validation ensures that the generated documentation accurately represents the available functionality without orphaned or undocumented actions.

Sources: [user-doc/Makefile](user-doc/Makefile#L1-L34), [user-doc/extract](user-doc/extract#L200-L300)

## Building Developer Documentation

The developer documentation follows a streamlined build process designed for API and architectural documentation. The `developer-doc/go-doxygen` script configures Doxygen to process all C++ source files directly, targeting the internal codebase structure rather than the user-facing action documentation. This configuration disables reference relationship tracking to reduce generation time and focuses on class hierarchies, method signatures, and implementation details relevant to contributors extending PLUMED.

The developer Doxyfile is configured with output language set to English and UTF-8 encoding, with automatic extraction of documentation from source comments. Unlike the user documentation, this pipeline does not require intermediate extraction steps or post-processing, as the target audience requires direct access to code structure rather than the polished presentation needed by end users. The resulting documentation provides a complete API reference for internal classes, methods, and data structures that form the foundation of PLUMED's execution model.

Sources: [developer-doc/go-doxygen](developer-doc/go-doxygen#L1-L12), [developer-doc/Doxyfile](developer-doc/Doxyfile#L1-L100)

## In-Code Documentation Mechanism

The documentation system relies on structured comment blocks embedded directly within source code, enabling automatic extraction and synchronization. Actions must be documented using `//+PLUMEDOC` blocks that begin with the action name followed by optional tags for categorization. The comment block format follows GitHub-flavored markdown with PLUMED-specific extensions, supporting mathematical notation, bibliographic references, and HTML elements. The first paragraph serves as a brief description appearing in summary listings, while subsequent content provides detailed explanations for the dedicated action page.

Critical to the documentation philosophy is the integration with keyword registration through the static `registerKeywords` method. This method declares all input parameters, flags, and output values using the `PLMD::Keywords` interface, with each keyword requiring a descriptive explanation that becomes part of the generated documentation. Keywords support multiple attribute types: compulsory parameters requiring specification, optional parameters with default values, flags for boolean toggles, atom specifications, and numbered keyword sequences for repetitive parameters. The registration system enforces documentation completeness by preventing the parsing of undocumented keywords, creating a direct dependency between functionality and documentation.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L60-L120)

### Keyword Registration Patterns

The keyword registration system provides specialized methods for different parameter types, each with corresponding documentation requirements. Standard keywords use the `add()` method with attributes determining required/optional status and providing user-facing explanations. Input keywords that consume values from other actions utilize `addInputKeyword()`, which specifies acceptable types (scalar, vector, matrix, or grid) and enables type checking during input processing. Flags for boolean toggles employ `addFlag()` with default states, while numbered keyword sequences use `add()` with the numbered attribute to handle repetitions like `ATOM1`, `ATOM2`, `ATOM3`.

Output value documentation follows the same pattern through `setValueDescription()` and `addOutputComponent()` methods. These methods document the characteristics of values calculated by actions, distinguishing between scalar outputs and multi-component results accessible via dot notation. The registration system supports conditional components that appear only when specific keywords are present, with mechanisms to declare components as mandatory or optional based on action semantics. This comprehensive registration ensures that the generated documentation accurately reflects all available inputs and outputs with appropriate usage explanations.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L120-L250)

### Component Documentation Example

Actions generating multiple output values, such as those with the `COMPONENTS` keyword, must document each accessible component using `addOutputComponent()`. The method requires specifying the component name, the keyword that enables it, the value type, and a descriptive explanation. For actions that always generate specific components regardless of input configuration, the `componentsAreNotOptional()` method declares this behavior, simplifying component registration by removing keyword association requirements.

The MOVINGRESTRAINT action exemplifies this pattern, documenting bias and force2 components as always present while defining _cntr and _work components that scale with the number of input arguments. These component names combine argument names with descriptive suffixes, creating predictable output naming conventions. The registration system maps these documented components to actual calculation results, enabling users to reference individual outputs through the action label followed by component name.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L250-L300)

## Module Documentation System

PLUMED organizes actions into logical modules, each requiring two documentation files: `module.md` for descriptive content and `module.yml` for structured metadata. The markdown file provides module overview, usage guidance, and conceptual explanations using the same GitHub-flavored markdown syntax as action documentation. This content appears on the module's dedicated documentation page, offering context for understanding the collective purpose of actions within the module.

The YAML file contains structured metadata including module name, author list, description, DOI references for relevant publications, and tag definitions with explanations. Tags defined here become available for action categorization, enabling cross-module organization without rigid taxonomic constraints. Actions declare tag membership by including tag names on their `PLUMEDOC` line, creating flexible groupings that facilitate discovery of related functionality across module boundaries. This tag-based system supports community-driven organization, allowing contributors to define meaningful categories without restructuring the codebase.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L350-L438)

### Module YAML Structure

```yaml
name: module_identifier
authors: Author One, Author Two
description: Comprehensive description of module purpose
dois: ["doi:10.1234/example.doi", "doi:10.5678/another.doi"]
tags:
  DISTANCE: "Actions involving distance calculations"
  ANGLE: "Actions involving angle measurements"
  ENERGY: "Actions related to energy calculations"
```

The DOI references specified in module documentation enable automatic citation generation and linking to peer-reviewed publications, supporting PLUMED's philosophy that comprehensive documentation exists in the literature using the software. When actions are documented with `addDOI()` calls, citations automatically appear on action pages, connecting implementation details to the theoretical foundations published in research articles.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L300-L350)

## New Manual System

The `new-manual/` directory represents the next-generation documentation system built on Mkdocs with the Material theme, offering modern styling, dark mode support, and enhanced search capabilities. This system leverages Python scripts in `build_manual.py` to extract documentation from source code, processing action descriptions with parallel processing for efficiency and generating markdown files that Mkdocs compiles into static HTML. The system maintains compatibility with existing source documentation practices while providing a more flexible and maintainable foundation for future documentation evolution.

The Mkdocs configuration defines navigation structure linking to external tutorial resources on plumed-tutorials.org, integration with the PLUMED GitHub repository, and developer documentation hosted in a separate HTML tree. Custom CSS and JavaScript files extend the base theme with PLUMED-specific styling, table functionality through DataTables, mathematical rendering via MathJax, and diagram capabilities through Mermaid. This comprehensive toolset enables rich documentation with interactive examples, code snippets, and visual explanations that enhance user understanding of complex collective variable concepts.

Sources: [new-manual/build_manual.py](new-manual/build_manual.py#L1-L200), [new-manual/mkdocs.yml](new-manual/mkdocs.yml#L1-L57)

## Continuous Documentation Deployment

PLUMED implements automated documentation generation through Travis CI and GitHub Actions, ensuring that documentation stays synchronized with code changes. The continuous integration system builds documentation automatically on successful test completion, deploying to version-specific repositories under the plumed organization on GitHub. Each branch generates documentation at a corresponding repository URL, enabling version-aligned documentation that matches the specific codebase state.

The deployment mechanism handles version detection through environment variables, substituting branch names into documentation headers and navigation links. Coverage scans generate separate repositories containing regression test coverage data, providing transparency into which code paths are validated by automated tests. This automated pipeline eliminates manual documentation deployment steps while ensuring that only passing builds generate published documentation, preventing broken or incomplete documentation from reaching users.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L380-L438)

## Documentation Quality Assurance

The documentation build process includes multiple validation checks that detect common errors and inconsistencies. The extraction script identifies registered actions without corresponding documentation, reporting violations to an errors file for developer attention. Example testing validates that code snippets presented in documentation execute successfully without syntax errors or runtime failures. Spelling checks using a custom dictionary ensure consistent terminology and catch typos in user-facing text.

These quality assurance mechanisms operate during documentation generation rather than requiring separate validation steps, integrating documentation health checks into the standard development workflow. The `report_errors` script aggregates findings from multiple validation sources, presenting developers with actionable feedback on documentation completeness and accuracy. This comprehensive validation ensures that published documentation maintains high quality standards while minimizing additional overhead for contributors.

Sources: [user-doc/extract](user-doc/extract#L1-L50), [user-doc/report_errors](user-doc/report_errors), [user-doc/go-spelling](user-doc/go-spelling)

> [!TIP]
> The documentation system enforces completeness by requiring keyword registration before action input parsing, making it impossible to add undocumented parameters. This design ensures documentation evolves synchronously with code changes, preventing the common problem of orphaned functionality reaching users without corresponding documentation.

## Integration with External Resources

PLUMED documentation maintains extensive cross-referencing to external educational resources, particularly the PLUMED tutorials site (plumed-tutorials.org) and the PLUMED nest repository (plumed-nest.org). These connections support the documentation philosophy that practical examples and tutorials provide superior learning opportunities compared to comprehensive reference materials. Manual pages link to tutorials demonstrating specific calculations, while tutorial content references manual entries for detailed parameter explanations.

The bibliography system leverages DOIs to automatically generate citation information and links to peer-reviewed publications, connecting code implementation details to theoretical foundations. When actions document methods with `addDOI()` calls, the documentation system retrieves citation metadata from DOI resolution services, presenting formatted references alongside usage instructions. This integration ensures that users can trace the scientific basis of PLUMED functionality back to the original research publications, supporting reproducibility and proper citation in academic work.

Sources: [developer-doc/usingDoxygen.md](developer-doc/usingDoxygen.md#L1-L20)

## Next Steps

Understanding PLUMED's documentation architecture provides the foundation for effectively extending and maintaining the system. For practical experience implementing actions, refer to [Creating New CVs](24-creating-new-cvs) which demonstrates the registration and documentation patterns in concrete examples. The [Regression Testing Framework](27-regression-testing-framework) explains how to validate that your documented examples function correctly, while [Continuous Integration and Code Coverage](29-continuous-integration-and-code-coverage) describes how documentation quality checks integrate with automated testing.

For comprehensive understanding of PLUMED's action framework, the [Action Framework and Execution Model](6-action-framework-and-execution-model) provides the theoretical foundation for why documentation is structured around keyword registration and static initialization methods. When contributing to PLUMED, [How to Contribute to PLUMED](developer-doc/HowToContributeToPlumed.md) offers additional guidance on documentation standards and community expectations.