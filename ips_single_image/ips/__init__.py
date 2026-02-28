"""Inverse Packing Segmentation (IPS) - minimal single-image reference."""

from .preprocess import PreprocessConfig, make_mask
from .cc import connected_components
from .cuts import CutConfig
from .priors import ScoringConfig
from .search import SearchConfig, beam_search
from .ocr_backends import OCRConfig, ocr_segments
from .trace import hash_trace
from .viz import draw_segments
