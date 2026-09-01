## OCR Segmentation Research Module

This module contains the complete experimental environment used for testing and validating the OCR segmentation pipeline, including the relevant source code, generated images, configuration files, batch execution scripts, and auxiliary test assets. The included datasets and license-plate fragments are synthetic, and the generated visual inputs are designed to provide controlled ground-truth conditions for algorithmic research without relying on real personal data, real vehicle identifiers, or legally sensitive image material.

The synthetic test setup supports reproducible evaluation of segmentation behaviour, geometric priors, detection stability, and batch-level performance across multiple input variants. Because the data are artificially generated and fully controlled, the environment is suitable for validating algorithmic assumptions while avoiding privacy, data protection, and personality-rights concerns.

The batch-runner environment was prepared for the SISY 2026 research workflow as an extension of the earlier CANDO-EPE implementation, where the pipeline was still primarily evaluated through a single-image IPS execution mode. The current structure enables systematic batch testing, result packaging, and comparative validation across multiple synthetic scenarios.

Unless an experiment directory states otherwise, the computational experiments
in this repository were executed on a dedicated workstation with an AMD Ryzen
Threadripper PRO 3945WX CPU (12 cores / 24 threads), 128 GB DDR4 RAM, a 4 TB
Kingston NVMe SSD, and four NVIDIA RTX 4000 Ada Generation GPUs with 20,475 MiB
VRAM each, under Ubuntu 24.04.4 LTS. The bounded-adaptation V2/V2.1 experiments
used the CPU-only OpenCV-NumPy-Tesseract path with eight CPU workers; the GPUs
were available but unused in those runs.

Full configuration and workload-specific scope: docs/hardware/HARDWARE.md.
