# Experimental compute platform

All computational experiments reported in this repository were executed on the
same dedicated workstation unless an experiment directory explicitly states
otherwise.

## Hardware and operating system

| Component | Configuration |
| --- | --- |
| CPU | AMD Ryzen Threadripper PRO 3945WX, 12 cores / 24 threads, up to approximately 4.43 GHz |
| System memory | 128 GB DDR4 RAM |
| Storage | 4 TB Kingston NVMe SSD |
| GPUs | 4 x NVIDIA RTX 4000 Ada Generation |
| GPU memory | 20,475 MiB per GPU |
| NVIDIA driver | 580.126.09 |
| CUDA | 13.0 |
| Operating system | Ubuntu 24.04.4 LTS |
| Kernel | Linux 6.8.0-111-generic |

## Experiment-specific use

The bounded-adaptation V2 and V2.1 experiments used the CPU-only
OpenCV-NumPy-Tesseract execution path with eight parallel CPU workers. The four
GPUs were installed and available but were not used for these experiments.
Other experiments in this repository may use the GPUs; their run manifests and
protocol files remain authoritative for workload-specific settings.

## Citation and reproducibility

The repository should archive the detailed configuration report as
`docs/hardware/Node01_hardware_configuration.pdf`. Publications should describe
the configuration above rather than relying only on the internal host name.

Recommended reference:

> Revival27 RDI Kft. (2026). *GPU Compute Workstation: Hardware Architecture and
> System Configuration*. Technical report.

For an archival publication reference, release the report through Zenodo or
another DOI-issuing repository and replace the technical-report citation with
the resulting persistent identifier.

