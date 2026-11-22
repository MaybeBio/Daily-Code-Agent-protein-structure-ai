from molsysmt._private.argdigest import arg_digest


@arg_digest(form="biopython.Seq")
def copy(item, skip_digestion=False):
    """Creating an independent copy of a Biopython sequence.

    Parameters
    ----------
    item : biopython.Seq
        Source sequence to copy.
    skip_digestion : bool, default=False
        Whether to skip MolSysMT's internal argument digestion mechanism.

    Returns
    -------
    biopython.Seq
        Independent object preserving source content.

    Examples
    --------
    >>> from Bio.Seq import Seq
    >>> molsys = Seq('AGX')
    >>> copied = copy(molsys)
    >>> copied is molsys
    False
    >>> str(copied)
    'AGX'

    .. versionadded:: 1.0.0
    """
    from copy import deepcopy

    return deepcopy(item)
