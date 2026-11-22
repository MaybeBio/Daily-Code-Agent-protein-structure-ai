# Contributing

Follow the [installation guide](https://github.com/CalzaAlessandro/cationize-protein/blob/HEAD/docs/INSTALL.md), then run the existing test
suite from the repository root:

```sh
python -B -m unittest discover -s tests -v
```

Report errors through the bug-report form. Include the command, version or
commit, Python and OS versions, a small input, the expected result and the error log.

Keep pull requests focused. When changing behavior, add a regression test and
state which tests you ran. For residue-library changes, include parameter
provenance and validation evidence. See [validation notes](https://github.com/CalzaAlessandro/cationize-protein/blob/HEAD/docs/VALIDATION.md).
