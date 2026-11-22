import torch
from transformers import AutoTokenizer, EsmModel

MODEL_CHECKPOINT = "facebook/esm2_t6_8M_UR50D"

MAX_SEQUENCE_LENGTH = 1024

VALID_AMINO_ACIDS = set(
    "ACDEFGHIKLMNPQRSTVWY"
)


class ProteinEmbedder:
    """Generate protein embeddings using pretrained ESM2."""

    def __init__(
        self,
        model_checkpoint: str = MODEL_CHECKPOINT,
        device: str | None = None,
    ):
        self.model_checkpoint = model_checkpoint

        self.tokenizer = AutoTokenizer.from_pretrained(
            model_checkpoint
        )

        self.model = EsmModel.from_pretrained(
            model_checkpoint
        )

        if device is None:
            device = (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )

        self.device = torch.device(device)

        self.model.to(self.device)
        self.model.eval()

    @staticmethod
    def validate_sequence(
        sequence: str,
    ) -> str:
        sequence = "".join(
            sequence.split()
        ).upper()

        if not sequence:
            raise ValueError(
                "Protein sequence cannot be empty."
            )

        if len(sequence) > MAX_SEQUENCE_LENGTH:
            raise ValueError(
                "Protein sequence exceeds maximum "
                f"length of {MAX_SEQUENCE_LENGTH} residues."
            )

        invalid = (
            set(sequence)
            - VALID_AMINO_ACIDS
        )

        if invalid:
            raise ValueError(
                "Sequence contains invalid amino acids: "
                f"{sorted(invalid)}"
            )

        return sequence

    def embed_batch(
        self,
        sequences: list[str],
    ) -> torch.Tensor:
        """Embed a batch of protein sequences."""

        if not sequences:
            raise ValueError(
                "Sequence batch cannot be empty."
            )

        sequences = [
            self.validate_sequence(sequence)
            for sequence in sequences
        ]

        inputs = self.tokenizer(
            sequences,
            return_tensors="pt",
            padding=True,
            return_special_tokens_mask=True,
        )

        special_tokens_mask = inputs.pop(
            "special_tokens_mask"
        )

        inputs = {
            key: value.to(self.device)
            for key, value in inputs.items()
        }

        special_tokens_mask = (
            special_tokens_mask.to(
                self.device
            )
        )

        with torch.inference_mode():
            outputs = self.model(**inputs)

        token_embeddings = (
            outputs.last_hidden_state
        )

        residue_mask = (
            inputs["attention_mask"].bool()
            & ~special_tokens_mask.bool()
        )

        residue_mask_float = (
            residue_mask
            .unsqueeze(-1)
            .to(token_embeddings.dtype)
        )

        summed_embeddings = (
            token_embeddings
            * residue_mask_float
        ).sum(dim=1)

        residue_counts = (
            residue_mask_float
            .sum(dim=1)
        )

        protein_embeddings = (
            summed_embeddings
            / residue_counts
        )

        return protein_embeddings.cpu()

    def embed(
        self,
        sequence: str,
    ) -> torch.Tensor:
        """Embed one protein sequence."""

        return self.embed_batch(
            [sequence]
        )[0]
