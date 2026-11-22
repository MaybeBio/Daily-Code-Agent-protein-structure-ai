To use the actions in this module you have to construct an adjacency matrix using one of the methods from the [adjmat](https://github.com/plumed/plumed2/blob/HEAD/src/clusters/module_adjmat.md) module.
The [DFSCLUSTERING](https://github.com/plumed/plumed2/blob/HEAD/src/clusters/DFSCLUSTERING.md) takes an adjacency matrix in input and finds the various connected components in the graph that is represented
by that adjacency matrix.  This form analysis is useful if you are looking at a phenomenon such as nucleation where the aim is to detect the sizes of the crystalline nuclei that have formed
in your simulation cell.
