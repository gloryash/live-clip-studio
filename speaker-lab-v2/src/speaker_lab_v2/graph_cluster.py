from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import laplacian
from scipy.sparse.linalg import eigsh
from sklearn.cluster import KMeans


@dataclass(frozen=True)
class SpectralResult:
    labels: np.ndarray
    speaker_count: int
    neighbor_count: int
    eigengap: float
    eigenvalues: tuple[float, ...]


def _normalized_rows(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    norms = np.linalg.norm(values, axis=1)
    if np.any(norms <= 1e-9):
        raise ValueError("zero-length embedding")
    return values / norms[:, None]


def _sparse_affinity(similarity: np.ndarray, neighbor_count: int) -> sparse.csr_matrix:
    sample_count = len(similarity)
    keep = min(neighbor_count, sample_count - 1)
    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    for row in range(sample_count):
        scores = similarity[row].copy()
        scores[row] = -np.inf
        indexes = np.argpartition(scores, -keep)[-keep:]
        for column in indexes:
            value = max(0.0, float(scores[column]))
            if value > 0:
                rows.append(row)
                columns.append(int(column))
                values.append(value)
    directed = sparse.csr_matrix((values, (rows, columns)), shape=similarity.shape)
    affinity = directed.maximum(directed.T)
    affinity.setdiag(0.0)
    affinity.eliminate_zeros()
    return affinity


def _smallest_eigenpairs(
    matrix: sparse.spmatrix, count: int
) -> tuple[np.ndarray, np.ndarray]:
    size = matrix.shape[0]
    if size <= 256:
        eigenvalues, eigenvectors = np.linalg.eigh(matrix.toarray())
        return eigenvalues[:count], eigenvectors[:, :count]
    eigenvalues, eigenvectors = eigsh(
        matrix,
        k=count,
        which="SM",
        v0=np.ones(size, dtype=np.float64),
    )
    order = np.argsort(eigenvalues)
    return eigenvalues[order], eigenvectors[:, order]


def _canonical_labels(labels: np.ndarray) -> np.ndarray:
    mapping: dict[int, int] = {}
    result = np.empty_like(labels)
    for index, label in enumerate(labels.tolist()):
        mapping.setdefault(int(label), len(mapping))
        result[index] = mapping[int(label)]
    return result


def nme_spectral_cluster(
    embeddings: np.ndarray,
    *,
    neighbor_counts: tuple[int, ...] = (5, 10, 20, 40, 80),
    min_speakers: int = 2,
    max_speakers: int = 8,
    random_state: int = 0,
) -> SpectralResult:
    embeddings = _normalized_rows(embeddings)
    sample_count = len(embeddings)
    if sample_count < min_speakers:
        return SpectralResult(
            labels=np.zeros(sample_count, dtype=int),
            speaker_count=1,
            neighbor_count=max(0, sample_count - 1),
            eigengap=0.0,
            eigenvalues=(0.0,),
        )
    similarity = np.clip(embeddings @ embeddings.T, 0.0, 1.0)
    eigen_count = min(max_speakers + 1, sample_count)
    best: tuple[float, int, int, np.ndarray, np.ndarray] | None = None
    for requested_neighbors in neighbor_counts:
        neighbors = min(requested_neighbors, sample_count - 1)
        if neighbors < 1:
            continue
        affinity = _sparse_affinity(similarity, neighbors)
        normalized_laplacian = laplacian(affinity, normed=True)
        eigenvalues, eigenvectors = _smallest_eigenpairs(
            normalized_laplacian, eigen_count
        )
        for speakers in range(min_speakers, min(max_speakers, len(eigenvalues) - 1) + 1):
            gap = max(0.0, float(eigenvalues[speakers] - eigenvalues[speakers - 1]))
            normalized_gap = gap / max(abs(float(eigenvalues[speakers])), 1e-6)
            candidate = (
                normalized_gap,
                -neighbors,
                speakers,
                eigenvalues,
                eigenvectors,
            )
            if best is None or candidate[:3] > best[:3]:
                best = candidate
    if best is None:
        raise RuntimeError("could not build a spectral graph")
    normalized_gap, negative_neighbors, speakers, eigenvalues, eigenvectors = best
    spectral = eigenvectors[:, :speakers]
    norms = np.linalg.norm(spectral, axis=1, keepdims=True)
    spectral = spectral / np.maximum(norms, 1e-9)
    labels = KMeans(
        n_clusters=speakers,
        n_init=20,
        random_state=random_state,
    ).fit_predict(spectral)
    labels = _canonical_labels(np.asarray(labels, dtype=int))
    raw_gap = float(eigenvalues[speakers] - eigenvalues[speakers - 1])
    return SpectralResult(
        labels=labels,
        speaker_count=speakers,
        neighbor_count=-negative_neighbors,
        eigengap=raw_gap,
        eigenvalues=tuple(float(value) for value in eigenvalues),
    )
