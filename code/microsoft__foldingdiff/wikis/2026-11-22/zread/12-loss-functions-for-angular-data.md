

The foldingdiff library implements specialized loss functions designed to handle the unique challenges of angular data in protein structure prediction. Unlike traditional Euclidean coordinates, angular values exist on a circular manifold where the shortest distance between two angles must account for periodic wrapping around the unit circle.

## Angular Loss Functions

The core challenge with angular data is that standard loss functions fail to recognize that angles separated by 2π are equivalent. The library provides two primary angular loss functions that address this fundamental issue.

### Radian L1 Loss

The `radian_l1_loss` function computes the minimal angular distance between input and target angles by normalizing both to the range [0, 2π) and then calculating the wrapped difference [foldingdiff/losses.py#L12-L28](foldingdiff/losses.py#L12-L28):

```python
def radian_l1_loss(input: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    target = target % (2 * torch.pi)
    input = input % (2 * torch.pi)
    d = target - input
    d = (d + torch.pi) % (2 * torch.pi) - torch.pi
    retval = torch.abs(d)
    return torch.mean(retval)
```

This implementation ensures that the difference between 0.1 and 2π-0.1 is correctly computed as 0.2, rather than the naive difference of ~6.08.

### Radian Smooth L1 Loss

The `radian_smooth_l1_loss` extends the Smooth L1 loss concept to angular data, providing better gradient properties for optimization [foldingdiff/losses.py#L29-L65](foldingdiff/losses.py#L29-L65):

```python
def radian_smooth_l1_loss(
    input: torch.Tensor,
    target: torch.Tensor,
    beta: float = 1.0,
    circle_penalty: float = 0.0,
) -> torch.Tensor:
    d = target - input
    d = utils.modulo_with_wrapped_range(d, -torch.pi, torch.pi)
    
    abs_d = torch.abs(d)
    retval = torch.where(abs_d < beta, 0.5 * (d**2) / beta, abs_d - 0.5 * beta)
```

The function uses quadratic loss for small differences (|δ| < β) and linear loss for larger differences, with the modulo operation ensuring proper angular wrapping. An optional `circle_penalty` term regularizes against excessive rotations around the circle.

> [!TIP]
> The angular loss functions rely on the `modulo_with_wrapped_range` utility function [foldingdiff/utils.py#L84-L107](foldingdiff/utils.py#L84-L107), which handles negative ranges correctly—a critical requirement for angular computations where the range is typically [-π, π].

## Pairwise Distance Loss

For structural validation, the library implements a rotation and translation invariant loss based on pairwise distances between 3D coordinates [foldingdiff/losses.py#L101-L151](foldingdiff/losses.py#L101-L151):

```python
def pairwise_dist_loss(
    input: torch.Tensor,
    target: torch.Tensor,
    lengths: Optional[torch.Tensor] = None,
    weights: Optional[torch.Tensor] = None,
):
    input_dists, input_mask = _get_pairwise_dist_batch(input, lengths)
    target_dists, target_mask = _get_pairwise_dist_batch(target, lengths)
    
    loss = F.mse_loss(
        input_dists[torch.where(input_mask)],
        target_dists[torch.where(target_mask)],
        reduction="none",
    )
```

This function computes all pairwise distances within each protein structure and compares them using MSE loss. Since distances are invariant to rotation and translation, this loss provides a robust measure of structural similarity independent of coordinate system.

## Integration with Training Pipeline

The loss functions are integrated into the training pipeline through the `BertForDiffusion` class, which maintains dictionaries mapping loss keys to appropriate functions [foldingdiff/modelling.py#L224-L237](foldingdiff/modelling.py#L224-L237):

```python
nonangular_loss_fn_dict = {
    "l1": F.l1_loss,
    "smooth_l1": F.smooth_l1_loss,
}

angular_loss_fn_dict = {
    "l1": losses.radian_l1_loss,
    "smooth_l1": functools.partial(
        losses.radian_smooth_l1_loss, beta=torch.pi / 10
    ),
}
```

The model automatically selects between angular and non-angular loss functions based on the `ft_is_angular` parameter, which specifies which features represent angular values. This allows the same training pipeline to handle mixed data types seamlessly.

## Loss Function Characteristics

| Loss Function | Data Type | Invariance Properties | Use Case |
|---------------|-----------|----------------------|----------|
| `radian_l1_loss` | Angular | Periodic wrapping | Basic angular regression |
| `radian_smooth_l1_loss` | Angular | Periodic wrapping + smooth gradients | Training stability |
| `pairwise_dist_loss` | 3D Coordinates | Rotation + translation | Structural validation |

> [!TIP]
> The angular loss functions are extensively tested for periodic invariance. The test suite verifies that adding any integer multiple of 2π to either input or target produces identical loss values [tests/test_losses.py#L67-L95](tests/test_losses.py#L67-L95).

## Implementation Details

The angular loss implementations handle several edge cases critical for robust training:

1. **Periodic Boundary**: All angular differences are wrapped to the range [-π, π] using the modulo operation
2. **Numerical Stability**: The smooth L1 loss includes assertions to prevent negative loss values
3. **Batch Processing**: Functions support batch operations with proper masking for variable-length sequences
4. **Gradient Flow**: The smooth L1 variant provides well-behaved gradients near zero differences

These specialized loss functions enable effective training of diffusion models on angular protein representations, ensuring that the geometric constraints of angular data are properly respected during the learning process.

For understanding how these loss functions integrate with the broader training architecture, see [Lightning Training Pipeline](13-lightning-training-pipeline). The angular data representation that these losses operate on is described in [Angle-based Protein Representation](7-angle-based-protein-representation).