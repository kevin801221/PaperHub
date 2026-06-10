# syntax=docker/dockerfile:1
#
# PaperHub backend image — uvicorn API server.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    # uv installs into a project venv at /app/.venv; put it on PATH so
    # console scripts (uvicorn, paperhub-*) resolve without `uv run`.
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# System deps:
#   - Full TeX Live set (mirrors reference/paper2slides-plus/Dockerfile) — a
#     HARD requirement for the `slides` intent (Beamer → pdflatex). The
#     metropolis theme + Fira fonts live in texlive-latex-extra/fonts-extra;
#     fonts-firacode adds Fira for the best metropolis output.
#   - Extended FONT set (the font-providing recommends of the texlive packages,
#     which --no-install-recommends would otherwise skip). Two purposes:
#       1. The Citation Canvas table-rasteriser compiles a standalone pdflatex
#          doc that inlines a paper's OWN preamble, so papers \usepackage font
#          packages absent from a fixed Debian TeX Live — e.g. tgcursor.sty from
#          `tex-gyre`, dropped by --no-install-recommends. Missing -> the table
#          silently degraded to a raw-text DUMP in deploy (dev's MiKTeX
#          auto-installs missing .sty on demand; Debian can't). arXiv:2506.10100.
#       2. Slide style customization (F4.2) lets users pick deck fonts — only
#          fonts actually present in the image are usable by Beamer/xelatex.
#     The non-font recommends (a JRE, gv/xpdf PDF viewers) are deliberately
#     excluded — useless for a headless compile. The table compile ALSO stubs
#     any still-missing .sty and retries (pipelines/table_figures.py), so a font
#     absent here can never re-introduce a raw-text dump — this set is for
#     fidelity (real fonts vs a stubbed fallback), not correctness.
#   - pandoc: optional LaTeX→HTML for the Citation Canvas (else pylatexenc).
#   - poppler-utils: PDF tooling used by the pipeline.
# BuildKit cache mounts keep downloaded .deb files + apt indices across builds,
# so a retry after a dropped connection only fetches what's still missing
# (TeX Live is hundreds of MB). `keep-downloaded-packages` stops the base
# image's docker-clean from deleting the cached debs; we therefore do NOT
# `rm -rf` the lists (the cache mount owns them).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache && \
    apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-lang-all \
    texlive-science \
    texlive-xetex \
    latexmk \
    chktex \
    fonts-firacode \
    fonts-noto-cjk \
    cm-super \
    lmodern \
    tex-gyre \
    tipa \
    texlive-plain-generic \
    texlive-fonts-extra-links \
    fonts-adf-accanthis \
    fonts-adf-berenis \
    fonts-adf-gillius \
    fonts-adf-universalis \
    fonts-cabin \
    fonts-cantarell \
    fonts-clear-sans \
    fonts-comfortaa \
    fonts-comic-neue \
    fonts-croscore \
    fonts-crosextra-caladea \
    fonts-crosextra-carlito \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-ebgaramond-extra \
    fonts-font-awesome \
    fonts-freefont-otf \
    fonts-freefont-ttf \
    fonts-gfs-artemisia \
    fonts-gfs-complutum \
    fonts-gfs-didot \
    fonts-gfs-neohellenic \
    fonts-gfs-olga \
    fonts-gfs-solomos \
    fonts-go \
    fonts-inter \
    fonts-lato \
    fonts-linuxlibertine \
    fonts-lobstertwo \
    fonts-noto-core \
    fonts-noto-mono \
    fonts-oflb-asana-math \
    fonts-open-sans \
    fonts-paratype \
    fonts-roboto-slab \
    fonts-roboto-unhinted \
    fonts-sil-andika \
    fonts-sil-charis \
    fonts-sil-gentium \
    fonts-sil-gentium-basic \
    fonts-sil-gentiumplus \
    fonts-sil-gentiumplus-compact \
    fonts-stix \
    pandoc \
    poppler-utils

# uv binary from its official distroless image (no pip-install-uv step).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Resolve dependencies first (cached across source edits). The BuildKit cache
# mount keeps the downloaded wheels across rebuilds so a failed build never
# re-downloads them.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now the source + install the project itself (uv_build).
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uvicorn", "paperhub.app:app", "--host", "0.0.0.0", "--port", "8000"]
