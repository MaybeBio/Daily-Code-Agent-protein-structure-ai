maze is a module for PLUMED2, which implements enhanced sampling methods for 
ligand unbinding from protein tunnels. The maze module is developed and 
maintained by [Jakub Rydzewski](http://www.fizyka.umk.pl/~jr) at the Institute 
of Physics, Nicolaus Copernicus University, Torun, Poland. See this 
[link](https://www.fizyka.umk.pl/~jr/maze.html) for additional information.

The method, which is discussed in the papers cited below, finds unbinding pathways by repeatedly minimizing
a coarse-grained loss function ([MAZE_LOSS](https://github.com/plumed/plumed2/blob/HEAD/src/maze/MAZE_LOSS.md)) that measures the ligand-protein interactions.
An optimizer (for example [MAZE_MEMETIC_SAMPLING](https://github.com/plumed/plumed2/blob/HEAD/src/maze/MAZE_MEMETIC_SAMPLING.md), [MAZE_SIMULATED_ANNEALING](https://github.com/plumed/plumed2/blob/HEAD/src/maze/MAZE_SIMULATED_ANNEALING.md)
or [MAZE_RANDOM_WALK](https://github.com/plumed/plumed2/blob/HEAD/src/maze/MAZE_RANDOM_WALK.md)) finds the direction along which the loss decreases, i.e. the direction where the
ligand has the most room to move, and [MAZE_OPTIMIZER_BIAS](https://github.com/plumed/plumed2/blob/HEAD/src/maze/MAZE_OPTIMIZER_BIAS.md) pushes the ligand along this direction.
A typical input thus contains a MAZE_LOSS action, one optimizer and a MAZE_OPTIMIZER_BIAS action.

The maze module is an optional module for PLUMED2 that needs to be enabled when 
configuring the compilation of PLUMED2. You can either pass a flag
`--enable-modules=maze` or a `--enable-modules=all` when running the 
configure script. 
