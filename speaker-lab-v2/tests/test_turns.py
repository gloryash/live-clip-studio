import numpy as np

from speaker_lab_v2.turns import aggregate_acoustic_turns


def test_acoustic_turns_merge_contiguous_same_voice_and_split_changes():
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    embeddings = np.vstack([a, a, a, b, b, b, a, a, a])
    rows = [
        {"index": index, "start": float(index), "end": float(index + 1)}
        for index in range(len(embeddings))
    ]

    turns = aggregate_acoustic_turns(embeddings, rows, random_state=0)

    assert len(turns.embeddings) == 3
    assert turns.member_positions == ((0, 1, 2), (3, 4, 5), (6, 7, 8))
    assert sum(len(group) for group in turns.member_positions) == len(embeddings)


def test_uniform_contiguous_voice_becomes_one_turn_without_gmm_failure():
    embeddings = np.repeat([[1.0, 0.0]], 5, axis=0)
    rows = [
        {"index": index, "start": float(index), "end": float(index + 1)}
        for index in range(len(embeddings))
    ]

    turns = aggregate_acoustic_turns(embeddings, rows, random_state=0)

    assert len(turns.embeddings) == 1
    assert turns.member_positions == ((0, 1, 2, 3, 4),)
