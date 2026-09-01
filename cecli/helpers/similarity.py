def normalize_vector(vector):
    """Normalize a vector to unit length (L2 norm).

    Args:
        vector (list): Input vector

    Returns:
        list: Normalized vector with length 1
    """
    import math

    magnitude = math.sqrt(sum(x * x for x in vector))
    if magnitude == 0:
        return list(vector)  # Return copy if zero vector
    return [x / magnitude for x in vector]


def cosine_similarity(vector1, vector2):
    """Calculate cosine similarity between two vectors.

    Args:
        vector1 (list): First vector
        vector2 (list): Second vector

    Returns:
        float: Cosine similarity between the vectors (range: -1 to 1)
    """
    import math

    if len(vector1) != len(vector2):
        raise ValueError("Vectors must have the same length")

    dot_product = sum(a * b for a, b in zip(vector1, vector2))
    magnitude1 = math.sqrt(sum(x * x for x in vector1))
    magnitude2 = math.sqrt(sum(x * x for x in vector2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0  # Return 0 if either vector is zero

    return dot_product / (magnitude1 * magnitude2)


def create_bigram_vector(texts):
    """Create a bigram frequency vector.

    Args:
        texts (tuple): Tuple of strings to process

    Returns:
        list: Vector of bigram frequencies
    """
    # Pre-compute bigram indices (0 for 'aa', 1 for 'ab', ..., 675 for 'zz')
    bigram_indices = {}
    idx = 0
    for i in range(ord("a"), ord("z") + 1):
        for j in range(ord("a"), ord("z") + 1):
            bigram = chr(i) + chr(j)
            bigram_indices[bigram] = idx
            idx += 1

    # Initialize frequency vector
    vector = [0] * (26 * 26)

    # Process all texts
    for text in texts:
        text_lower = text.lower()
        if len(text_lower) < 2:
            continue

        # Create bigrams by combining consecutive characters
        for i in range(len(text_lower) - 1):
            bg = text_lower[i : i + 2]
            # Filter only alphabetic bigrams
            if bg.isalpha() and bg in bigram_indices:
                vector[bigram_indices[bg]] += 1

    return vector
