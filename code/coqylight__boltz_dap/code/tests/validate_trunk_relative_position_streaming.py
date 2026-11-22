import torch
from boltz.data import const

def make_features(n_tokens, device):
    chain_length = 533
    token_index = torch.arange(n_tokens, device=device)
    return {'asym_id': (token_index // chain_length).unsqueeze(0), 'residue_index': (token_index % chain_length).unsqueeze(0), 'entity_id': torch.zeros(1, n_tokens, dtype=torch.long, device=device), 'token_index': (token_index % chain_length).unsqueeze(0), 'sym_id': (token_index // chain_length).unsqueeze(0), 'cyclic_period': torch.zeros(1, n_tokens, dtype=torch.long, device=device)}

def make_contact_features(n_rows, n_tokens, device, *, varied):
    n_classes = len(const.contact_conditioning_info)
    contact_conditioning = torch.zeros(1, n_rows, n_tokens, n_classes, dtype=torch.float32, device=device)
    if varied:
        row_index = torch.arange(n_rows, device=device)[:, None]
        column_index = torch.arange(n_tokens, device=device)[None, :]
        labels = (row_index + column_index) % n_classes
        contact_conditioning.scatter_(-1, labels[None, :, :, None], 1.0)
    else:
        contact_conditioning[..., const.contact_conditioning_info['UNSELECTED']] = 1.0
    return {'contact_conditioning': contact_conditioning, 'contact_threshold': torch.full((1, n_rows, n_tokens), 10.0, dtype=torch.float32, device=device)}
