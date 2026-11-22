from protein_function_predictor.embedding import ProteinEmbedder


def main() -> None:
    sequence = (
        "MALWMRLLPLLALLALWGPDPAAAFVNQHLCGSHLVEALYLVCGERGFFYTPKTR"
        "REAEDLQVGQVELGGGPGAGSLQPLALEGSLQKRGIVEQCCTSICSLYQLENYCN"
    )


    embedder = ProteinEmbedder()

    embedding = embedder.embed(sequence)

    print(f"Embedding shape: {embedding.shape}")
    print(f"Embedding dtype: {embedding.dtype}")
    print(f"First 10 values: {embedding[:10]}")

if __name__ == "__main__":
    main()