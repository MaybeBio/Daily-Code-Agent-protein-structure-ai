#include "./src/box.h"
#include <stdio.h>

int main() {
  printf("    ________________________________________ \n");
  printf("   |                                        |\n");
  printf("   |  Let there be jiggly and wiggly atoms  |\n");
  printf("   |________________________________________|\n\n\n");

  Box box = {{2.3, 3.2, 5.1}, 'f'}; 

  printf("The dimension of box is: %.2lf, %.2lf, %.2lf\n", box.dimension.x, box.dimension.y, box.dimension.z);

  return 0;
}
